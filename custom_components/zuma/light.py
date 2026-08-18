"""The Zuma lamp: tunable-white brightness + colour temperature over HTTP."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_TRANSITION,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import LIGHT_MAX_KELVIN, LIGHT_MIN_KELVIN, LIGHT_TRANSITIONS
from .coordinator import ZumaConfigEntry, ZumaCoordinator
from .entity import ZumaEntity


def _nearest_transition(seconds: float | None) -> str:
    """Map HA's transition (seconds) to the device's fixed millisecond buckets."""
    if seconds is None:
        return "ms500"
    ms = seconds * 1000
    return LIGHT_TRANSITIONS[min(LIGHT_TRANSITIONS, key=lambda b: abs(b - ms))]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZumaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Zuma light."""
    async_add_entities([ZumaLight(entry.runtime_data)])


class ZumaLight(ZumaEntity, LightEntity):
    """Brightness + colour temperature for one Zuma unit.

    power and brightness are independent on the device (brightness 0 leaves the lamp
    powered), so on/off toggles the `power` field and leaves brightness untouched --
    that way the lamp comes back at the level it had.
    """

    _attr_name = None
    _attr_color_mode = ColorMode.COLOR_TEMP
    _attr_supported_color_modes = {ColorMode.COLOR_TEMP}
    _attr_supported_features = LightEntityFeature.TRANSITION
    _attr_min_color_temp_kelvin = LIGHT_MIN_KELVIN
    _attr_max_color_temp_kelvin = LIGHT_MAX_KELVIN

    def __init__(self, coordinator: ZumaCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{self._serial}_light"

    @property
    def _light(self) -> dict[str, Any]:
        return self.coordinator.data.get("light") or {}

    @property
    def available(self) -> bool:
        """Only present the light if the device actually reported its state."""
        return super().available and bool(self._light)

    @property
    def is_on(self) -> bool | None:
        """Power flag, independent of brightness."""
        return self._light.get("power")

    @property
    def brightness(self) -> int | None:
        """Device 0-100 mapped to HA's 0-255."""
        pct = self._light.get("brightness")
        return None if pct is None else round(pct * 255 / 100)

    @property
    def color_temp_kelvin(self) -> int | None:
        """Colour temperature in Kelvin, as the device stores it."""
        return self._light.get("temperature")

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Power on, applying any brightness / colour-temp / transition given."""
        state = dict(self._light)
        state["power"] = True
        if ATTR_BRIGHTNESS in kwargs:
            state["brightness"] = round(kwargs[ATTR_BRIGHTNESS] * 100 / 255)
        if ATTR_COLOR_TEMP_KELVIN in kwargs:
            # Clamp to the advertised range; the device tolerates more but renders poorly.
            state["temperature"] = max(
                LIGHT_MIN_KELVIN, min(LIGHT_MAX_KELVIN, kwargs[ATTR_COLOR_TEMP_KELVIN])
            )
        state["lastTransitionPeriod"] = _nearest_transition(kwargs.get(ATTR_TRANSITION))
        await self._write(state)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Power off, keeping brightness so it restores on next turn-on."""
        state = dict(self._light)
        state["power"] = False
        state["lastTransitionPeriod"] = _nearest_transition(kwargs.get(ATTR_TRANSITION))
        await self._write(state)

    async def _write(self, state: dict[str, Any]) -> None:
        # Send only the four fields the device expects; drop anything stray we read.
        payload = {
            "power": state.get("power", True),
            "brightness": state.get("brightness", 100),
            "temperature": state.get("temperature", 4600),
            "lastTransitionPeriod": state.get("lastTransitionPeriod", "ms500"),
        }
        await self.coordinator.api.set_light(payload)
        await self.coordinator.async_request_refresh()
