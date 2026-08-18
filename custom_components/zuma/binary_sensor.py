"""Read-only diagnostic binary sensors for a Zuma unit."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import ZumaConfigEntry, ZumaCoordinator
from .entity import ZumaEntity


@dataclass(frozen=True, kw_only=True)
class ZumaBinaryDescription(BinarySensorEntityDescription):
    """A binary sensor backed by a coordinator-data key."""

    data_key: str


BINARY_SENSORS: tuple[ZumaBinaryDescription, ...] = (
    ZumaBinaryDescription(
        key="smart_bezel",
        translation_key="smart_bezel",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        data_key="bezel",
    ),
    ZumaBinaryDescription(
        key="area_master",
        translation_key="area_master",
        entity_category=EntityCategory.DIAGNOSTIC,
        data_key="master",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZumaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Zuma diagnostic binary sensors."""
    coordinator = entry.runtime_data
    async_add_entities(ZumaBinarySensor(coordinator, d) for d in BINARY_SENSORS)


class ZumaBinarySensor(ZumaEntity, BinarySensorEntity):
    """A boolean diagnostic value."""

    entity_description: ZumaBinaryDescription

    def __init__(
        self, coordinator: ZumaCoordinator, description: ZumaBinaryDescription
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{self._serial}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        """Current boolean value."""
        return self.coordinator.data.get(self.entity_description.data_key)
