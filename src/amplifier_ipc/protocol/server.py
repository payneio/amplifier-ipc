"""Generic JSON-RPC 2.0 server with method dispatch for Amplifier IPC packages.

Discovers components and content from a package at startup, then serves
describe / content.read / content.list / tool.execute / hook.emit requests
over newline-delimited JSON-RPC 2.0 framing.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import logging
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from amplifier_ipc.protocol.client import Client
from amplifier_ipc.protocol.content import read_content
from amplifier_ipc.protocol.discovery import scan_content, scan_package
from amplifier_ipc.protocol.errors import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    JsonRpcError,
    make_error_response,
)
from amplifier_ipc.protocol.framing import read_message, write_message
from amplifier_ipc.protocol.models import HookAction, HookResult

_log = logging.getLogger(__name__)


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

        # Discover component CLASSES (not instances) — instantiation is deferred
        # until after configuration arrives (lazy instantiation for the configure
        # protocol).
        discovered = scan_package(package_name)
        self._content_paths: list[str] = scan_content(package_name)

        # Store classes for lazy instantiation
        self._tool_classes: list[type] = discovered.get("tool", [])
        self._hook_classes: list[type] = discovered.get("hook", [])
        self._orchestrator_classes: list[type] = discovered.get("orchestrator", [])
        self._context_manager_classes: list[type] = discovered.get(
            "context_manager", []
        )
        self._provider_classes: list[type] = discovered.get("provider", [])

        # Lazy instantiation state — populated by handle_configure or _ensure_instances
        self._instances_ready = False
        self._tool_instances: list[Any] = []
        self._hook_instances: list[Any] = []
        self._orchestrator_instances: list[Any] = []
        self._context_manager_instances: list[Any] = []
        self._provider_instances: list[Any] = []

        # Runtime lookup tables — built by _build_runtime_state after instantiation
        self._tools: dict[str, Any] = {}
        self._hooks: dict[str, list[Any]] = {}
        self._components: dict[str, list[Any]] = {}

        # Resolve the package directory
        mod = importlib.import_module(package_name)
        if mod.__file__ is None:
            raise RuntimeError(
                f"Package {package_name!r} has no __file__ (namespace package?)"
            )
        self._package_dir = Path(mod.__file__).parent

        # Tracks the active orchestrator's IPC client during orchestrator.execute,
        # so tools can use it to make delegate/task calls back to the host.
        self._current_orchestrator_client: Any = None

        # Tracks the orchestrator instance currently running execute() so that
        # an orchestrator.cancel request can reach it.
        self._active_orchestrator_instance: Any = None

    # ------------------------------------------------------------------
    # Lazy instantiation and configuration
    # ------------------------------------------------------------------

    async def handle_configure(self, params: dict) -> dict:
        """Instantiate all discovered component classes, passing config when provided.

        Components whose name appears in ``params["config"]`` are instantiated
        with ``cls(config=comp_config)``; all others are instantiated with no
        arguments via ``cls()``.  After all components are instantiated the
        runtime lookup tables (_tools, _hooks, _components) are built.

        Args:
            params: Dict optionally containing ``config`` — a mapping of
                component name -> config dict.

        Returns:
            ``{"status": "ok"}``
        """
        config_map: dict = params.get("config", {})

        # Reset instance lists first so configure is idempotent — a second call
        # (e.g. reconnection or protocol retry) replaces instances rather than
        # appending to them, which would double every component.
        self._tool_instances = []
        self._hook_instances = []
        self._orchestrator_instances = []
        self._context_manager_instances = []
        self._provider_instances = []

        def _instantiate(classes: list[type], instances: list) -> None:
            for cls in classes:
                comp_name = getattr(cls, "name", cls.__name__)
                comp_config = config_map.get(comp_name)
                if comp_config is not None:
                    instances.append(cls(config=comp_config))
                else:
                    instances.append(cls())

        _instantiate(self._tool_classes, self._tool_instances)
        _instantiate(self._hook_classes, self._hook_instances)
        _instantiate(self._orchestrator_classes, self._orchestrator_instances)
        _instantiate(self._context_manager_classes, self._context_manager_instances)
        _instantiate(self._provider_classes, self._provider_instances)

        self._instances_ready = True
        self._build_runtime_state()
        return {"status": "ok"}

    def _ensure_instances(self) -> None:
        """Auto-instantiate all components with no arguments if configure was never called.

        This is a convenience fallback so that callers never need to check
        ``_instances_ready`` explicitly — any handler that needs instances can
        simply call ``_ensure_instances()`` at the top of its body.
        """
        if not self._instances_ready:
            for cls in self._tool_classes:
                self._tool_instances.append(cls())
            for cls in self._hook_classes:
                self._hook_instances.append(cls())
            for cls in self._orchestrator_classes:
                self._orchestrator_instances.append(cls())
            for cls in self._context_manager_classes:
                self._context_manager_instances.append(cls())
            for cls in self._provider_classes:
                self._provider_instances.append(cls())
            self._instances_ready = True
            self._build_runtime_state()

    def _build_runtime_state(self) -> None:
        """Build runtime lookup tables from the current instance lists.

        Populates ``_tools`` (name -> instance), ``_hooks`` (event -> sorted
        list of instances), and ``_components`` (component-type -> list).
        """
        # Build _tools: name -> instance
        self._tools = {}
        for tool_instance in self._tool_instances:
            name = getattr(tool_instance, "name", None)
            if name:
                self._tools[name] = tool_instance

        # Build _hooks: event -> list of instances sorted by priority (ascending)
        self._hooks = {}
        seen: set[int] = set()
        unique_hook_instances: list[Any] = []
        for hook_instance in self._hook_instances:
            events = getattr(
                hook_instance,
                "events",
                getattr(hook_instance, "__amplifier_hook_events__", []),
            )
            for event in events:
                self._hooks.setdefault(event, []).append(hook_instance)
            if id(hook_instance) not in seen:
                seen.add(id(hook_instance))
                unique_hook_instances.append(hook_instance)
        self._hook_instances = unique_hook_instances

        for event in self._hooks:
            self._hooks[event].sort(
                key=lambda h: getattr(
                    h,
                    "priority",
                    getattr(h, "__amplifier_hook_priority__", 0),
                )
            )

        # Build _components: component-type -> list of instances
        self._components = {
            "orchestrator": self._orchestrator_instances,
            "context_manager": self._context_manager_instances,
            "provider": self._provider_instances,
        }

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

            # orchestrator.execute requires bidirectional access to reader/writer
            # so it is handled here rather than in _dispatch().
            if method == "orchestrator.execute":
                try:
                    result = await self._handle_orchestrator_execute(
                        params or {}, reader, writer
                    )
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
    # Orchestrator execution
    # ------------------------------------------------------------------

    async def _handle_orchestrator_execute(
        self,
        params: dict[str, Any],
        reader: asyncio.StreamReader,
        writer: Any,
    ) -> Any:
        """Run the named (or first) orchestrator component and return its result.

        This method is called from :meth:`handle_stream` rather than
        ``_dispatch`` because the orchestrator needs a :class:`Client` that
        shares the *same* reader/writer as the server so it can make
        ``request.*`` calls back to the host while the main dispatch loop is
        suspended awaiting this coroutine.

        Args:
            params: The ``orchestrator.execute`` params dict, expected to
                contain at minimum ``prompt`` and optionally ``system_prompt``,
                ``orchestrator`` (name), and ``config``.
            reader: The asyncio StreamReader backing the server's stdin.
            writer: The writer backing the server's stdout.

        Returns:
            Whatever the orchestrator's ``execute()`` coroutine returns
            (typically a ``str`` with the final assistant response text).

        Raises:
            JsonRpcError: INVALID_PARAMS if no orchestrators are registered or
                the named orchestrator is not found.
        """
        self._ensure_instances()
        orchestrators = self._components.get("orchestrator", [])
        if not orchestrators:
            raise JsonRpcError(
                INVALID_PARAMS, "No orchestrators registered in this service"
            )

        # Select orchestrator by name if specified, else use the first one.
        orchestrator_name = params.get("orchestrator")
        if orchestrator_name:
            orch_instance = next(
                (
                    o
                    for o in orchestrators
                    if getattr(o, "name", None) == orchestrator_name
                ),
                None,
            )
            if orch_instance is None:
                raise JsonRpcError(
                    INVALID_PARAMS,
                    f"Orchestrator '{orchestrator_name}' not found in this service",
                )
        else:
            orch_instance = orchestrators[0]

        prompt: str = params.get("prompt", "")
        system_prompt: str = params.get("system_prompt", "")

        # Merge system_prompt into config so the orchestrator can access it.
        config: dict[str, Any] = dict(params.get("config") or {})
        if system_prompt:
            config.setdefault("system_prompt", system_prompt)

        # Use a local client that handles same-service calls (hooks, context,
        # tools) without going through IPC.  This avoids the deadlock that
        # would occur if those calls were routed back to this service via the
        # host while handle_stream() is suspended awaiting this coroutine.
        # Only truly external calls (e.g. request.provider_complete) are
        # forwarded to the host over the real reader/writer channel.
        client = _OrchestratorLocalClient(
            server=self, ipc_reader=reader, ipc_writer=writer
        )
        self._current_orchestrator_client = client
        self._active_orchestrator_instance = orch_instance
        try:
            return await orch_instance.execute(
                prompt=prompt, config=config, client=client
            )
        finally:
            self._current_orchestrator_client = None
            self._active_orchestrator_instance = None
            # Cancel any background IPC read task started by the local client.
            ipc = client._ipc_client
            if (
                ipc is not None
                and ipc._read_task is not None
                and not ipc._read_task.done()
            ):
                ipc._read_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await ipc._read_task

    async def _handle_orchestrator_cancel(
        self, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Cancel the currently executing orchestrator.

        Looks up the active orchestrator instance (set by
        :meth:`_handle_orchestrator_execute`) and calls its ``cancel()``
        method.  If a specific orchestrator name is provided via
        ``params["orchestrator"]``, that named instance is used instead,
        so the call also works before execution starts (the cancel flag
        will be honoured at the top of the next :meth:`execute` call).

        Args:
            params: Optional dict with an ``orchestrator`` key (name string).

        Returns:
            ``{"status": "ok"}`` when a ``cancel()``-capable instance was
            found, or ``{"status": "no_active_orchestrator"}`` otherwise.
        """
        self._ensure_instances()
        orchestrator_name: str | None = params.get("orchestrator")

        if orchestrator_name:
            # Caller specified a name — find that instance directly.
            orch_instance = next(
                (
                    o
                    for o in self._orchestrator_instances
                    if getattr(o, "name", None) == orchestrator_name
                ),
                None,
            )
        else:
            # Default to whatever is currently executing.
            orch_instance = self._active_orchestrator_instance

        if orch_instance is None or not hasattr(orch_instance, "cancel"):
            return {"status": "no_active_orchestrator"}

        orch_instance.cancel()
        _log.info(
            "Orchestrator cancel requested for %r",
            getattr(orch_instance, "name", type(orch_instance).__name__),
        )
        return {"status": "ok"}

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
        if method == "configure":
            return await self.handle_configure(params or {})
        if method == "content.read":
            return await self._handle_content_read(params or {})
        if method == "content.list":
            return await self._handle_content_list(params or {})
        if method == "tool.execute":
            return await self._handle_tool_execute(params or {})
        if method == "hook.emit":
            return await self._handle_hook_emit(params or {})
        if method == "context.add_message":
            return await self._handle_context_add_message(params or {})
        if method == "context.get_messages":
            return await self._handle_context_get_messages(params or {})
        if method == "context.clear":
            return await self._handle_context_clear()
        if method == "provider.complete":
            return await self._handle_provider_complete(params or {})
        if method == "orchestrator.cancel":
            return await self._handle_orchestrator_cancel(params or {})
        raise JsonRpcError(METHOD_NOT_FOUND, f"Method not found: {method!r}")

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    async def _handle_describe(self) -> dict[str, Any]:
        """Return the package name and all discovered capabilities.

        Uses class-level metadata so that describe works before configure is
        called.  Decorator attributes (``name``, ``description``,
        ``input_schema``, ``__amplifier_hook_events__``, etc.) are set on the
        class itself, so they are accessible whether or not an instance has
        been created.
        """
        tools = []
        for cls in self._tool_classes:
            schema = getattr(cls, "input_schema", {})
            # input_schema may be a @property descriptor when accessed on
            # the class rather than an instance — fall back to empty dict
            # so describe still succeeds (the real schema is used at runtime).
            if isinstance(schema, property):
                schema = {"type": "object", "properties": {}}
            tools.append(
                {
                    "name": getattr(cls, "name", ""),
                    "description": getattr(cls, "description", ""),
                    "input_schema": schema,
                }
            )

        hooks = [
            {
                "name": getattr(cls, "name", cls.__name__),
                "events": getattr(cls, "__amplifier_hook_events__", []),
                "priority": getattr(cls, "__amplifier_hook_priority__", 0),
            }
            for cls in self._hook_classes
        ]

        orchestrators = [
            {"name": getattr(cls, "name", cls.__name__)}
            for cls in self._orchestrator_classes
        ]
        context_managers = [
            {"name": getattr(cls, "name", cls.__name__)}
            for cls in self._context_manager_classes
        ]
        providers = [
            {"name": getattr(cls, "name", cls.__name__)}
            for cls in self._provider_classes
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
        self._ensure_instances()
        name: str | None = params.get("name")
        if not name:
            raise JsonRpcError(INVALID_PARAMS, "Missing required parameter: name")

        tool_instance = self._tools.get(name)
        if tool_instance is None:
            raise JsonRpcError(INVALID_PARAMS, f"Unknown tool: {name!r}")

        input_data: dict[str, Any] = params.get("input", {})
        if (
            hasattr(tool_instance, "client")
            and self._current_orchestrator_client is not None
        ):
            tool_instance.client = self._current_orchestrator_client
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
        self._ensure_instances()
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

    async def _handle_context_add_message(self, params: dict[str, Any]) -> Any:
        """Add a message to the registered context manager.

        Args:
            params: Must contain ``message`` (a serialised :class:`Message` dict).

        Raises:
            JsonRpcError: INVALID_PARAMS if no context manager is registered or
                ``message`` is missing.
        """
        from amplifier_ipc.protocol.models import Message

        self._ensure_instances()
        ctx_managers = self._components.get("context_manager", [])
        if not ctx_managers:
            raise JsonRpcError(
                INVALID_PARAMS, "No context manager registered in this service"
            )
        ctx = ctx_managers[0]

        message_data = params.get("message")
        if message_data is None:
            raise JsonRpcError(INVALID_PARAMS, "Missing required parameter: message")

        message = Message.model_validate(message_data)
        await ctx.add_message(message)
        return {"ok": True}

    async def _handle_context_get_messages(self, params: dict[str, Any]) -> Any:
        """Return messages from the registered context manager.

        Args:
            params: Optional ``provider_info`` dict passed through to the
                context manager.

        Raises:
            JsonRpcError: INVALID_PARAMS if no context manager is registered.
        """
        self._ensure_instances()
        ctx_managers = self._components.get("context_manager", [])
        if not ctx_managers:
            raise JsonRpcError(
                INVALID_PARAMS, "No context manager registered in this service"
            )
        ctx = ctx_managers[0]

        if hasattr(ctx, "client") and self._current_orchestrator_client is not None:
            ctx.client = self._current_orchestrator_client

        provider_info: dict[str, Any] = dict(params) if params else {}
        messages = await ctx.get_messages(provider_info)

        # Serialise pydantic models if needed
        result = []
        for m in messages:
            if isinstance(m, BaseModel):
                result.append(m.model_dump(mode="json"))
            elif isinstance(m, dict):
                result.append(m)
            else:
                result.append(m)
        return result

    async def _handle_context_clear(self) -> Any:
        """Clear messages in the registered context manager.

        Raises:
            JsonRpcError: INVALID_PARAMS if no context manager is registered.
        """
        self._ensure_instances()
        ctx_managers = self._components.get("context_manager", [])
        if not ctx_managers:
            raise JsonRpcError(
                INVALID_PARAMS, "No context manager registered in this service"
            )
        ctx = ctx_managers[0]
        await ctx.clear()
        return {"ok": True}

    async def _handle_provider_complete(self, params: dict[str, Any]) -> Any:
        """Call the registered provider's complete() method.

        Args:
            params: Must contain ``request`` (a serialised :class:`ChatRequest`
                dict) and optionally ``provider`` (name to select among multiple
                registered providers).

        Raises:
            JsonRpcError: INVALID_PARAMS if no provider is registered, the
                named provider is not found, or ``request`` is missing.
        """
        from amplifier_ipc.protocol.models import ChatRequest

        self._ensure_instances()
        providers = self._components.get("provider", [])
        if not providers:
            raise JsonRpcError(INVALID_PARAMS, "No provider registered in this service")

        provider_name = params.get("provider")
        if provider_name:
            provider_instance = next(
                (p for p in providers if getattr(p, "name", None) == provider_name),
                None,
            )
            if provider_instance is None:
                raise JsonRpcError(
                    INVALID_PARAMS,
                    f"Provider '{provider_name}' not found in this service",
                )
        else:
            provider_instance = providers[0]

        request_data = params.get("request")
        if request_data is None:
            raise JsonRpcError(INVALID_PARAMS, "Missing required parameter: request")

        request = ChatRequest.model_validate(request_data)
        # Pass through any extra kwargs from params (e.g. model, temperature)
        extra_kwargs = {
            k: v for k, v in params.items() if k not in ("request", "provider")
        }
        response = await provider_instance.complete(request, **extra_kwargs)

        if isinstance(response, BaseModel):
            return response.model_dump(mode="json")
        return response

    # ------------------------------------------------------------------
    # Entry point for service processes
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Run the server, connecting stdin/stdout as asyncio streams."""
        asyncio.run(self._run())

    async def _run(self) -> None:
        """Internal async entry point — sets up stdin/stdout streams."""
        loop = asyncio.get_running_loop()

        # Use a large limit (10 MB) so that messages containing large payloads
        # (e.g. orchestrator.execute with a full system prompt) are not truncated
        # by the default 64 KB asyncio.StreamReader limit.
        _STREAM_LIMIT = 10 * 1024 * 1024  # 10 MB

        # --- stdin as StreamReader ---
        reader = asyncio.StreamReader(limit=_STREAM_LIMIT)
        read_protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: read_protocol, sys.stdin)

        # --- stdout as transport-backed writer ---
        write_transport, _ = await loop.connect_write_pipe(
            asyncio.BaseProtocol, sys.stdout
        )
        writer = _StdoutWriter(write_transport)

        await self.handle_stream(reader, writer)


class _OrchestratorLocalClient:
    """Pseudo-client for orchestrator.execute that avoids same-service IPC deadlocks.

    When the orchestrator's ``execute()`` runs, the server's ``handle_stream()``
    loop is suspended.  Any ``request.*`` call that would normally route back to
    THIS service via the host would deadlock: the service can't read from stdin
    while suspended.

    This client handles calls to same-service components (hooks, context manager,
    tools) by dispatching them directly to the server's handler methods.  Only
    calls to external services (e.g. ``request.provider_complete``) are forwarded
    to the host over the real IPC channel.

    Notifications (``send_notification``) are always written to the actual stdout
    so that the host's orchestrator loop receives them (stream.token etc.).
    """

    def __init__(
        self,
        server: "Server",
        ipc_reader: asyncio.StreamReader,
        ipc_writer: Any,
    ) -> None:
        self._server = server
        self._ipc_reader = ipc_reader
        self._ipc_writer = ipc_writer
        self._ipc_client: Client | None = None

    async def request(self, method: str, params: Any = None) -> Any:
        """Route a request either locally or via IPC.

        Same-service operations are dispatched directly to the server's
        internal handler methods; external operations go through the host.
        """
        p: dict[str, Any] = dict(params) if isinstance(params, dict) else {}

        if method == "request.hook_emit":
            return await self._server._handle_hook_emit(p)

        if method == "request.context_add_message":
            result = await self._server._handle_context_add_message(p)
            # Notify the host so it can persist the message to the session
            # transcript.  The local handler already added the message to the
            # in-memory context manager; this notification lets the host write
            # it to disk for cross-turn replay.
            await self.send_notification("stream.context_message_added", p)
            return result

        if method == "request.context_get_messages":
            return await self._server._handle_context_get_messages(p)

        if method == "request.context_clear":
            return await self._server._handle_context_clear()

        if method == "request.tool_execute":
            # Check if the tool exists in this service's local registry.
            # If it does, execute locally (fast path).  If not, forward to the
            # host via IPC so it can route to the correct external service
            # (e.g. amplifier-skills provides load_skill, amplifier-modes
            # provides mode, etc.).
            tool_name = p.get("name", "")
            self._server._ensure_instances()
            if tool_name in self._server._tools:
                return await self._server._handle_tool_execute(p)
            # Tool not local — fall through to IPC.

        # Any other request (e.g. request.provider_complete, request.state_*,
        # request.session_spawn, or external tool calls) must go through the
        # host via IPC.
        return await self._ipc_request(method, params)

    async def send_notification(self, method: str, params: Any = None) -> None:
        """Write a JSON-RPC notification directly to the IPC writer (stdout)."""
        msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        await write_message(self._ipc_writer, msg)

    async def _ipc_request(self, method: str, params: Any = None) -> Any:
        """Send a request to the host and await its response over the IPC channel."""
        if self._ipc_client is None:
            self._ipc_client = Client(reader=self._ipc_reader, writer=self._ipc_writer)
        return await self._ipc_client.request(method, params)


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
        # Yield control to the event loop so that consumers (e.g. the CLI
        # display loop) can process events between writes.  Without this,
        # a burst of back-to-back notifications starves the reader task and
        # the user sees all output batched at the end.
        await asyncio.sleep(0)
