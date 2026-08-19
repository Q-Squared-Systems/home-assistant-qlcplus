"""Coordinator behavior tests; QLC+ hardware is never required."""

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.qlcplus.client import QLCPlusConnectionError
from custom_components.qlcplus.coordinator import QLCPlusCoordinator
from custom_components.qlcplus.models import QLCFunction


class FakeConfigEntry:
    """Minimum config-entry contract consumed by DataUpdateCoordinator."""

    domain = "qlcplus"

    def async_on_unload(self, callback) -> None:
        """No-op: tests do not start the Home Assistant lifecycle."""


ENTRY = FakeConfigEntry()


@pytest.mark.asyncio
async def test_changed_numeric_id_preserves_identity(tmp_path) -> None:
    class Client:
        calls = 0

        async def async_get_functions(self):
            self.calls += 1
            return [QLCFunction(12 if self.calls == 1 else 99, "House Red", "Scene", False)]

    coordinator = QLCPlusCoordinator(HomeAssistant(str(tmp_path)), Client(), ENTRY)
    first = await coordinator._async_update_data()
    second = await coordinator._async_update_data()
    assert list(first) == list(second)
    assert next(iter(second.values())).function_id == 99


@pytest.mark.asyncio
async def test_connection_failure_becomes_update_failed(tmp_path) -> None:
    class Client:
        async def async_get_functions(self):
            raise QLCPlusConnectionError("offline")

    coordinator = QLCPlusCoordinator(HomeAssistant(str(tmp_path)), Client(), ENTRY)
    with pytest.raises(UpdateFailed, match="offline"):
        await coordinator._async_update_data()
