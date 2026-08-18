"""Coordinator for a single Zuma unit: push via the event queue, polling as fallback."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ZumaApi, ZumaError
from .const import DOMAIN, PUSH_PATHS, SCAN_INTERVAL_SECONDS

_LOGGER = logging.getLogger(__name__)

type ZumaConfigEntry = ConfigEntry[ZumaCoordinator]

# After a push error (queue lost, device rebooting), wait this long before rebuilding.
_PUSH_RETRY_SECONDS = 5.0


class ZumaCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Refresh device state, driven by the device's own change events.

    The device exposes a long-poll event queue: subscribe to the fast-changing
    leaf nodes, then a poll blocks until one of them changes and names the path.
    On any event we do a full refresh, so a volume/light change made from the app
    or the unit shows up in HA in ~2 s instead of waiting for the periodic poll.
    Polling stays on as a slow safety net (and to catch the rare-change
    diagnostics the push set does not subscribe to).
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
        # Cached DLNA AVTransport control URL (ephemeral port; re-discovered on failure).
        self.avtransport_url: str | None = None

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self.api.get_state()
        except ZumaError as err:
            raise UpdateFailed(str(err)) from err

    async def async_run_push_listener(self) -> None:
        """Long-poll the event queue forever, refreshing on each change.

        Runs as a background task for the life of the config entry. Resilient by
        design: a client-timeout is a normal heartbeat (re-poll, keep the queue);
        any real error drops the queue id and rebuilds it after a short wait.
        """
        queue_id: str | None = None
        while True:
            try:
                if queue_id is None:
                    queue_id = await self.api.create_event_queue(list(PUSH_PATHS))
                    _LOGGER.debug("%s: event queue %s", self.name, queue_id)
                changed = await self.api.poll_events(queue_id)
                if changed:
                    _LOGGER.debug("%s: push %s", self.name, changed)
                    await self.async_request_refresh()
            except asyncio.CancelledError:
                raise
            except TimeoutError:
                # No change within the poll window -- expected; just poll again.
                continue
            except Exception as err:  # noqa: BLE001 -- keep the loop alive on any fault
                _LOGGER.debug("%s: push reset (%s)", self.name, err)
                queue_id = None
                await asyncio.sleep(_PUSH_RETRY_SECONDS)
