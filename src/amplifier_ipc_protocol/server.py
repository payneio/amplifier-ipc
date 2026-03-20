"""Generic JSON-RPC 2.0 server with method dispatch for Amplifier IPC packages.

Discovers components and content from a package at startup, then serves
describe / content.read / content.list / tool.execute / hook.emit requests
over newline-delimited JSON-RPC 2.0 framing.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from amplifier_ipc_protocol.content import read_content
from amplifier_ipc_protocol.discovery import scan_content, scan_package
from amplifier_ipc_protocol.errors import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    JsonRpcError,
    make_error_response,
)
from amplifier_ipc_protocol.framing import read_message, write_message
from amplifier_ipc_protocol.models import HookAction, HookResult


class Server:
    """Generic JSON-RPC 2.0 server for an Amplifier IPC package.

    Discovers components (tools, hooks, orchestrators, context managers,
    providers) and content files at construction time, then dispatches
    incoming requests to the appropriate handler.

    Args:
        package_name: The importable package name to scan.
    """

    def __init__(self, package_name: str) -> None:
        self._package_name = package_name

        # Discover components and content
        components = scan_package(package_name)
        self._content_paths: list[str] = scan_content(package_name)
        self._components: dict[str, list[Any]] = components

        # Resolve the package directory
        mod = importlib.import_module(package_name)
        if mod.__file__ is None:
            raise RuntimeError(
                f"Package {package_name!r} has no __file__ (namespace package?)"
            )
        self._package_dir = Path(mod.__file__).parent

        # Build _tools: name -> instance
        self._tools: dict[str, Any] = {}
        for tool_instance in components.get("tool", []):
            name = getattr(tool_instance, "name", None)
            if name:
                self._tools[name] = tool_instance

        # Build _hooks: event -> list of instances sorted by priority (ascending)
        self._hooks: dict[str, list[Any]] = {}
        # Keep an ordered, deduplicated list of all hook instances for describe
        self._hook_instances: list[Any] = []
        seen_hooks: set[Any] = set()
        for hook_instance in components.get("hook", []):
            events = getattr(
                hook_instance,
                "events",
                getattr(hook_instance, "__amplifier_hook_events__", []),
            )
            for event in events:
                self._hooks.setdefault(event, []).append(hook_instance)
            if hook_instance not in seen_hooks:
                seen_hooks.add(hook_instance)
                self._hook_instances.append(hook_instance)

        # Sort each event's hook list by priority (ascending = lower runs first)
        for event in self._hooks:
            self._hooks[event].sort(
                key=lambda h: getattr(
                    h,
                    "priority",
                    getattr(h, "__amplifier_hook_priority__", 0),
                )
            )

    # ------------------------------------------------------------------
    # Main stream loop
    # ------------------------------------------------------------------

    async def handle_stream(
        self,
        reader: asyncio.StreamReader,
        writer: Any,
    ) -> None:
        """Read JSON-RPC messages from *reader* until EOF and dispatch them.

        Responses are written to *writer* only for messages that carry an
        ``id`` field (i.e., requests, not notifications).

        Handles ``ValueError`` (parse errors) and ``JsonRpcError``/general
        exceptions per the JSON-RPC 2.0 spec.
        """
        while True:
            try:
                message = await read_message(reader)
            except ValueError as exc:
                # Malformed JSON — send parse-error response with null id
                await write_message(
                    writer,
                    make_error_response(None, PARSE_ERROR, str(exc)),
                )
                continue

            if message is None:
                # EOF — stop the loop
                break

            msg_id = message.get("id")
            method: str = message.get("method", "")
            params: Any = message.get("params")

            # Notifications (no id) are silently ignored per JSON-RPC 2.0
            if "id" not in message:
                continue

            try:
                result = await self._dispatch(method, params)
                await write_message(
                    writer,
                    {"jsonrpc": "2.0", "id": msg_id, "result": result},
                )
            except JsonRpcError as exc:
                await write_message(writer, exc.to_response(msg_id))
            except Exception as exc:  # noqa: BLE001
                await write_message(
                    writer,
                    make_error_response(msg_id, INTERNAL_ERROR, str(exc)),
                )

    # ------------------------------------------------------------------
    # Dispatcher
    # ------------------------------------------------------------------

    async def _dispatch(self, method: str, params: Any) -> Any:
        """Route *method* to the appropriate handler.

        Raises:
            JsonRpcError: With METHOD_NOT_FOUND if *method* is unknown.
        """
        if method == "describe":
            return await self._handle_describe()
        if method == "content.read":
            return await self._handle_content_read(params or {})
        if method == "content.list":
            return await self._handle_content_list(params or {})
        if method == "tool.execute":
            return await self._handle_tool_execute(params or {})
        if method == "hook.emit":
            return await self._handle_hook_emit(params or {})
        raise JsonRpcError(METHOD_NOT_FOUND, f"Method not found: {method!r}")

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    async def _handle_describe(self) -> dict[str, Any]:
        """Return the package name and all discovered capabilities."""
        tools = []
        for tool_instance in self._tools.values():
            tools.append(
                {
                    "name": getattr(tool_instance, "name", ""),
                    "description": getattr(tool_instance, "description", ""),
                    "input_schema": getattr(tool_instance, "input_schema", {}),
                }
            )

        hooks = []
        for hook_instance in self._hook_instances:
            hooks.append(
                {
                    "name": getattr(
                        hook_instance,
                        "name",
                        hook_instance.__class__.__name__,
                    ),
                    "events": getattr(
                        hook_instance,
                        "events",
                        getattr(hook_instance, "__amplifier_hook_events__", []),
                    ),
                    "priority": getattr(
                        hook_instance,
                        "priority",
                        getattr(hook_instance, "__amplifier_hook_priority__", 0),
                    ),
                }
            )

        orchestrators = [
            {"name": getattr(o, "name", o.__class__.__name__)}
            for o in self._components.get("orchestrator", [])
        ]
        context_managers = [
            {"name": getattr(c, "name", c.__class__.__name__)}
            for c in self._components.get("context_manager", [])
        ]
        providers = [
            {"name": getattr(p, "name", p.__class__.__name__)}
            for p in self._components.get("provider", [])
        ]

        return {
            "name": self._package_name,
            "capabilities": {
                "tools": tools,
                "hooks": hooks,
                "orchestrators": orchestrators,
                "context_managers": context_managers,
                "providers": providers,
                "content": {"paths": self._content_paths},
            },
        }

    async def _handle_content_read(self, params: dict[str, Any]) -> dict[str, Any]:
        """Read a content file and return its text.

        Raises:
            JsonRpcError: INVALID_PARAMS if ``path`` is missing or the file
                does not exist / escapes the package root.
        """
        path: str | None = params.get("path")
        if not path:
            raise JsonRpcError(INVALID_PARAMS, "Missing required parameter: path")

        text = read_content(self._package_dir, path)
        if text is None:
            raise JsonRpcError(
                INVALID_PARAMS, f"Content not found or inaccessible: {path!r}"
            )

        return {"content": text}

    async def _handle_content_list(self, params: dict[str, Any]) -> dict[str, Any]:
        """Return all known content paths, optionally filtered by prefix.

        Args:
            params: May contain an optional ``prefix`` string filter.
        """
        prefix: str | None = params.get("prefix")
        paths = self._content_paths
        if prefix:
            paths = [p for p in paths if p.startswith(prefix)]
        return {"paths": paths}

    async def _handle_tool_execute(self, params: dict[str, Any]) -> Any:
        """Execute the named tool with the provided input.

        Returns the tool result as a JSON-serialisable dict.  If the result
        is a Pydantic model, ``model_dump(mode='json')`` is called; otherwise
        the result is wrapped in ``{success: True, output: result}``.

        Raises:
            JsonRpcError: INVALID_PARAMS if ``name`` is missing or unknown.
        """
        name: str | None = params.get("name")
        if not name:
            raise JsonRpcError(INVALID_PARAMS, "Missing required parameter: name")

        tool_instance = self._tools.get(name)
        if tool_instance is None:
            raise JsonRpcError(INVALID_PARAMS, f"Unknown tool: {name!r}")

        input_data: dict[str, Any] = params.get("input", {})
        result = await tool_instance.execute(input_data)

        if isinstance(result, BaseModel):
            return result.model_dump(mode="json")
        return {"success": True, "output": result}

    async def _handle_hook_emit(self, params: dict[str, Any]) -> Any:
        """Emit a hook event and run all registered handlers in priority order.

        DENY and ASK_USER short-circuit the chain.  MODIFY updates the
        running ``data`` dict.  Returns the final ``HookResult`` as a
        JSON-serialisable dict.

        Raises:
            JsonRpcError: INVALID_PARAMS if ``event`` is missing.
        """
        event: str | None = params.get("event")
        if not event:
            raise JsonRpcError(INVALID_PARAMS, "Missing required parameter: event")

        data: dict[str, Any] = dict(params.get("data") or {})
        hooks = self._hooks.get(event, [])
        final_result: HookResult = HookResult(action=HookAction.CONTINUE)

        for hook_instance in hooks:
            result: HookResult = await hook_instance.handle(event, data)
            final_result = result

            if result.action in (HookAction.DENY, HookAction.ASK_USER):
                break

            if result.action == HookAction.MODIFY and result.data:
                data.update(result.data)

        return final_result.model_dump(mode="json")

    # ------------------------------------------------------------------
    # Entry point for service processes
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Run the server, connecting stdin/stdout as asyncio streams."""
        asyncio.run(self._run())

    async def _run(self) -> None:
        """Internal async entry point — sets up stdin/stdout streams."""
        loop = asyncio.get_event_loop()

        # --- stdin as StreamReader ---
        reader = asyncio.StreamReader()
        read_protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: read_protocol, sys.stdin)

        # --- stdout as transport-backed writer ---
        write_transport, _ = await loop.connect_write_pipe(
            asyncio.BaseProtocol, sys.stdout
        )
        writer = _StdoutWriter(write_transport)

        await self.handle_stream(reader, writer)


class _StdoutWriter:
    """Minimal writer wrapper around a write transport.

    Satisfies the ``write()`` / ``drain()`` interface expected by
    :func:`amplifier_ipc_protocol.framing.write_message`.
    """

    def __init__(self, transport: asyncio.BaseTransport) -> None:
        self._transport = transport

    def write(self, data: bytes) -> None:
        self._transport.write(data)  # type: ignore[attr-defined]

    async def drain(self) -> None:
        pass  # stdout transport doesn't need draining
