"""Connectivity sensor for QLC+."""

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import QLCPlusCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up the QLC+ connection-status sensor."""
    coordinator: QLCPlusCoordinator = hass.data[DOMAIN][entry.entry_id].coordinator
    async_add_entities([QLCPlusOnlineSensor(coordinator, entry)])


class QLCPlusOnlineSensor(CoordinatorEntity[QLCPlusCoordinator], BinarySensorEntity):
    """Report whether QLC+ is reachable through its WebSocket API."""

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_name = "QLC Online"

    def __init__(self, coordinator: QLCPlusCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.unique_id}:online"

    @property
    def is_on(self) -> bool:
        return self.coordinator.last_update_success and self.coordinator.client.connected
