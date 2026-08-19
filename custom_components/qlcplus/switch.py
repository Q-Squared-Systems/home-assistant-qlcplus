"""Switch entities for QLC+ Functions."""

from __future__ import annotations

from collections.abc import Callable
import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_EXPOSED_FUNCTIONS, CONF_EXPOSED_TYPES, CONF_NAME_PREFIX, DOMAIN
from .coordinator import QLCPlusCoordinator
from .models import QLCFunction

_LOGGER = logging.getLogger(__name__)


def _is_exposed(entry: ConfigEntry, function: QLCFunction) -> bool:
    """Apply optional individual/type/prefix filters; empty settings expose all."""
    options = entry.options
    selected = set(options.get(CONF_EXPOSED_FUNCTIONS, []))
    types = set(options.get(CONF_EXPOSED_TYPES, []))
    prefix = options.get(CONF_NAME_PREFIX, "").strip().casefold()
    if not selected and not types and not prefix:
        return True
    return function.identity in selected or function.function_type in types or (bool(prefix) and function.name.casefold().startswith(prefix))


def _has_active_filter(entry: ConfigEntry) -> bool:
    """Return whether entity selection has been explicitly restricted."""
    options = entry.options
    return bool(
        options.get(CONF_EXPOSED_FUNCTIONS)
        or options.get(CONF_EXPOSED_TYPES)
        or options.get(CONF_NAME_PREFIX, "").strip()
    )


async def _async_cleanup_filtered_entities(
    hass: HomeAssistant, entry: ConfigEntry, exposed_identities: set[str]
) -> None:
    """Remove previously-created Function switches excluded by active filters.

    This intentionally runs only after the user enables a filter. Leaving all
    filters empty means "expose everything" and never removes registry entries.
    """
    if not _has_active_filter(entry):
        return
    registry = er.async_get(hass)
    prefix = f"{entry.unique_id}:"
    removed = 0
    for registry_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if not registry_entry.entity_id.startswith("switch.") or not registry_entry.unique_id.startswith(prefix):
            continue
        identity = registry_entry.unique_id.removeprefix(prefix)
        if identity in exposed_identities:
            continue
        registry.async_remove(registry_entry.entity_id)
        removed += 1
    if removed:
        _LOGGER.info("Removed %d QLC+ switch entities excluded by updated filters", removed)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up Function switches and dynamically add newly discovered Functions."""
    coordinator: QLCPlusCoordinator = hass.data[DOMAIN][entry.entry_id].coordinator
    added: set[str] = set()

    functions = coordinator.data or {}
    exposed_identities = {identity for identity, function in functions.items() if _is_exposed(entry, function)}
    await _async_cleanup_filtered_entities(hass, entry, exposed_identities)
    if exposed_identities:
        _LOGGER.info("Setting up %d QLC+ Function switch entities", len(exposed_identities))
    else:
        _LOGGER.warning("No QLC+ Functions match the configured entity filters")

    def add_new() -> None:
        functions = coordinator.data or {}
        entities = [QLCPlusFunctionSwitch(coordinator, entry, identity) for identity, function in functions.items() if identity not in added and _is_exposed(entry, function)]
        added.update(entity.identity for entity in entities)
        if entities:
            _LOGGER.debug("Adding %d newly discovered QLC+ Function switches", len(entities))
            async_add_entities(entities)

    add_new()
    entry.async_on_unload(coordinator.async_add_discovery_listener(add_new))


class QLCPlusFunctionSwitch(CoordinatorEntity[QLCPlusCoordinator], SwitchEntity):
    """Represent a durable QLC+ Function identity as a switch."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: QLCPlusCoordinator, entry: ConfigEntry, identity: str) -> None:
        super().__init__(coordinator)
        self.identity = identity
        self._entry = entry
        self._attr_unique_id = f"{entry.unique_id}:{identity}"

    @property
    def function(self) -> QLCFunction | None:
        return self.coordinator.get_function(self.identity)

    @property
    def available(self) -> bool:
        return super().available and self.function is not None

    @property
    def name(self) -> str:
        function = self.function
        return function.name if function else self.identity

    @property
    def is_on(self) -> bool | None:
        function = self.function
        return function.running if function else None

    @property
    def extra_state_attributes(self) -> dict[str, str | int]:
        function = self.function
        if not function:
            return {"function_identity": self.identity}
        return {"function_type": function.function_type, "function_id": function.function_id, "function_identity": self.identity}

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.unique_id)},
            name=self._entry.title,
            manufacturer="QLC+",
            model="QLC+ 4 Web API",
            configuration_url=self.coordinator.client.web_url,
        )

    async def async_turn_on(self, **kwargs: object) -> None:
        await self.coordinator.async_set_function_state(self.identity, True)

    async def async_turn_off(self, **kwargs: object) -> None:
        await self.coordinator.async_set_function_state(self.identity, False)
