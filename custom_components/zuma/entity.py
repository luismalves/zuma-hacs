"""Shared base entity for Zuma."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ZumaCoordinator


class ZumaEntity(CoordinatorEntity[ZumaCoordinator]):
    """Common device registry wiring."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: ZumaCoordinator) -> None:
        super().__init__(coordinator)
        identity = coordinator.identity
        # Fall back to the host so a unit that hides its serial still gets a
        # stable-enough id rather than colliding with every other Zuma.
        self._serial = identity.get("serial") or coordinator.api.host
        # Prefix the device name with the brand so entity_ids come out as
        # zuma_<room>_<feature> (has_entity_name derives the id from this name),
        # and the device reads e.g. "Zuma Bathroom" rather than a bare "Bathroom".
        room = identity.get("name")
        device_name = f"Zuma {room}" if room else "Zuma"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._serial)},
            name=device_name,
            manufacturer=identity.get("manufacturer") or "Zuma Array Limited",
            model=identity.get("model"),
            sw_version=identity.get("version"),
            configuration_url=f"http://{coordinator.api.host}/",
        )
