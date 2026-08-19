"""Number entities for QLC+ Virtual Console sliders."""

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .widget_coordinator import QLCPlusWidgetCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: QLCPlusWidgetCoordinator = hass.data[DOMAIN][entry.entry_id].widget_coordinator
    async_add_entities(
        QLCPlusWidgetSlider(coordinator, entry, identity)
        for identity, widget in (coordinator.data or {}).items()
        if widget.widget_type == "Slider"
    )


class QLCPlusWidgetSlider(CoordinatorEntity[QLCPlusWidgetCoordinator], NumberEntity):
    _attr_has_entity_name = True
    _attr_native_min_value = 0
    _attr_native_max_value = 255
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator: QLCPlusWidgetCoordinator, entry: ConfigEntry, identity: str) -> None:
        super().__init__(coordinator)
        self.identity = identity
        self._attr_unique_id = f"{entry.unique_id}:widget:{identity}"

    @property
    def native_value(self) -> int | None:
        widget = self.coordinator.get_widget(self.identity)
        return widget.value if widget else None

    @property
    def name(self) -> str:
        widget = self.coordinator.get_widget(self.identity)
        return f"QLC {widget.name}" if widget else f"QLC {self.identity}"

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_widget_value(self.identity, round(value))
