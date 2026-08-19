"""QLC+ integration setup and service actions."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .client import QLCPlusClient
from .const import (
    ATTR_FUNCTION,
    ATTR_STATE,
    CONF_SSL,
    DOMAIN,
    PLATFORMS,
    SERVICE_REFRESH_FUNCTIONS,
    SERVICE_SET_FUNCTION_STATE,
    SERVICE_START_FUNCTION,
    SERVICE_STOP_FUNCTION,
)
from .coordinator import QLCPlusCoordinator
from .widget_coordinator import QLCPlusWidgetCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class QLCPlusRuntime:
    """Runtime objects owned by one config entry."""

    client: QLCPlusClient
    coordinator: QLCPlusCoordinator
    widget_coordinator: QLCPlusWidgetCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up QLC+ from a config entry."""
    client = QLCPlusClient(entry.data[CONF_HOST], entry.data[CONF_PORT], entry.data[CONF_SSL])
    coordinator = QLCPlusCoordinator(hass, client, entry)
    widget_coordinator = QLCPlusWidgetCoordinator(hass, client, entry)
    try:
        await coordinator.async_config_entry_first_refresh()
        await widget_coordinator.async_config_entry_first_refresh()
    except Exception:
        await client.async_disconnect()
        raise
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = QLCPlusRuntime(client, coordinator, widget_coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    _async_register_services(hass)
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload platforms after an entity selection change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload platforms and disconnect the shared WebSocket."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        runtime: QLCPlusRuntime = hass.data[DOMAIN].pop(entry.entry_id)
        await runtime.client.async_disconnect()
    if not hass.data.get(DOMAIN):
        for service in (SERVICE_START_FUNCTION, SERVICE_STOP_FUNCTION, SERVICE_SET_FUNCTION_STATE, SERVICE_REFRESH_FUNCTIONS):
            hass.services.async_remove(DOMAIN, service)
    return unloaded


def _find_by_name(coordinator: QLCPlusCoordinator, name: str):
    """Resolve a name, rejecting ambiguous duplicate names."""
    matches = [function for function in (coordinator.data or {}).values() if function.name.casefold() == name.casefold()]
    if not matches:
        raise HomeAssistantError(f"QLC+ Function '{name}' was not found")
    if len(matches) > 1:
        raise HomeAssistantError(f"QLC+ Function name '{name}' is ambiguous; rename duplicate Functions")
    return matches[0]


def _async_register_services(hass: HomeAssistant) -> None:
    """Register domain services once; an entry_id selects a QLC+ instance."""
    if hass.services.has_service(DOMAIN, SERVICE_START_FUNCTION):
        return

    def runtime_for(call: ServiceCall) -> QLCPlusRuntime:
        entry_id = call.data.get("entry_id")
        runtimes = hass.data.get(DOMAIN, {})
        if entry_id:
            runtime = runtimes.get(entry_id)
            if runtime is None:
                raise HomeAssistantError(f"QLC+ config entry '{entry_id}' was not found")
            return runtime
        if len(runtimes) != 1:
            raise HomeAssistantError("Specify entry_id when more than one QLC+ server is configured")
        return next(iter(runtimes.values()))

    async def set_state(call: ServiceCall, state: bool | None = None) -> None:
        runtime = runtime_for(call)
        target_state = state if state is not None else call.data[ATTR_STATE]
        function = _find_by_name(runtime.coordinator, call.data[ATTR_FUNCTION])
        await runtime.coordinator.async_set_function_state(function.identity, target_state)

    async def refresh(call: ServiceCall) -> None:
        await runtime_for(call).coordinator.async_request_refresh()

    name_schema = vol.Schema({vol.Required(ATTR_FUNCTION): cv.string, vol.Optional("entry_id"): cv.string})
    hass.services.async_register(DOMAIN, SERVICE_START_FUNCTION, lambda call: set_state(call, True), schema=name_schema)
    hass.services.async_register(DOMAIN, SERVICE_STOP_FUNCTION, lambda call: set_state(call, False), schema=name_schema)
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_FUNCTION_STATE,
        set_state,
        schema=vol.Schema({vol.Required(ATTR_FUNCTION): cv.string, vol.Required(ATTR_STATE): cv.boolean, vol.Optional("entry_id"): cv.string}),
    )
    hass.services.async_register(DOMAIN, SERVICE_REFRESH_FUNCTIONS, refresh, schema=vol.Schema({vol.Optional("entry_id"): cv.string}))
