# Zuma for Home Assistant

Local control of [Zuma](https://zuma.ai) ceiling speaker-lights (Lumisonic / Zuma SL)
over the undocumented StreamUnlimited StreamSDK HTTP API the units expose on port 80.

No cloud, no account, no API key — the API needs no authentication at all.

## What this controls

| Entity | Backing node | Notes |
|---|---|---|
| `light` | `zuma:lightState` | on/off, brightness, colour temperature (2200–6500 K) |
| `media_player` volume | `player:volume` | 0–100 on the device, mapped to HA's 0.0–1.0 |
| `media_player` mute | `settings:/mediaPlayer/mute` | |
| `media_player` state | `player:player/data` | `stopped` / `playing` / `paused` |
| `media_player` pause / stop | `player:player/control` | `{"control": "pause"\|"stop"}` |
| `media_player` next / previous | `player:player/control` | advertised only when `controls.next_` / `.previous` are true; live radio reports false |
| `media_player` play URL | DLNA `AVTransport` (renderer) | `media_player.play_media` — starts a stream URL the nsdk API can't originate |
| `media_player` now playing | `player:player/data` | title, artwork URL, `zuma_service` attribute |
| `switch` circadian lighting | `settings:/zuma/circadianLighting` | |
| `switch` status LED curfew | `settings:/zuma/ledCurfewEnabled` | diagnostic, config category |

Devices are discovered automatically over mDNS (`_sues800device._tcp`), whose TXT
record carries the serial used as the unique ID. Manual setup by IP also works.

## What this does *not* control, and why

**Lamp brightness and colour temperature are not available over HTTP.** This isn't an
omission — all 365 nodes under `settings:/` and `player:` were enumerated, and the only
light-related ones are `circadianLighting` (a mode toggle), `ledCurfew*` (the small
status LED), and `ui/displayBrightness` (the StreamSDK display). There is no brightness,
CCT, or on/off node for the lamp itself.

### The light — controllable over plain HTTP after all

Brightness, colour temperature and power are all live on the LAN HTTP API, no auth:

    zuma:lightState = {
      "type": "zumaLightState",
      "zumaLightState": {
        "power": true,
        "brightness": 25,           # 0-100
        "temperature": 3869,        # Kelvin
        "lastTransitionPeriod": "ms1000"
      }
    }

The catch that hid this for a while: `settings:/zuma/lightState` is flagged
`"internal": true` (confirmed in the firmware's `settings-default/zuma/*`), so
enumeration never lists it and `getData` returns "Node is internal". But the
device also mirrors the lamp into the **`zuma:` volatile namespace**, and
`zuma:lightState` is served over the LAN read *and* write. `getData`/`setData`
it like any other node; the value is a composite tagged `zumaLightState` rather
than a scalar.

Findings that shaped the `light` entity:
- **Temperature**: the firmware tolerates 1000–8000 K but the entity clamps to
  2200–6500 K, the range a fixture actually renders.
- **Brightness and power are independent** — writing `brightness: 0` leaves
  `power: true` (on but dark), so turn-off sets `power: false` and keeps the
  brightness value, and the lamp restores its level on turn-on.
- **Transition** enum: `instant, ms125, ms250, ms500, ms1000, ms2000, ms4000`;
  HA's transition seconds snap to the nearest bucket.

No DTLS, no CoAP, no per-device key needed. (For the record: the CoAP/DTLS
bridge on 5684 authenticates with a per-device X.509 cert+key stored in the
internal `settings:/zuma/factoryCert` / `factoryKey` nodes — the intended
off-device path — but the `zuma:` mirror makes it unnecessary.)

Architecture note: the mDNS TXT record's `master=1` / `group=<uuid>` mean one unit per
area is the master and fans out to the rest over KleerNet — a light integration should
target the master, not each downlight.

## Install

HACS → three-dot menu → Custom repositories → this repo, category *Integration*.
Then Settings → Devices & Services → Add Integration → **Zuma**.

Or copy `custom_components/zuma/` into your HA `config/custom_components/`.

## Playing a stream URL (internet radio, etc.)

The nsdk API can pause/stop/skip but cannot *start* a URL. The same unit also runs a
Rygel DLNA MediaRenderer, which can — so `media_player.play_media` bridges to it:

```yaml
action: media_player.play_media
target:
  entity_id: media_player.bathroom
data:
  media_content_id: https://playerservices.streamtheworld.com/api/livestream-redirect/RADIO_RENASCENCA.mp3
  media_content_type: music
```

This is the standard Home Assistant service — no custom action. Under the hood the
integration finds the renderer via a unicast SSDP M-SEARCH each call (its port is
ephemeral and moves across reboots) and issues `SetAVTransportURI` + `Play`. Volume,
mute, pause and stop then work on the stream through the nsdk API as usual.

**Format limits (the renderer probes the URL and enforces these):** MP3
(`audio/mpeg`) and clean AAC/MP4 play. **HLS (`.m3u8`) and ICY `audio/aacp` do not** —
notably streamtheworld's `.aac` mounts serve `audio/aacp` and are refused, so use the
station's `.mp3` mount. The entity also accepts HA media-source items (TTS, the media
browser), not only raw URLs.

## The device API, for reference

Port 80, plaintext, unauthenticated:

```
GET  /api/getData?path=<path>&roles=<comma,separated>
GET  /api/getRows?path=<path>&roles=<r>&from=<i>&to=<i>
POST /api/setData   {"path":..,"role":..,"value":..}
GET  /api/event/modifyQueue?queueId=&subscribe=[..]&unsubscribe=[..]
GET  /api/event/pollQueue?queueId=&timeout=<ms>
```

Two things will trip you up:

1. **Values are tagged unions.** A read returns `[{"i32_": 22, "type": "i32_"}]`, and a
   write must re-tag with the matching type name. Booleans must be tagged `bool_`, not
   `i32_`, even though Python's `bool` is an `int`.
2. **Errors come back as HTTP 500 with a JSON body**, not as a transport failure:
   `{"error": {"name": "CMAbstractWorker::invalidPath", "message": "..."}}`.

Useful roles: `value`, `title`, `type`, `path`. Enumerate a container with
`getRows?roles=path,type`.

Other open ports on the unit: **2019** TIDAL Connect, **7000** AirPlay,
**8080 / 8085 / 41347** unidentified (bare 404s), **5684/udp** the Zuma CoAP channel.
Spotify Connect rides on port 80 at `/api/stream/spotify:zeroconf`.

## Tests

Offline tests cover the value codec and request building — no device, no Home Assistant:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-test.txt
.venv/bin/python -m pytest tests/test_api.py -q
```

Live tests talk to a real unit and print its responses:

```bash
ZUMA_HOST=192.168.20.158 .venv/bin/python -m pytest tests/test_live.py -v -s
```

Reads are safe. The volume round-trip moves a real speaker's volume (and restores it),
so it's gated behind an explicit opt-in:

```bash
ZUMA_HOST=… ZUMA_ALLOW_WRITE=1 .venv/bin/python -m pytest tests/test_live.py -v -s
```

There's also a standalone explorer that needs neither pytest nor Home Assistant:

```bash
python3 scripts/live_check.py 192.168.20.158              # full report
python3 scripts/live_check.py <ip> --ls settings:/        # list a container
python3 scripts/live_check.py <ip> --walk settings:/zuma  # dump a subtree
python3 scripts/live_check.py <ip> --get player:volume
python3 scripts/live_check.py <ip> --set player:volume 25
```

## Not done yet

- **Internet radio — browsing solved, starting playback is not possible over HTTP.**
  This is a structural limit of the API, established by exhaustive test rather than
  by giving up:
  - Actions are invoked as `setData(path, role="activate", value={})`. On action nodes
    the role name is ignored; a *wrong* role reports "Node at path X does not exist",
    which doubles as a handy role-existence oracle.
  - `airable:` is a URL-addressed browse tree, fully readable. `getRows` on
    `airable:https://<acct>.airable.io/airable/radios` yields Favorites, History,
    Recommendations, Local, Popular, Trending, HQ, New, Filter and Search. Stations are
    `airable:https://<acct>.airable.io/id/airable/radio/<id>`, with roles `id`, `icon`,
    `audioType`, `containerPlayable`, `mediaData` and `context`.
  - **`player:player/control` accepts exactly four verbs: `pause`, `stop`, `next`,
    `previous`.** A sweep of 24 candidate spellings (play, resume, playPause, toggle,
    start, unpause, continue, …) found no way to *start* playback. Verb validity is
    testable independent of player state: a valid verb returns `null`, while anything
    unrecognised falls through to "play the current directory" and reports
    *"Directory is empty. No playable items found."* — which is why an invalid verb
    masquerades as a playback failure.
  - Activating a station only navigates: the reply is an `NsdkActionReply` whose
    `result.path` echoes the input, and playback does not start — including while
    another station is already playing.
  - `airable:playContext:<url>` exists only while that item is playing, and it is a
    context *menu*, not a queue: type `container`, title "Actions", containing one
    row `airable:action:https://<acct>.airable.io/actions/favorites/airable/radio/<id>/insert`
    ("Add to Radio favorites", type `action`). Managing favourites therefore looks
    reachable even though starting playback is not.
  - `airable:preplay\?serviceType\=…` blocks indefinitely for every payload shape;
    it is an internal node, not HTTP-invocable.
  - Conclusion: **start playback from the app, AirPlay, Spotify Connect or TIDAL
    Connect; this integration then controls and reports it.** Seeding the play
    directory appears to be reserved to the Zuma middleware over its CoAP channel.
    The untried lead is `systemmanager:/createLogFile` — a device log taken while the
    app starts a station may name the internal call.
- **Push updates.** Polls every 10 s. The event queue endpoints above give push; worth
  switching to if volume feedback lag becomes annoying.
- **Light.** See above — needs the DTLS-PSK CoAP credentials.

Firmware this was built against: Zuma SL, `22.11.108952`, StreamSDK
`21.03-Phosphorus`. Nothing here is official or supported by Zuma; node paths could
move in any firmware update.
