"""JSON-RPC 2.0 client with request/response matching and notification support."""

from __future__ import annotations

import asyncio
from typing import Any, Callable

from amplifier_ipc.protocol.errors import JsonRpcError
from amplifier_ipc.protocol.framing import read_message, write_message


class Client:
    """JSON-RPC 2.0 client wrapping an asyncio StreamReader/StreamWriter pair.

    Sends requests with auto-incrementing ids, matches responses by id,
    handles interleaved notifications, and raises on errors or EOF.
    """

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: Any,
        on_notification: Callable[[dict], None] | None = None,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._next_id: int = 1
        self._pending: dict[int | str, asyncio.Future[Any]] = {}
        self._read_task: asyncio.Task[None] | None = None
        self.on_notification = on_notification

    def _ensure_read_loop(self) -> None:
        """Start the background read loop if it is not already running."""
        if self._read_task is None or self._read_task.done():
            self._read_task = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        """Background loop that reads and dispatches incoming messages."""
        try:
            while True:
                message = await read_message(self._reader)

                if message is None:
                    # EOF — fail all pending futures
                    self._fail_all_pending(ConnectionError("Connection closed (EOF)"))
                    return

                msg_id = message.get("id")

                # Response: has an 'id' and either 'result' or 'error'
                if msg_id is not None and ("result" in message or "error" in message):
                    future = self._pending.pop(msg_id, None)
                    if future is not None and not future.done():
                        if "error" in message:
                            err_payload = message["error"]
                            future.set_exception(
                                JsonRpcError(
                                    code=err_payload["code"],
                                    message=err_payload["message"],
                                    data=err_payload.get("data"),
                                )
                            )
                        else:
                            future.set_result(message["result"])

                # Notification: has 'method' but no 'id'
                elif "method" in message and msg_id is None:
                    if self.on_notification is not None:
                        self.on_notification(message)

        except Exception as exc:
            self._fail_all_pending(ConnectionError(f"Read loop failed: {exc}"))

    def _fail_all_pending(self, error: Exception) -> None:
        """Set an exception on all pending futures and clear the dict."""
        pending, self._pending = self._pending, {}
        for future in pending.values():
            if not future.done():
                future.set_exception(error)

    async def request(self, method: str, params: Any = None) -> Any:
        """Send a JSON-RPC request and return the result.

        Raises:
            JsonRpcError: If the server returns an error response.
            ConnectionError: If the connection closes before the response.
        """
        self._ensure_read_loop()

        req_id = self._next_id
        self._next_id += 1

        message: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
        }
        if params is not None:
            message["params"] = params

        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._pending[req_id] = future

        await write_message(self._writer, message)

        return await future

    async def send_notification(self, method: str, params: Any = None) -> None:
        """Send a JSON-RPC notification (fire-and-forget, no id).

        Args:
            method: The notification method name.
            params: Optional parameters for the notification.
        """
        message: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params is not None:
            message["params"] = params

        await write_message(self._writer, message)
