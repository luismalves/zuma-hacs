"""Config flow for Zuma, with mDNS discovery."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .api import ZumaApi, ZumaError
from .const import DOMAIN


class ZumaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Zuma."""

    VERSION = 1

    def __init__(self) -> None:
        self._host: str | None = None
        self._name: str | None = None

    async def _probe(self, host: str) -> dict[str, Any]:
        """Read identity from a candidate host; raises ZumaError if unreachable."""
        api = ZumaApi(host, async_get_clientsession(self.hass))
        return await api.get_identity()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manual host entry."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST]
            try:
                identity = await self._probe(host)
            except ZumaError:
                errors["base"] = "cannot_connect"
            else:
                if not identity.get("serial"):
                    errors["base"] = "not_zuma"
                else:
                    await self.async_set_unique_id(identity["serial"])
                    self._abort_if_unique_id_configured(updates={CONF_HOST: host})
                    return self.async_create_entry(
                        title=identity.get("name") or host, data={CONF_HOST: host}
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_HOST): str}),
            errors=errors,
        )

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """Handle a unit found via _sues800device._tcp.

        Its TXT record carries serial, name and ip, so no probe is needed to
        deduplicate -- only to confirm before creating the entry.
        """
        serial = discovery_info.properties.get("serial")
        if not serial:
            return self.async_abort(reason="not_zuma")

        await self.async_set_unique_id(serial)
        self._abort_if_unique_id_configured(updates={CONF_HOST: discovery_info.host})

        self._host = discovery_info.host
        self._name = discovery_info.properties.get("name") or discovery_info.host
        self.context["title_placeholders"] = {"name": self._name}
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm a discovered unit."""
        assert self._host is not None
        if user_input is not None:
            try:
                await self._probe(self._host)
            except ZumaError:
                return self.async_abort(reason="cannot_connect")
            return self.async_create_entry(
                title=self._name or self._host, data={CONF_HOST: self._host}
            )

        self._set_confirm_only()
        return self.async_show_form(
            step_id="confirm",
            description_placeholders={"name": self._name or self._host},
        )
