"""Coordinated discovery and state refresh for QLC+."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
import logging
from time import monotonic

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import QLCPlusClient, QLCPlusError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN
from .models import QLCFunction
from .const import CONF_EXPOSED_FUNCTIONS, CONF_EXPOSED_TYPES, CONF_NAME_PREFIX

_LOGGER = logging.getLogger(__name__)
_COMMAND_STATE_GRACE_SECONDS = 5


class QLCPlusCoordinator(DataUpdateCoordinator[dict[str, QLCFunction]]):
    """Maintain the current ID mapping and states for one QLC+ server."""

    def __init__(self, hass: HomeAssistant, client: QLCPlusClient, config_entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
            always_update=False,
            config_entry=config_entry,
        )
        self.client = client
        self.last_successful_communication: datetime | None = None
        self._discovery_listeners: list[Callable[[], None]] = []
        self._state_generation = 0
        self._command_lock = asyncio.Lock()
        self._command_complete = asyncio.Event()
        self._command_complete.set()
        self._pending_states: dict[str, tuple[bool, float]] = {}

    def _is_exposed(self, function: QLCFunction) -> bool:
        """Return whether this Function has a corresponding HA switch."""
        options = self.config_entry.options
        selected = set(options.get(CONF_EXPOSED_FUNCTIONS, []))
        types = set(options.get(CONF_EXPOSED_TYPES, []))
        prefix = options.get(CONF_NAME_PREFIX, "").strip().casefold()
        if not selected and not types and not prefix:
            return True
        return (
            function.identity in selected
            or function.function_type in types
            or (bool(prefix) and function.name.casefold().startswith(prefix))
        )

    async def _async_update_data(self) -> dict[str, QLCFunction]:
        """Read a full QLC+ snapshot without overwriting a newer command state."""
        await self._command_complete.wait()
        generation = self._state_generation
        try:
            functions = await self.client.async_get_functions(self._is_exposed)
        except QLCPlusError as err:
            raise UpdateFailed(str(err)) from err
        self.last_successful_communication = datetime.now().astimezone()
        if generation != self._state_generation:
            # A Function command was issued after this scan began. Its direct
            # state update is newer than this complete-but-stale scan.
            _LOGGER.debug("Discarding stale QLC+ Function scan after a command")
            return self.data or {}
        data = {function.identity: function for function in functions}
        now = monotonic()
        for identity, (expected_state, expires_at) in tuple(self._pending_states.items()):
            function = data.get(identity)
            if function is None or function.running == expected_state or now >= expires_at:
                self._pending_states.pop(identity, None)
            else:
                # QLC+ can activate a Function before getFunctionStatus reports
                # the new state. Preserve the just-issued command briefly.
                data[identity] = replace(function, running=expected_state)
        return data

    def async_set_updated_data(self, data: dict[str, QLCFunction]) -> None:
        """Publish data before asking platforms to create newly discovered entities."""
        previous_identities = set(self.data or {})
        super().async_set_updated_data(data)
        if previous_identities != set(data):
            for listener in tuple(self._discovery_listeners):
                listener()

    def async_add_discovery_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Subscribe to added/removed Functions."""
        self._discovery_listeners.append(listener)
        return lambda: self._discovery_listeners.remove(listener)

    def get_function(self, identity: str) -> QLCFunction | None:
        return (self.data or {}).get(identity)

    async def async_set_function_state(self, identity: str, state: bool) -> None:
        """Command one Function and immediately update its Home Assistant state."""
        async with self._command_lock:
            function = self.get_function(identity)
            if function is None:
                raise ValueError("Function no longer exists in the QLC+ project")

            # Full scans query hundreds of Functions over time. Mark any scan
            # already running as stale and keep new scans out until the command
            # has been sent and this Function's state has been read back.
            self._command_complete.clear()
            self._state_generation += 1
            try:
                await self.client.async_set_function_status(function.function_id, state)
                data = dict(self.data or {})
                data[identity] = replace(function, running=state)
                self._pending_states[identity] = (state, monotonic() + _COMMAND_STATE_GRACE_SECONDS)
                self.last_successful_communication = datetime.now().astimezone()
                self.async_set_updated_data(data)
            finally:
                self._command_complete.set()
