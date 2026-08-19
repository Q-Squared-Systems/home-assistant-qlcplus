"""Protocol parsing tests using a mocked QLC+ WebSocket client."""

import pytest
import aiohttp

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


@pytest.mark.asyncio
async def test_discovers_all_functions_but_reads_only_filtered_statuses(monkeypatch) -> None:
    client = QLCPlusClient("qlc.local", 9999, False)
    queries = []

    async def query(command, *args):
        queries.append((command, *args))
        replies = {
            ("getFunctionsList",): ["12", "House Red", "13", "Worklight"],
            ("getFunctionType", "12"): ["Scene"],
            ("getFunctionType", "13"): ["Chaser"],
            ("getFunctionStatus", "12"): ["Running"],
        }
        return replies[(command, *args)]

    monkeypatch.setattr(client, "_async_query", query)
    functions = await client.async_get_functions(lambda function: function.name == "House Red")

    assert [(item.name, item.running) for item in functions] == [("House Red", True), ("Worklight", False)]
    assert ("getFunctionStatus", "12") in queries
    assert ("getFunctionStatus", "13") not in queries


@pytest.mark.asyncio
async def test_connect_uses_websocket_specific_timeout(monkeypatch) -> None:
    client = QLCPlusClient("qlc.local", 9999, False)
    captured = {}

    class FakeWebSocket:
        closed = False

        async def close(self):
            self.closed = True

    async def ws_connect(self, url, **kwargs):
        captured["url"] = url
        captured["timeout"] = kwargs["timeout"]
        captured["heartbeat"] = kwargs["heartbeat"]
        return FakeWebSocket()

    monkeypatch.setattr(aiohttp.ClientSession, "ws_connect", ws_connect)
    await client.async_connect()
    assert captured["url"] == "ws://qlc.local:9999/qlcplusWS"
    assert isinstance(captured["timeout"], aiohttp.ClientWSTimeout)
    assert captured["timeout"].ws_receive == 10
    assert captured["heartbeat"] == 30
    await client.async_disconnect()


def test_url_normalizes_a_home_assistant_number_selector_float() -> None:
    client = QLCPlusClient("qlc.local", 9999.0, False)
    assert client.url == "ws://qlc.local:9999/qlcplusWS"
    assert client.web_url == "http://qlc.local:9999"


@pytest.mark.asyncio
async def test_query_skips_unsolicited_function_event(monkeypatch) -> None:
    client = QLCPlusClient("qlc.local", 9999, False)

    class FakeWebSocket:
        closed = False

        async def send_str(self, payload):
            assert payload == "QLC+API|getFunctionsList"

        async def receive(self, timeout):
            return replies.pop(0)

    replies = [
        aiohttp.WSMessage(aiohttp.WSMsgType.TEXT, "FUNCTION|0|Running", ""),
        aiohttp.WSMessage(aiohttp.WSMsgType.TEXT, "QLC+API|getFunctionsList|0|House Red", ""),
    ]
    client._ws = FakeWebSocket()

    async def connect():
        return None

    monkeypatch.setattr(client, "async_connect", connect)
    assert await client._async_query("getFunctionsList") == ["0", "House Red"]
