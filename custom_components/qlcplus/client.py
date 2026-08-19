"""Async client for QLC+ 4.14.x's built-in WebSocket API."""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import replace
import logging
from typing import Final

import aiohttp

from .const import API_PREFIX, WEBSOCKET_PATH
from .models import QLCFunction, QLCWidget

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
        self._reader_task: asyncio.Task[None] | None = None
        self._reply_waiter: tuple[str, asyncio.Future[list[str]]] | None = None
        self._function_event_handler: Callable[[int, bool], Awaitable[None]] | None = None
        self._widget_event_handler: Callable[[int, str, int], Awaitable[None]] | None = None
        self.last_error: str | None = None

    @property
    def connected(self) -> bool:
        return self._ws is not None and not self._ws.closed

    @property
    def url(self) -> str:
        scheme = "wss" if self.use_ssl else "ws"
        return f"{scheme}://{self.host}:{self.port}{WEBSOCKET_PATH}"

    @property
    def web_url(self) -> str:
        """Return the browser URL for QLC+'s Web Interface."""
        scheme = "https" if self.use_ssl else "http"
        return f"{scheme}://{self.host}:{self.port}"

    def set_function_event_handler(self, handler: Callable[[int, bool], Awaitable[None]]) -> None:
        """Register the recipient for QLC+ FUNCTION start/stop push events."""
        self._function_event_handler = handler

    def set_widget_event_handler(self, handler: Callable[[int, str, int], Awaitable[None]]) -> None:
        """Register the recipient for Virtual Console widget push events."""
        self._widget_event_handler = handler

    async def async_connect(self) -> None:
        """Open the WebSocket if it is not already open."""
        if self.connected:
            return
        await self.async_disconnect()
        try:
            self._session = aiohttp.ClientSession()
            # Home Assistant's aiohttp pins expect ClientWSTimeout here; passing
            # ClientTimeout can fail during WebSocket setup/cleanup. The WebSocket
            # heartbeat keeps an otherwise-idle persistent connection healthy.
            self._ws = await self._session.ws_connect(
                self.url,
                heartbeat=30,
                timeout=aiohttp.ClientWSTimeout(ws_receive=_TIMEOUT, ws_close=_TIMEOUT),
            )
            self._start_reader()
            self.last_error = None
            _LOGGER.debug("Connected to QLC+ WebSocket at %s", self.url)
        except (aiohttp.ClientError, asyncio.TimeoutError, TypeError) as err:
            self.last_error = str(err)
            await self.async_disconnect()
            raise QLCPlusConnectionError(f"Unable to connect to {self.url}: {err}") from err

    async def async_disconnect(self) -> None:
        """Close resources. Safe to call repeatedly."""
        reader_task = self._reader_task
        self._reader_task = None
        if reader_task is not None and reader_task is not asyncio.current_task():
            reader_task.cancel()
            try:
                await reader_task
            except asyncio.CancelledError:
                pass
        if self._reply_waiter is not None:
            _, waiter = self._reply_waiter
            if not waiter.done():
                waiter.set_exception(QLCPlusConnectionError("QLC+ WebSocket disconnected"))
            self._reply_waiter = None
        if self._ws is not None:
            try:
                await self._ws.close()
            except aiohttp.ClientError as err:
                _LOGGER.debug("Error while closing QLC+ WebSocket: %s", err)
        self._ws = None
        if self._session is not None:
            await self._session.close()
        self._session = None

    def _start_reader(self) -> None:
        """Ensure one task owns all WebSocket reads and processes push events."""
        if self._reader_task is None or self._reader_task.done():
            self._reader_task = asyncio.create_task(self._async_reader(), name="qlcplus_websocket_reader")

    async def _async_reader(self) -> None:
        """Dispatch WebSocket replies and FUNCTION state events."""
        assert self._ws is not None
        try:
            while True:
                message = await self._ws.receive()
                if message.type != aiohttp.WSMsgType.TEXT:
                    break
                fields = message.data.split("|")
                if len(fields) == 3 and fields[0] == "FUNCTION" and fields[2] in {"Running", "Stopped"}:
                    try:
                        function_id = int(fields[1])
                    except ValueError:
                        _LOGGER.debug("Ignoring QLC+ FUNCTION event with invalid ID: %s", message.data)
                        continue
                    if self._function_event_handler is not None:
                        await self._function_event_handler(function_id, fields[2] == "Running")
                    continue
                if len(fields) == 3 and fields[0].isdigit() and fields[1] in {"BUTTON", "SLIDER", "AUDIO_TRIGGERS"}:
                    if self._widget_event_handler is not None:
                        await self._widget_event_handler(int(fields[0]), fields[1], int(fields[2]))
                    continue
                waiter = self._reply_waiter
                if waiter is not None and len(fields) >= 2 and fields[:2] == [API_PREFIX, waiter[0]]:
                    if not waiter[1].done():
                        waiter[1].set_result(fields)
                    continue
                _LOGGER.debug("Ignoring unmatched QLC+ WebSocket message: %s", message.data)
        except (aiohttp.ClientError, asyncio.CancelledError) as err:
            if not isinstance(err, asyncio.CancelledError):
                self.last_error = str(err)
                _LOGGER.debug("QLC+ WebSocket reader stopped: %s", err)
            raise
        finally:
            if self._reply_waiter is not None:
                _, waiter = self._reply_waiter
                if not waiter.done():
                    waiter.set_exception(QLCPlusConnectionError("QLC+ WebSocket reader stopped"))

    async def _async_query(self, command: str, *args: str) -> list[str]:
        """Send a query and return its result fields."""
        async with self._lock:
            await self.async_connect()
            assert self._ws is not None
            self._start_reader()
            payload = "|".join((API_PREFIX, command, *args))
            _LOGGER.debug("QLC+ query: %s", payload)
            waiter: asyncio.Future[list[str]] = asyncio.get_running_loop().create_future()
            self._reply_waiter = (command, waiter)
            try:
                await self._ws.send_str(payload)
                fields = await asyncio.wait_for(waiter, _TIMEOUT)
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                self.last_error = str(err)
                await self.async_disconnect()
                raise QLCPlusConnectionError(f"QLC+ query {command} failed: {err}") from err
            finally:
                if self._reply_waiter is not None and self._reply_waiter[1] is waiter:
                    self._reply_waiter = None
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

    async def _async_direct_command(self, *parts: str) -> None:
        """Send QLC+'s low-overhead direct Virtual Console command."""
        async with self._lock:
            await self.async_connect()
            assert self._ws is not None
            try:
                await self._ws.send_str("|".join(parts))
            except aiohttp.ClientError as err:
                self.last_error = str(err)
                await self.async_disconnect()
                raise QLCPlusConnectionError(f"QLC+ direct command failed: {err}") from err

    async def async_get_functions(
        self, status_filter: Callable[[QLCFunction], bool] | None = None
    ) -> list[QLCFunction]:
        """Fetch all Functions and types, and states selected by ``status_filter``.

        QLC+ 4 returns names but not types in its Function list. Types must be
        read to retain stable identities and apply Home Assistant's filters;
        status reads, however, are only needed for exposed Functions.
        """
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
            key = (function_type.casefold(), name.casefold())
            seen[key] += 1
            function = QLCFunction(function_id, name, function_type, False, seen[key])
            if status_filter is None or status_filter(function):
                status = (await self._async_query("getFunctionStatus", str(function_id)) or ["Undefined"])[0]
                function = replace(function, running=status == "Running")
            discovered.append(function)
        return discovered

    async def async_get_function_status(self, function_id: int) -> bool:
        """Read a Function's authoritative run state."""
        result = await self._async_query("getFunctionStatus", str(function_id))
        if not result or result[0] not in {"Running", "Stopped"}:
            raise QLCPlusProtocolError(f"Unknown function status for {function_id}: {result!r}")
        return result[0] == "Running"

    async def async_get_widgets(self) -> list[QLCWidget]:
        """Fetch Virtual Console widgets and their current values."""
        raw = await self._async_query("getWidgetsList")
        if len(raw) % 2:
            raise QLCPlusProtocolError("getWidgetsList reply has an odd number of fields")
        widgets = []
        for widget_id, name in zip(raw[::2], raw[1::2], strict=True):
            try:
                numeric_id = int(widget_id)
            except ValueError as err:
                raise QLCPlusProtocolError(f"Invalid widget ID: {widget_id!r}") from err
            widget_type_reply = await self._async_query("getWidgetType", str(numeric_id))
            widget_type = widget_type_reply[-1] if widget_type_reply else "Unknown"
            status = await self._async_query("getWidgetStatus", str(numeric_id))
            try:
                value = int(status[-1]) if status and status[-1].isdigit() else 0
            except ValueError:
                value = 0
            widgets.append(QLCWidget(numeric_id, name, widget_type, value))
        return widgets

    async def async_set_widget_value(self, widget_id: int, value: int) -> None:
        """Control a VC Button, Slider, or Audio Trigger via the high-rate API."""
        await self._async_direct_command(str(widget_id), str(value))

    async def async_get_widget_value(self, widget_id: int) -> int:
        """Return the current value reported by a Virtual Console widget."""
        result = await self._async_query("getWidgetStatus", str(widget_id))
        if not result:
            raise QLCPlusProtocolError(f"No status returned for widget {widget_id}")
        try:
            return int(result[-1])
        except ValueError as err:
            raise QLCPlusProtocolError(f"Invalid status for widget {widget_id}: {result!r}") from err

    async def async_set_function_status(self, function_id: int, state: bool) -> None:
        """Start or stop a Function."""
        await self._async_command("setFunctionStatus", str(function_id), "1" if state else "0")

    async def async_start_function(self, function_id: int) -> None:
        await self.async_set_function_status(function_id, True)

    async def async_stop_function(self, function_id: int) -> None:
        await self.async_set_function_status(function_id, False)
