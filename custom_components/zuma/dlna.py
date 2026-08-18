"""Play an arbitrary stream URL on the Zuma's built-in DLNA renderer.

The nsdk HTTP API cannot *start* playback of a URL (it only has pause/stop/skip),
but the same box also runs a Rygel MediaRenderer with AVTransport, which can. So
media_player.play_media bridges to it: discover the AVTransport control URL via a
unicast SSDP M-SEARCH (the renderer binds an ephemeral high port that moves across
reboots, so it must be discovered, not hardcoded), then SetAVTransportURI + Play.

Only stream URLs whose server returns an accepted MIME play: the renderer probes the
URL itself and rejects anything outside its sink list -- notably ICY `audio/aacp`
(what streamtheworld's .aac mounts serve). MP3 (`audio/mpeg`) and clean AAC work.
"""

from __future__ import annotations

import asyncio
import socket
from urllib.parse import urljoin
from xml.sax.saxutils import escape
from xml.etree import ElementTree as ET

import aiohttp

_DEVNS = "urn:schemas-upnp-org:device-1-0"
_AVT = "urn:schemas-upnp-org:service:AVTransport:2"
_RENDERER_ST = "urn:schemas-upnp-org:device:MediaRenderer:1"

# Audio MIME types the Zuma renderer advertises via ConnectionManager GetProtocolInfo.
_MIME_OK = {"audio/mpeg", "audio/aac", "audio/x-aac", "audio/mp4", "audio/vnd.dlna.adts"}


def _msearch(host: str) -> str | None:
    """Blocking unicast SSDP M-SEARCH; return the device description URL or None."""
    msg = (
        "M-SEARCH * HTTP/1.1\r\n"
        f"HOST:{host}:1900\r\n"
        'MAN:"ssdp:discover"\r\n'
        f"ST:{_RENDERER_ST}\r\n"
        "MX:2\r\n\r\n"
    ).encode()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(3)
    try:
        sock.sendto(msg, (host, 1900))
        for _ in range(4):
            data = sock.recvfrom(2048)[0]
            for line in data.decode(errors="replace").splitlines():
                if line.lower().startswith("location:"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        return None
    finally:
        sock.close()
    return None


async def discover_avtransport(host: str, session: aiohttp.ClientSession) -> str | None:
    """Return the absolute AVTransport controlURL for the device, or None."""
    loop = asyncio.get_running_loop()
    location = await loop.run_in_executor(None, _msearch, host)
    if not location:
        return None
    async with session.get(location, timeout=aiohttp.ClientTimeout(total=6)) as resp:
        root = ET.fromstring(await resp.text())
    for svc in root.iter(f"{{{_DEVNS}}}service"):
        if "AVTransport" in (svc.findtext(f"{{{_DEVNS}}}serviceType") or ""):
            ctrl = svc.findtext(f"{{{_DEVNS}}}controlURL") or ""
            return urljoin(location, ctrl)
    return None


async def probe_mime(url: str, session: aiohttp.ClientSession) -> str:
    """Best-effort content type for the DIDL protocolInfo, following redirects."""
    try:
        async with session.get(
            url,
            headers={"Range": "bytes=0-1"},
            allow_redirects=True,
            timeout=aiohttp.ClientTimeout(total=6),
        ) as resp:
            ct = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    except aiohttp.ClientError:
        ct = ""
    return normalize_mime(ct)


def normalize_mime(ct: str) -> str:
    """Map a probed content type to an accepted sink MIME; default to MP3."""
    ct = (ct or "").split(";")[0].strip().lower()
    if ct in _MIME_OK:
        return ct
    if "mpeg" in ct or "mp3" in ct:
        return "audio/mpeg"
    if "aac" in ct:  # audio/aacp and friends map to the accepted audio/aac
        return "audio/aac"
    return "audio/mpeg"


def _didl(url: str, title: str, mime: str) -> str:
    inner = (
        '<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/">'
        '<item id="0" parentID="-1" restricted="1">'
        f"<dc:title>{escape(title)}</dc:title>"
        "<upnp:class>object.item.audioItem.audioBroadcast</upnp:class>"
        f'<res protocolInfo="http-get:*:{mime}:*">{escape(url)}</res>'
        "</item></DIDL-Lite>"
    )
    return escape(inner)


async def _soap(
    session: aiohttp.ClientSession, control_url: str, action: str, body: str
) -> None:
    envelope = (
        '<?xml version="1.0"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
        f'<u:{action} xmlns:u="{_AVT}">{body}</u:{action}>'
        "</s:Body></s:Envelope>"
    )
    async with session.post(
        control_url,
        data=envelope.encode(),
        headers={
            "Content-Type": 'text/xml; charset="utf-8"',
            "SOAPAction": f'"{_AVT}#{action}"',
        },
        timeout=aiohttp.ClientTimeout(total=10),
    ) as resp:
        text = await resp.text()
        if resp.status >= 400:
            raise aiohttp.ClientError(f"{action} failed: {text[:200]}")


async def play_url(
    session: aiohttp.ClientSession,
    control_url: str,
    url: str,
    title: str,
    mime: str,
) -> None:
    """SetAVTransportURI + Play on the renderer."""
    await _soap(
        session,
        control_url,
        "SetAVTransportURI",
        f"<InstanceID>0</InstanceID><CurrentURI>{escape(url)}</CurrentURI>"
        f"<CurrentURIMetaData>{_didl(url, title, mime)}</CurrentURIMetaData>",
    )
    await _soap(
        session, control_url, "Play", "<InstanceID>0</InstanceID><Speed>1</Speed>"
    )
