"""Protocol parsing tests using a mocked QLC+ WebSocket client."""

import pytest

from custom_components.qlcplus.client import QLCPlusClient, QLCPlusProtocolError


@pytest.mark.asyncio
async def test_rejects_odd_function_list(monkeypatch) -> None:
    client = QLCPlusClient("qlc.local", 9999, False)

    async def query(command, *args):
        assert command == "getFunctionsList"
        return ["12", "House Red", "13"]

    monkeypatch.setattr(client, "_async_query", query)
    with pytest.raises(QLCPlusProtocolError, match="odd"):
        await client.async_get_functions()


@pytest.mark.asyncio
async def test_discovers_types_states_and_duplicate_names(monkeypatch) -> None:
    client = QLCPlusClient("qlc.local", 9999, False)

    async def query(command, *args):
        replies = {
            ("getFunctionsList",): ["12", "House Red", "13", "House Red"],
            ("getFunctionType", "12"): ["Scene"],
            ("getFunctionStatus", "12"): ["Running"],
            ("getFunctionType", "13"): ["Scene"],
            ("getFunctionStatus", "13"): ["Stopped"],
        }
        return replies[(command, *args)]

    monkeypatch.setattr(client, "_async_query", query)
    functions = await client.async_get_functions()
    assert [(item.function_id, item.occurrence, item.running) for item in functions] == [(12, 1, True), (13, 2, False)]
