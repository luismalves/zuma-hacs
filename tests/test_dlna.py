"""Offline tests for the DLNA helper's pure logic."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest

COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "zuma"


@pytest.fixture(scope="module")
def dlna():
    spec = importlib.util.spec_from_file_location("zuma_dlna", COMPONENT / "dlna.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["zuma_dlna"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_normalize_mime_accepts_known(dlna):
    assert dlna.normalize_mime("audio/mpeg") == "audio/mpeg"
    assert dlna.normalize_mime("audio/mp4") == "audio/mp4"


def test_normalize_mime_maps_icy_aac_to_accepted(dlna):
    # streamtheworld .aac mounts serve audio/aacp, which the device rejects;
    # map it to the accepted audio/aac family rather than passing it through.
    assert dlna.normalize_mime("audio/aacp") == "audio/aac"
    assert dlna.normalize_mime("AUDIO/AACP; charset=x") == "audio/aac"


def test_normalize_mime_defaults_to_mp3(dlna):
    assert dlna.normalize_mime("") == "audio/mpeg"
    assert dlna.normalize_mime("application/octet-stream") == "audio/mpeg"


def test_didl_escapes_and_carries_url_and_mime(dlna):
    didl = dlna._didl("http://h/s.mp3?a=1&b=2", "R & R", "audio/mpeg")
    # The whole blob is XML-escaped for embedding in the SOAP body.
    assert "&lt;DIDL-Lite" in didl
    assert "audio/mpeg" in didl
    assert "R &amp;amp; R" in didl  # title ampersand double-escaped (DIDL then SOAP)
