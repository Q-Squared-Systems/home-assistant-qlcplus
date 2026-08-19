"""Coordinated discovery and state refresh for QLC+."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
import logging

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import QLCPlusClient, QLCPlusError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN
from .models import QLCFunction

_LOGGER = logging.getLogger(__name__)


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

    async def _async_update_data(self) -> dict[str, QLCFunction]:
        try:
            functions = await self.client.async_get_functions()
        except QLCPlusError as err:
            raise UpdateFailed(str(err)) from err
        self.last_successful_communication = datetime.now().astimezone()
        return {function.identity: function for function in functions}

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
        """Resolve the latest numeric ID, command it, then confirm via refresh."""
        function = self.get_function(identity)
        if function is None:
            raise ValueError("Function no longer exists in the QLC+ project")
        await self.client.async_set_function_status(function.function_id, state)
        # The command has no response in QLC+ 4, so read back authoritative state.
        await self.async_request_refresh()
