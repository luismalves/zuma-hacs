"""Switches for the Zuma settings that are actually writable over HTTP."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import PATH_CIRCADIAN, PATH_LED_CURFEW
from .coordinator import ZumaConfigEntry, ZumaCoordinator
from .entity import ZumaEntity


@dataclass(frozen=True, kw_only=True)
class ZumaSwitchDescription(SwitchEntityDescription):
    """A switch backed by one boolean node in the data model."""

    path: str
    data_key: str


SWITCHES: tuple[ZumaSwitchDescription, ...] = (
    ZumaSwitchDescription(
        key="circadian_lighting",
        translation_key="circadian_lighting",
        path=PATH_CIRCADIAN,
        data_key="circadian",
    ),
    ZumaSwitchDescription(
        key="led_curfew",
        translation_key="led_curfew",
        path=PATH_LED_CURFEW,
        data_key="led_curfew",
        entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZumaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Zuma switches."""
    coordinator = entry.runtime_data
    async_add_entities(ZumaSwitch(coordinator, desc) for desc in SWITCHES)


class ZumaSwitch(ZumaEntity, SwitchEntity):
    """A boolean settings node exposed as a switch."""

    entity_description: ZumaSwitchDescription

    def __init__(
        self, coordinator: ZumaCoordinator, description: ZumaSwitchDescription
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{self._serial}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        """Current value of the backing node."""
        return self.coordinator.data.get(self.entity_description.data_key)

    async def async_turn_on(self, **kwargs) -> None:
        """Set the node true."""
        await self._write(True)

    async def async_turn_off(self, **kwargs) -> None:
        """Set the node false."""
        await self._write(False)

    async def _write(self, value: bool) -> None:
        await self.coordinator.api.set_value(self.entity_description.path, value)
        await self.coordinator.async_request_refresh()
