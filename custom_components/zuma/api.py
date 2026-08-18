"""Async client for the StreamUnlimited StreamSDK HTTP API exposed by Zuma devices.

Reverse-engineered surface (port 80, plaintext, no authentication):

    GET  /api/getData?path=<p>&roles=<comma,separated>
    GET  /api/getRows?path=<p>&roles=<r>&from=<i>&to=<i>
    POST /api/setData   {"path":..,"role":..,"value":..}
    GET  /api/event/modifyQueue?queueId=&subscribe=[..]&unsubscribe=[..]
    GET  /api/event/pollQueue?queueId=&timeout=<ms>

Two quirks drive the code below:
  * Values are tagged unions -- {"i32_": 22, "type": "i32_"} -- so reads must be
    unwrapped and writes must be re-tagged with the matching type name.
  * Application-level errors arrive as HTTP 500 with a JSON {"error": {...}} body
    rather than as a transport failure, so status codes alone are not enough.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import aiohttp

from .const import (
    CONTROL_VERBS,
    PATH_CIRCADIAN,
    PATH_CONTROL,
    PATH_DEVICE_NAME,
    PATH_LED_CURFEW,
    PATH_LIGHT,
    PATH_BEZEL,
    PATH_MANUFACTURER,
    PATH_MASTER,
    PATH_NETWORK_INFO,
    PATH_TEMP_MODE,
    PATH_MODEL,
    PATH_MUTE,
    PATH_PLAYER_DATA,
    PATH_SERIAL,
    PATH_VERSION,
    PATH_VOLUME,
    VOLUME_MAX,
)

_LOGGER = logging.getLogger(__name__)


class ZumaError(Exception):
    """The device replied, but with an application-level error."""


def unwrap(raw: Any) -> Any:
    """Turn a getData reply into a plain Python value.

    getData always answers with a list, one entry per requested role. A scalar
    leaf is tagged (``{"i32_": 22, "type": "i32_"}``); a composite node such as
    ``player:player/data`` is a plain untagged dict and is returned as-is.
    """
    if not isinstance(raw, list) or not raw:
        return None
    first = raw[0]
    if not isinstance(first, dict):
        return first
    tag = first.get("type")
    return first.get(tag) if tag else first


def wrap(value: bool | int | str) -> dict[str, Any]:
    """Tag a Python scalar the way setData expects."""
    # bool before int on purpose: bool is a subclass of int, and sending a
    # boolean as i32_ makes the device reject the write.
    if isinstance(value, bool):
        return {"bool_": value, "type": "bool_"}
    if isinstance(value, int):
        return {"i32_": value, "type": "i32_"}
    if isinstance(value, str):
        return {"string_": value, "type": "string_"}
    raise TypeError(f"no StreamSDK tag for {type(value).__name__}")


class ZumaApi:
    """Talk to one Zuma unit's StreamSDK web API."""

    def __init__(
        self, host: str, session: aiohttp.ClientSession, timeout: float = 8.0
    ) -> None:
        self._host = host
        self._session = session
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    @property
    def host(self) -> str:
        """Address this client is bound to."""
        return self._host

    async def _request(
        self,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        url = f"http://{self._host}/api/{endpoint}"
        # aiohttp rejects non-string query values, and the device wants ints as digits.
        query = {k: str(v) for k, v in (params or {}).items()}
        try:
            if body is None:
                ctx = self._session.get(url, params=query, timeout=self._timeout)
            else:
                ctx = self._session.post(url, json=body, timeout=self._timeout)
            async with ctx as resp:
                text = await resp.text()
        except aiohttp.ClientError as err:
            raise ZumaError(f"cannot reach {self._host}: {err}") from err

        if not text:
            return {}
        try:
            data = json.loads(text)
        except ValueError as err:
            raise ZumaError(f"non-JSON reply from {endpoint}: {text[:120]}") from err

        if isinstance(data, dict) and data.get("error"):
            raise ZumaError(str(data["error"].get("message", data["error"])))
        return data

    # --- primitives -------------------------------------------------------

    async def get_data(self, path: str, roles: str = "value") -> Any:
        """Raw getData, one entry per requested role."""
        return await self._request("getData", params={"path": path, "roles": roles})

    async def get_value(self, path: str) -> Any:
        """getData for the ``value`` role, unwrapped."""
        return unwrap(await self.get_data(path, "value"))

    async def set_value(self, path: str, value: bool | int | str) -> Any:
        """setData on the ``value`` role."""
        return await self._request(
            "setData", body={"path": path, "role": "value", "value": wrap(value)}
        )

    async def get_rows(
        self, path: str, roles: str = "path,type", start: int = 0, end: int = 200
    ) -> list[list[Any]]:
        """List a container node's children."""
        reply = await self._request(
            "getRows",
            params={"path": path, "roles": roles, "from": start, "to": end},
        )
        return [row for row in (reply.get("rows") or []) if row and row[0]]

    # --- conveniences -----------------------------------------------------

    async def get_volume(self) -> int | None:
        """Volume as the device counts it: 0-100."""
        return await self.get_value(PATH_VOLUME)

    async def set_volume(self, volume: int) -> None:
        """Set volume, clamped to the device's 0-100 range."""
        await self.set_value(PATH_VOLUME, max(0, min(VOLUME_MAX, int(volume))))

    async def get_mute(self) -> bool | None:
        """Current mute flag."""
        return await self.get_value(PATH_MUTE)

    async def set_mute(self, mute: bool) -> None:
        """Mute or unmute."""
        await self.set_value(PATH_MUTE, bool(mute))

    async def control(self, verb: str) -> Any:
        """Invoke a transport verb on player:player/control.

        Only pause/stop/next/previous exist. An unrecognised value shape is not
        rejected as such -- the device falls back to "play the current directory"
        and reports "Directory is empty. No playable items found.", which is why
        a bad verb looks like a playback failure.
        """
        if verb not in CONTROL_VERBS:
            raise ValueError(f"unknown control verb {verb!r}; have {CONTROL_VERBS}")
        return await self._request(
            "setData", body={"path": PATH_CONTROL, "role": "activate", "value": {"control": verb}}
        )

    async def get_player_state(self) -> str | None:
        """Transport state string: stopped / playing / paused."""
        data = await self.get_value(PATH_PLAYER_DATA)
        return data.get("state") if isinstance(data, dict) else None

    async def get_light(self) -> dict[str, Any] | None:
        """Current lamp state: {power, brightness 0-100, temperature K, ...}."""
        state = await self.get_value(PATH_LIGHT)
        return state if isinstance(state, dict) else None

    async def set_light(self, state: dict[str, Any]) -> Any:
        """Write a full zumaLightState. Caller supplies every field.

        The value is composite, not a tagged scalar, so it bypasses wrap().
        """
        return await self._request(
            "setData",
            body={
                "path": PATH_LIGHT,
                "role": "value",
                "value": {"type": "zumaLightState", "zumaLightState": state},
            },
        )

    async def get_identity(self) -> dict[str, Any]:
        """Identity for the config flow and device registry.

        ``serial`` is the same UUID the unit publishes in its mDNS TXT record,
        so a manually-added entry and a discovered one resolve to one device.
        """
        return {
            "serial": await self.get_value(PATH_SERIAL),
            "name": await self.get_value(PATH_DEVICE_NAME),
            "version": await self.get_value(PATH_VERSION),
            "model": await self.get_value(PATH_MODEL),
            "manufacturer": await self.get_value(PATH_MANUFACTURER),
        }

    async def get_state(self) -> dict[str, Any]:
        """One poll of everything the entities need.

        player:player/data is fetched once and mined for both transport state and
        now-playing metadata -- it carries the lot, whatever the source is
        (airable radio, Spotify Connect, AirPlay, TIDAL).
        """
        player = await self.get_value(PATH_PLAYER_DATA)
        if not isinstance(player, dict):
            player = {}
        track = player.get("trackRoles") or {}
        meta = (track.get("mediaData") or {}).get("metaData") or {}
        return {
            "volume": await self.get_volume(),
            "mute": await self.get_mute(),
            "state": player.get("state"),
            "title": track.get("title"),
            "image": track.get("icon"),
            "source": meta.get("serviceID"),
            # The device advertises per-stream which transport ops are valid; live
            # radio reports next_/previous false even though the verbs are accepted.
            "controls": player.get("controls") or {},
            "circadian": await self.get_value(PATH_CIRCADIAN),
            "led_curfew": await self.get_value(PATH_LED_CURFEW),
            "light": await self.get_light(),
            **await self._get_diagnostics(),
        }

    async def _get_diagnostics(self) -> dict[str, Any]:
        """Read-only diagnostics: connectivity, thermal, accessory, group role."""
        # network:info carries a type="networkInfo" tag, so get_value already
        # unwraps it to the inner object (keys: wireless, wired, gateways, ...).
        info = await self.get_value(PATH_NETWORK_INFO)
        if not isinstance(info, dict):
            info = {}
        # Prefer whichever interface is up; a Lumisonic is normally on wireless.
        wired, wifi = info.get("wired") or {}, info.get("wireless") or {}
        iface = wired if wired.get("state") == "up" else wifi
        addrs = iface.get("addresses") or []
        ip = next((a.get("ip") for a in addrs if a.get("protocol") == "ipv4"), None)
        return {
            "ip": ip,
            "ssid": wifi.get("ssid"),
            "bssid": wifi.get("bssid"),
            "rssi": wifi.get("signalLevel"),
            "frequency": wifi.get("frequency"),
            "thermal": await self.get_value(PATH_TEMP_MODE),
            "bezel": await self.get_value(PATH_BEZEL),
            "master": await self.get_value(PATH_MASTER),
        }
