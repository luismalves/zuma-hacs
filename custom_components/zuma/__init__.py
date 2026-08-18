"""The Zuma integration."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ZumaApi
from .coordinator import ZumaConfigEntry, ZumaCoordinator

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.LIGHT,
    Platform.MEDIA_PLAYER,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup_entry(hass: HomeAssistant, entry: ZumaConfigEntry) -> bool:
    """Set up Zuma from a config entry."""
    api = ZumaApi(entry.data[CONF_HOST], async_get_clientsession(hass))
    coordinator = ZumaCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()
    coordinator.identity = await api.get_identity()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Push listener: refreshes on device-side changes. Cancelled automatically when
    # the entry unloads; the periodic poll remains as a fallback if it can't run.
    entry.async_create_background_task(
        hass, coordinator.async_run_push_listener(), f"zuma-push-{api.host}"
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ZumaConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
