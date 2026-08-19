"""Coordinator behavior tests; QLC+ hardware is never required."""

import asyncio

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.qlcplus.client import QLCPlusConnectionError
from custom_components.qlcplus.coordinator import QLCPlusCoordinator
from custom_components.qlcplus.models import QLCFunction


class FakeConfigEntry:
    """Minimum config-entry contract consumed by DataUpdateCoordinator."""

    domain = "qlcplus"
    options = {}

    def async_on_unload(self, callback) -> None:
        """No-op: tests do not start the Home Assistant lifecycle."""


ENTRY = FakeConfigEntry()


class ClientWithEvents:
    """Minimal event-registration contract used by coordinator test clients."""

    def set_function_event_handler(self, handler) -> None:
        self.function_event_handler = handler


@pytest.mark.asyncio
async def test_changed_numeric_id_preserves_identity(tmp_path) -> None:
    class Client(ClientWithEvents):
        calls = 0

        async def async_get_functions(self, status_filter):
            self.calls += 1
            return [QLCFunction(12 if self.calls == 1 else 99, "House Red", "Scene", False)]

    coordinator = QLCPlusCoordinator(HomeAssistant(str(tmp_path)), Client(), ENTRY)
    first = await coordinator._async_update_data()
    second = await coordinator._async_update_data()
    assert list(first) == list(second)
    assert next(iter(second.values())).function_id == 99


@pytest.mark.asyncio
async def test_connection_failure_becomes_update_failed(tmp_path) -> None:
    class Client(ClientWithEvents):
        async def async_get_functions(self, status_filter):
            raise QLCPlusConnectionError("offline")

    coordinator = QLCPlusCoordinator(HomeAssistant(str(tmp_path)), Client(), ENTRY)
    with pytest.raises(UpdateFailed, match="offline"):
        await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_command_updates_only_the_affected_function_immediately(tmp_path) -> None:
    function = QLCFunction(12, "House Red", "Scene", False)

    class Client(ClientWithEvents):
        commands: list[tuple[int, bool]] = []

        async def async_set_function_status(self, function_id, state):
            self.commands.append((function_id, state))

    client = Client()
    coordinator = QLCPlusCoordinator(HomeAssistant(str(tmp_path)), client, ENTRY)
    coordinator.async_set_updated_data({function.identity: function})

    await coordinator.async_set_function_state(function.identity, True)

    assert client.commands == [(12, True)]
    assert coordinator.get_function(function.identity).running is True


@pytest.mark.asyncio
async def test_scan_preserves_recent_command_state_while_qlcplus_catches_up(tmp_path) -> None:
    function = QLCFunction(12, "House Red", "Scene", False)

    class Client(ClientWithEvents):
        async def async_get_functions(self, status_filter):
            return [QLCFunction(12, "House Red", "Scene", False)]

    coordinator = QLCPlusCoordinator(HomeAssistant(str(tmp_path)), Client(), ENTRY)
    coordinator._pending_states[function.identity] = (True, float("inf"))

    data = await coordinator._async_update_data()

    assert data[function.identity].running is True


@pytest.mark.asyncio
async def test_function_event_updates_matching_entity_without_a_refresh(tmp_path) -> None:
    function = QLCFunction(12, "House Red", "Scene", False)

    class Client(ClientWithEvents):
        pass

    client = Client()
    coordinator = QLCPlusCoordinator(HomeAssistant(str(tmp_path)), client, ENTRY)
    coordinator.async_set_updated_data({function.identity: function})

    await client.function_event_handler(12, True)

    assert coordinator.get_function(function.identity).running is True


@pytest.mark.asyncio
async def test_full_scan_started_before_command_is_discarded(tmp_path) -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    current = QLCFunction(12, "House Red", "Scene", True)

    class Client(ClientWithEvents):
        async def async_get_functions(self, status_filter):
            started.set()
            await release.wait()
            return [QLCFunction(12, "House Red", "Scene", False)]

    coordinator = QLCPlusCoordinator(HomeAssistant(str(tmp_path)), Client(), ENTRY)
    coordinator.async_set_updated_data({current.identity: current})
    scan = asyncio.create_task(coordinator._async_update_data())
    await started.wait()
    coordinator._state_generation += 1
    release.set()

    assert await scan == {current.identity: current}
