"""Async client for QLC+ 4.14.x's built-in WebSocket API."""

from __future__ import annotations

import asyncio
from collections import Counter
import logging
from typing import Final

import aiohttp

from .const import API_PREFIX, WEBSOCKET_PATH
from .models import QLCFunction

_LOGGER = logging.getLogger(__name__)
_TIMEOUT: Final = 10


class QLCPlusError(Exception):
    """Base QLC+ client error."""


class QLCPlusConnectionError(QLCPlusError):
    """QLC+ is not reachable."""


class QLCPlusProtocolError(QLCPlusError):
    """QLC+ sent an unexpected protocol message."""


class QLCPlusClient:
    """One serialized WebSocket connection to a QLC+ Web API server.

    QLC+ replies have no request ID, therefore requests must be serialized.
    Commands that change state do not produce a reply in the upstream server.
    """

    def __init__(self, host: str, port: int | float, use_ssl: bool) -> None:
        self.host = host
        self.port = int(port)
        self.use_ssl = use_ssl
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._lock = asyncio.Lock()
        self.last_error: str | None = None

    @property
    def connected(self) -> bool:
        return self._ws is not None and not self._ws.closed

    @property
    def url(self) -> str:
        scheme = "wss" if self.use_ssl else "ws"
        return f"{scheme}://{self.host}:{self.port}{WEBSOCKET_PATH}"

    async def async_connect(self) -> None:
        """Open the WebSocket if it is not already open."""
        if self.connected:
            return
        await self.async_disconnect()
        try:
            self._session = aiohttp.ClientSession()
            # Home Assistant's aiohttp pins expect ClientWSTimeout here; passing
            # ClientTimeout can fail during WebSocket setup/cleanup. Do not use
            # heartbeat: QLC+ 4's embedded server does not document ping/pong
            # support, and the coordinator's regular requests keep the socket live.
            self._ws = await self._session.ws_connect(
                self.url,
                timeout=aiohttp.ClientWSTimeout(ws_receive=_TIMEOUT, ws_close=_TIMEOUT),
            )
            self.last_error = None
            _LOGGER.debug("Connected to QLC+ WebSocket at %s", self.url)
        except (aiohttp.ClientError, asyncio.TimeoutError, TypeError) as err:
            self.last_error = str(err)
            await self.async_disconnect()
            raise QLCPlusConnectionError(f"Unable to connect to {self.url}: {err}") from err

    async def async_disconnect(self) -> None:
        """Close resources. Safe to call repeatedly."""
        if self._ws is not None:
            try:
                await self._ws.close()
            except aiohttp.ClientError as err:
                _LOGGER.debug("Error while closing QLC+ WebSocket: %s", err)
        self._ws = None
        if self._session is not None:
            await self._session.close()
        self._session = None

    async def _async_query(self, command: str, *args: str) -> list[str]:
        """Send a query and return its result fields."""
        async with self._lock:
            await self.async_connect()
            assert self._ws is not None
            payload = "|".join((API_PREFIX, command, *args))
            _LOGGER.debug("QLC+ query: %s", payload)
            try:
                await self._ws.send_str(payload)
                message = await self._ws.receive(timeout=_TIMEOUT)
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                self.last_error = str(err)
                await self.async_disconnect()
                raise QLCPlusConnectionError(f"QLC+ query {command} failed: {err}") from err
            if message.type != aiohttp.WSMsgType.TEXT:
                await self.async_disconnect()
                raise QLCPlusConnectionError(f"QLC+ WebSocket closed during {command}")
            fields = message.data.split("|")
            if len(fields) < 2 or fields[0] != API_PREFIX or fields[1] != command:
                raise QLCPlusProtocolError(f"Unexpected QLC+ reply to {command}: {message.data!r}")
            _LOGGER.debug("QLC+ reply: %s", message.data)
            return fields[2:]

    async def _async_command(self, command: str, *args: str) -> None:
        """Send a command that QLC+ 4 intentionally does not acknowledge."""
        async with self._lock:
            await self.async_connect()
            assert self._ws is not None
            payload = "|".join((API_PREFIX, command, *args))
            _LOGGER.debug("QLC+ command: %s", payload)
            try:
                await self._ws.send_str(payload)
            except aiohttp.ClientError as err:
                self.last_error = str(err)
                await self.async_disconnect()
                raise QLCPlusConnectionError(f"QLC+ command {command} failed: {err}") from err

    async def async_get_functions(self) -> list[QLCFunction]:
        """Fetch all Functions, types and authoritative run states."""
        raw = await self._async_query("getFunctionsList")
        if len(raw) % 2:
            raise QLCPlusProtocolError("getFunctionsList reply has an odd number of fields")
        pairs: list[tuple[int, str]] = []
        for function_id, name in zip(raw[::2], raw[1::2], strict=True):
            try:
                pairs.append((int(function_id), name))
            except ValueError as err:
                raise QLCPlusProtocolError(f"Invalid function ID: {function_id!r}") from err
        discovered: list[QLCFunction] = []
        seen: Counter[tuple[str, str]] = Counter()
        for function_id, name in pairs:
            function_type = (await self._async_query("getFunctionType", str(function_id)) or ["Undefined"])[0]
            status = (await self._async_query("getFunctionStatus", str(function_id)) or ["Undefined"])[0]
            key = (function_type.casefold(), name.casefold())
            seen[key] += 1
            discovered.append(QLCFunction(function_id, name, function_type, status == "Running", seen[key]))
        return discovered

    async def async_get_function_status(self, function_id: int) -> bool:
        """Read a Function's authoritative run state."""
        result = await self._async_query("getFunctionStatus", str(function_id))
        if not result or result[0] not in {"Running", "Stopped"}:
            raise QLCPlusProtocolError(f"Unknown function status for {function_id}: {result!r}")
        return result[0] == "Running"

    async def async_set_function_status(self, function_id: int, state: bool) -> None:
        """Start or stop a Function."""
        await self._async_command("setFunctionStatus", str(function_id), "1" if state else "0")

    async def async_start_function(self, function_id: int) -> None:
        await self.async_set_function_status(function_id, True)

    async def async_stop_function(self, function_id: int) -> None:
        await self.async_set_function_status(function_id, False)
