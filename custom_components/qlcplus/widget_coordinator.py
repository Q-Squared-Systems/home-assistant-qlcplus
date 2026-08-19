"""Virtual Console widget discovery and push-state coordination."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import QLCPlusClient, QLCPlusError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN
from .models import QLCWidget

_LOGGER = logging.getLogger(__name__)


class QLCPlusWidgetCoordinator(DataUpdateCoordinator[dict[str, QLCWidget]]):
    """Keep all compatible Virtual Console widgets available to Home Assistant."""

    def __init__(self, hass: HomeAssistant, client: QLCPlusClient, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, name=f"{DOMAIN}_widgets", update_interval=DEFAULT_SCAN_INTERVAL, config_entry=entry)
        self.client = client
        self.client.set_widget_event_handler(self._async_handle_widget_event)
        self.last_successful_communication: datetime | None = None

    async def _async_update_data(self) -> dict[str, QLCWidget]:
        try:
            widgets = await self.client.async_get_widgets()
        except QLCPlusError as err:
            raise UpdateFailed(str(err)) from err
        self.last_successful_communication = datetime.now().astimezone()
        return {widget.identity: widget for widget in widgets}

    async def _async_handle_widget_event(self, widget_id: int, widget_type: str, value: int) -> None:
        data = dict(self.data or {})
        for identity, widget in data.items():
            if widget.widget_id == widget_id:
                data[identity] = replace(widget, value=value)
                self.last_successful_communication = datetime.now().astimezone()
                self.async_set_updated_data(data)
                return

    def get_widget(self, identity: str) -> QLCWidget | None:
        return (self.data or {}).get(identity)

    async def async_set_widget_value(self, identity: str, value: int) -> None:
        widget = self.get_widget(identity)
        if widget is None:
            raise ValueError("Virtual Console widget no longer exists")
        await self.client.async_set_widget_value(widget.widget_id, value)
        data = dict(self.data or {})
        data[identity] = replace(widget, value=value)
        self.async_set_updated_data(data)

    async def async_set_widget_switch_state(self, identity: str, state: bool) -> None:
        """Set a VC Toggle button by pressing it only when a toggle is needed."""
        widget = self.get_widget(identity)
        if widget is None:
            raise ValueError("Virtual Console widget no longer exists")
        current_value = await self.client.async_get_widget_value(widget.widget_id)
        is_on = current_value > 0
        if is_on == state:
            return
        # QLC+ Button value 0 is a release, not an off command. Toggle buttons
        # change state on a press (255), in either direction.
        await self.client.async_set_widget_value(widget.widget_id, 255)
