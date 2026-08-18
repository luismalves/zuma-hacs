"""Polling coordinator for a single Zuma unit."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ZumaApi, ZumaError
from .const import DOMAIN, SCAN_INTERVAL_SECONDS

_LOGGER = logging.getLogger(__name__)

type ZumaConfigEntry = ConfigEntry[ZumaCoordinator]


class ZumaCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Poll volume, mute and transport state.

    ponytail: plain polling. The device also offers a long-poll event queue
    (/api/event/modifyQueue + pollQueue) for push updates -- switch to it if a
    10 s lag on volume feedback becomes annoying.
    """

    def __init__(
        self, hass: HomeAssistant, entry: ZumaConfigEntry, api: ZumaApi
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {api.host}",
            update_interval=timedelta(seconds=SCAN_INTERVAL_SECONDS),
            config_entry=entry,
        )
        self.api = api
        # Filled in once during setup; entities read it to build device_info.
        self.identity: dict[str, Any] = {}

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self.api.get_state()
        except ZumaError as err:
            raise UpdateFailed(str(err)) from err
