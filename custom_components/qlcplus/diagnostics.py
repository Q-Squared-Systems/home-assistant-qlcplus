"""Diagnostics for QLC+; no credentials are used or exposed."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_HOST, CONF_PORT, DOMAIN


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    """Return non-sensitive connection and discovery information."""
    runtime = hass.data[DOMAIN][entry.entry_id]
    coordinator = runtime.coordinator
    functions = list((coordinator.data or {}).values())
    return {
        "host": entry.data[CONF_HOST],
        "port": entry.data[CONF_PORT],
        "connected": runtime.client.connected,
        "last_successful_communication": coordinator.last_successful_communication,
        "last_error": runtime.client.last_error,
        "function_count": len(functions),
        "functions": [{"name": f.name, "type": f.function_type, "identity": f.identity, "running": f.running} for f in functions],
    }
