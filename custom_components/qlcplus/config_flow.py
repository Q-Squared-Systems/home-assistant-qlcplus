"""Config and options flows for QLC+."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .client import QLCPlusClient, QLCPlusError
from .const import CONF_EXPOSED_FUNCTIONS, CONF_EXPOSED_TYPES, CONF_NAME_PREFIX, CONF_SSL, DEFAULT_PORT, DOMAIN

_LOGGER = logging.getLogger(__name__)


class QLCPlusConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle configuration through the Home Assistant UI."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = user_input[CONF_PORT]
            await self.async_set_unique_id(f"{host.casefold()}:{port}")
            self._abort_if_unique_id_configured()
            client = QLCPlusClient(host, port, user_input[CONF_SSL])
            try:
                await client.async_get_functions()
            except QLCPlusError as err:
                _LOGGER.error("Unable to verify QLC+ WebSocket connection to %s:%s: %s", host, port, err)
                errors["base"] = "cannot_connect"
            finally:
                await client.async_disconnect()
            if not errors:
                return self.async_create_entry(title=f"QLC+ ({host})", data={**user_input, CONF_HOST: host})
        schema = vol.Schema(
            {
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_PORT, default=DEFAULT_PORT): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1, max=65535, mode=selector.NumberSelectorMode.BOX)
                ),
                vol.Required(CONF_SSL, default=False): selector.BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> QLCPlusOptionsFlow:
        return QLCPlusOptionsFlow()


class QLCPlusOptionsFlow(config_entries.OptionsFlow):
    """Choose the Functions made visible as entities."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        runtime = self.hass.data[DOMAIN][self.config_entry.entry_id]
        functions = list((runtime.coordinator.data or {}).values())
        function_options = [selector.SelectOptionDict(value=f.identity, label=f.selector_key) for f in functions]
        types = sorted({f.function_type for f in functions})
        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Optional(CONF_EXPOSED_FUNCTIONS, default=options.get(CONF_EXPOSED_FUNCTIONS, [])): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=function_options, multiple=True)
                ),
                vol.Optional(CONF_EXPOSED_TYPES, default=options.get(CONF_EXPOSED_TYPES, [])): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=types, multiple=True)
                ),
                vol.Optional(CONF_NAME_PREFIX, default=options.get(CONF_NAME_PREFIX, "")): str,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
