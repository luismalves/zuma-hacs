"""Offline tests for the value codec and request building. No device needed."""

from __future__ import annotations

import pytest


def test_unwrap_tagged_scalars(zuma_api):
    """A tagged leaf yields the bare Python value."""
    assert zuma_api.unwrap([{"i32_": 22, "type": "i32_"}]) == 22
    assert zuma_api.unwrap([{"bool_": False, "type": "bool_"}]) is False
    assert zuma_api.unwrap([{"string_": "Bathroom", "type": "string_"}]) == "Bathroom"


def test_unwrap_untagged_composite(zuma_api):
    """player:player/data comes back untagged and must survive intact."""
    raw = [{"state": "stopped", "keepActive": False, "error": ""}]
    assert zuma_api.unwrap(raw) == raw[0]


def test_unwrap_handles_empty_and_garbage(zuma_api):
    assert zuma_api.unwrap([]) is None
    assert zuma_api.unwrap([None]) is None
    assert zuma_api.unwrap({"not": "a list"}) is None


def test_wrap_tags_bool_before_int(zuma_api):
    """bool subclasses int; tagging True as i32_ makes the device reject the write."""
    assert zuma_api.wrap(True) == {"bool_": True, "type": "bool_"}
    assert zuma_api.wrap(1) == {"i32_": 1, "type": "i32_"}
    assert zuma_api.wrap("x") == {"string_": "x", "type": "string_"}
    with pytest.raises(TypeError):
        zuma_api.wrap(1.5)


def test_roundtrip_wrap_unwrap(zuma_api):
    for value in (0, 22, 100, True, False, "Bathroom"):
        assert zuma_api.unwrap([zuma_api.wrap(value)]) == value


async def test_set_volume_clamps_to_device_range(zuma_api, fake_session):
    """Out-of-range volumes are clamped, not sent through and rejected."""
    session = fake_session()
    api = zuma_api.ZumaApi("host.invalid", session)

    await api.set_volume(150)
    await api.set_volume(-10)
    await api.set_volume(35)

    sent = [call[2]["value"]["i32_"] for call in session.calls]
    assert sent == [100, 0, 35]


async def test_get_volume_unwraps(zuma_api, fake_session):
    api = zuma_api.ZumaApi("host.invalid", fake_session('[{"i32_": 22, "type": "i32_"}]'))
    assert await api.get_volume() == 22


async def test_application_error_raises(zuma_api, fake_session):
    """A 500-with-JSON-body error must surface as ZumaError, not pass silently."""
    session = fake_session('{"error": {"name": "x", "message": "Node does not exist"}}')
    api = zuma_api.ZumaApi("host.invalid", session)
    with pytest.raises(zuma_api.ZumaError, match="Node does not exist"):
        await api.get_volume()


async def test_query_values_are_stringified(zuma_api, fake_session):
    """aiohttp rejects int query values, so getRows must stringify from/to."""
    session = fake_session('{"rows": []}')
    api = zuma_api.ZumaApi("host.invalid", session)
    await api.get_rows("settings:/", start=0, end=45)
    _, _, params = session.calls[0]
    assert params == {
        "path": "settings:/",
        "roles": "path,type",
        "from": "0",
        "to": "45",
    }


async def test_control_sends_expected_payload(zuma_api, fake_session):
    """Transport verbs go out as {"control": verb} on the activate role."""
    session = fake_session("null")
    api = zuma_api.ZumaApi("host.invalid", session)
    await api.control("pause")
    _, url, body = session.calls[0]
    assert url.endswith("/api/setData")
    assert body == {
        "path": "player:player/control",
        "role": "activate",
        "value": {"control": "pause"},
    }


async def test_control_rejects_unknown_verb(zuma_api, fake_session):
    """play/resume do not exist on this device; fail loudly instead of silently."""
    api = zuma_api.ZumaApi("host.invalid", fake_session("null"))
    with pytest.raises(ValueError, match="unknown control verb"):
        await api.control("play")


async def test_set_light_wraps_composite_value(zuma_api, fake_session):
    """Light state is a composite tagged value, not a scalar."""
    session = fake_session("null")
    api = zuma_api.ZumaApi("host.invalid", session)
    await api.set_light(
        {"power": True, "brightness": 40, "temperature": 3000,
         "lastTransitionPeriod": "ms500"}
    )
    _, url, body = session.calls[0]
    assert url.endswith("/api/setData")
    assert body["path"] == "zuma:lightState"
    assert body["value"]["type"] == "zumaLightState"
    assert body["value"]["zumaLightState"]["brightness"] == 40


async def test_get_light_unwraps_state(zuma_api, fake_session):
    reply = '[{"type":"zumaLightState","zumaLightState":{"power":true,"brightness":17,"temperature":3869}}]'
    api = zuma_api.ZumaApi("host.invalid", fake_session(reply))
    light = await api.get_light()
    assert light == {"power": True, "brightness": 17, "temperature": 3869}
