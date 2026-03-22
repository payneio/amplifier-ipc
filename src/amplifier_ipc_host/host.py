"""Host orchestration — ties config, lifecycle, registry, router, content, and persistence.

The :class:`Host` is the top-level coordinator for an IPC session.  It spawns
service subprocesses, discovers their capabilities, builds a routing table, runs
the orchestrator turn loop, persists the transcript, and tears everything down.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from amplifier_ipc_host.config import (
    HostSettings,
    SessionConfig,
    resolve_service_command,
)
from amplifier_ipc_host.content import assemble_system_prompt
from amplifier_ipc_host.events import (
    ApprovalRequestEvent,
    CompleteEvent,
    ErrorEvent,
    HostEvent,
    StreamContentBlockEndEvent,
    StreamContentBlockStartEvent,
    StreamThinkingEvent,
    StreamTokenEvent,
    StreamToolCallStartEvent,
)
from amplifier_ipc_host.lifecycle import ServiceProcess, shutdown_service, spawn_service
from amplifier_ipc_host.persistence import SessionPersistence
from amplifier_ipc_host.registry import CapabilityRegistry
from amplifier_ipc_host.router import Router
from amplifier_ipc_host.spawner import SpawnRequest, spawn_child_session
from amplifier_ipc_protocol.errors import JsonRpcError, make_error_response
from amplifier_ipc_protocol.framing import read_message, write_message

logger = logging.getLogger(__name__)

_DESCRIBE_TIMEOUT_S = 10.0


class Host:
    """Orchestrates a full IPC session: spawn → discover → route → persist → teardown.

    Args:
        config: Parsed session configuration (services, orchestrator, etc.).
        settings: Host-level settings including service command overrides.
        session_dir: Base directory for session persistence.  Defaults to
            ``~/.amplifier/sessions``.
    """

    def __init__(
        self,
        config: SessionConfig,
        settings: HostSettings,
        session_dir: Path | None = None,
    ) -> None:
        self._config = config
        self._settings = settings
        self._session_dir = session_dir or (Path.home() / ".amplifier" / "sessions")

        # Internal state — populated during run()
        self._services: dict[str, Any] = {}
        self._registry: CapabilityRegistry = CapabilityRegistry()
        self._router: Router | None = None
        self._persistence: SessionPersistence | None = None
        self._state: dict[str, Any] = {}
        self._provider_notification_queue: asyncio.Queue[dict[str, Any]] = (
            asyncio.Queue()
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self, prompt: str) -> AsyncIterator[HostEvent]:
        """Execute a full session turn, yielding events as they occur.

        1. Generate a session ID and create :class:`SessionPersistence`.
        2. Spawn all configured services.
        3. Discover capabilities via ``describe`` and build the registry.
        4. Resolve orchestrator / context-manager / provider service keys.
        5. Build a :class:`Router`.
        6. Assemble the system prompt via content resolution.
        7. Run the orchestrator turn loop, yielding :class:`HostEvent` instances.
        8. Persist metadata and finalize.

        Args:
            prompt: The user prompt to pass to the orchestrator.

        Yields:
            :class:`HostEvent` subclass instances as they are produced by the
            orchestrator loop, ending with a :class:`CompleteEvent`.

        Raises:
            RuntimeError: If the orchestrator, context manager, or provider
                declared in the config is not found in the registry.
        """
        session_id = uuid.uuid4().hex[:16]
        self._persistence = SessionPersistence(session_id, self._session_dir)

        try:
            # 1b. Load shared state from persistence
            self._state = self._persistence.load_state()

            # 2. Spawn services
            await self._spawn_services()

            # 3. Build registry
            await self._build_registry()

            # 4. Resolve service keys
            orchestrator_key = self._registry.get_orchestrator_service(
                self._config.orchestrator
            )
            context_manager_key = self._registry.get_context_manager_service(
                self._config.context_manager
            )
            provider_key = self._registry.get_provider_service(self._config.provider)

            if orchestrator_key is None:
                raise RuntimeError(
                    f"Orchestrator '{self._config.orchestrator}' not found in registry"
                )
            if context_manager_key is None:
                raise RuntimeError(
                    f"Context manager '{self._config.context_manager}' not found in registry"
                )
            if provider_key is None:
                raise RuntimeError(
                    f"Provider '{self._config.provider}' not found in registry"
                )

            # 5. Build router
            def _queue_provider_notification(msg: dict[str, Any]) -> None:
                """Sync callback that enqueues stream.provider.* notifications."""
                method: str = msg.get("method", "") if isinstance(msg, dict) else ""
                if method.startswith("stream.provider."):
                    self._provider_notification_queue.put_nowait(msg)

            async def _handle_spawn(params: Any) -> Any:
                """Handle request.session_spawn from the orchestrator."""
                p = params if isinstance(params, dict) else {}
                spawn_request = SpawnRequest(
                    agent=p.get("agent", "self"),
                    instruction=p.get("instruction", ""),
                    context_depth=p.get("context_depth", "none"),
                    context_scope=p.get("context_scope", "conversation"),
                    context_turns=p.get("context_turns"),
                    exclude_tools=p.get("exclude_tools"),
                    inherit_tools=p.get("inherit_tools"),
                    exclude_hooks=p.get("exclude_hooks"),
                    inherit_hooks=p.get("inherit_hooks"),
                    agents=p.get("agents"),
                    provider_preferences=p.get("provider_preferences"),
                    model_role=p.get("model_role"),
                )
                transcript = (
                    self._persistence.load_transcript() if self._persistence else []
                )
                return spawn_child_session(
                    parent_session_id=session_id,
                    parent_config={},  # TODO: expose full SessionConfig as dict
                    transcript=transcript,
                    request=spawn_request,
                )

            self._router = Router(
                registry=self._registry,
                services=self._services,
                context_manager_key=context_manager_key,
                provider_key=provider_key,
                provider_name=self._config.provider or None,
                state=self._state,
                on_provider_notification=_queue_provider_notification,
                spawn_handler=_handle_spawn,
            )

            # 6. Assemble system prompt
            system_prompt = await assemble_system_prompt(self._registry, self._services)

            # 6b. Stop the orchestrator service's Client background read loop.
            #
            # _build_registry() and assemble_system_prompt() use service.client.request()
            # which starts an asyncio background read task on process.stdout.
            # _orchestrator_loop() reads directly from the same process.stdout, so the
            # two readers conflict.  Cancelling the idle read task before the loop starts
            # avoids the error:
            #   RuntimeError: readuntil() called while another coroutine is already waiting
            orch_service = self._services[orchestrator_key]
            orch_client = getattr(orch_service, "client", None)
            if orch_client is not None:
                read_task = getattr(orch_client, "_read_task", None)
                if read_task is not None and not read_task.done():
                    read_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await read_task

            # 7. Orchestrator turn loop — yield events as they arrive
            async for event in self._orchestrator_loop(
                orchestrator_key=orchestrator_key,
                prompt=prompt,
                system_prompt=system_prompt,
            ):
                yield event

            # 8. Save state, metadata, and finalize
            self._persistence.save_state(self._state)
            self._persistence.save_metadata(
                {
                    "session_id": session_id,
                    "prompt": prompt,
                }
            )
            self._persistence.finalize()

        finally:
            await self._teardown_services()

    # ------------------------------------------------------------------
    # Orchestrator turn loop
    # ------------------------------------------------------------------

    async def _orchestrator_loop(
        self,
        orchestrator_key: str,
        prompt: str,
        system_prompt: str,
    ) -> AsyncIterator[HostEvent]:
        """Drive the bidirectional orchestrator routing loop, yielding events.

        Writes an ``orchestrator.execute`` JSON-RPC request to the orchestrator
        process, then processes messages until the final response arrives:

        * ``request.*`` messages are routed via :meth:`_handle_orchestrator_request`
          and the result is written back.
        * ``stream.token`` notifications yield :class:`StreamTokenEvent`.
        * ``stream.thinking`` notifications yield :class:`StreamThinkingEvent`.
        * ``stream.tool_call_start`` notifications yield :class:`StreamToolCallStartEvent`.
        * ``stream.content_block_start`` notifications yield :class:`StreamContentBlockStartEvent`.
        * ``stream.content_block_end`` notifications yield :class:`StreamContentBlockEndEvent`.
        * ``approval_request`` notifications yield :class:`ApprovalRequestEvent`.
        * ``error`` notifications yield :class:`ErrorEvent`.
        * A response whose ``id`` matches the execute request yields :class:`CompleteEvent`.

        Args:
            orchestrator_key: Service key for the orchestrator in ``_services``.
            prompt: User prompt to execute.
            system_prompt: Assembled system prompt for this session.

        Yields:
            :class:`HostEvent` subclass instances produced during execution.

        Raises:
            RuntimeError: If the orchestrator process closes the connection or
                returns a JSON-RPC error response.
        """
        orchestrator_svc: ServiceProcess = self._services[orchestrator_key]
        if (
            orchestrator_svc.process.stdin is None
            or orchestrator_svc.process.stdout is None
        ):
            raise RuntimeError(
                f"Orchestrator service '{orchestrator_key}' was not started with pipes"
            )

        execute_id = uuid.uuid4().hex[:16]

        request: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": execute_id,
            "method": "orchestrator.execute",
            "params": {
                "prompt": prompt,
                "system_prompt": system_prompt,
            },
        }
        await write_message(orchestrator_svc.process.stdin, request)

        # Read loop
        while True:
            message = await read_message(orchestrator_svc.process.stdout)
            if message is None:
                raise RuntimeError("Orchestrator connection closed unexpectedly")

            # Drain provider notification queue and forward to orchestrator
            while not self._provider_notification_queue.empty():
                notification = self._provider_notification_queue.get_nowait()
                await write_message(orchestrator_svc.process.stdin, notification)

            method: str | None = message.get("method")

            # Request from the orchestrator — route it and send back a response
            if method is not None and method.startswith("request."):
                params = message.get("params")
                msg_id = message.get("id")

                try:
                    result = await self._handle_orchestrator_request(method, params)
                    response: dict[str, Any] = {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "result": result,
                    }

                    # Persist context messages
                    if (
                        method == "request.context_add_message"
                        and self._persistence is not None
                        and isinstance(params, dict)
                    ):
                        self._persistence.append_message(params)

                except JsonRpcError as exc:
                    response = exc.to_response(msg_id)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Unexpected error routing %r", method)
                    response = make_error_response(
                        msg_id, -32603, f"Internal error: {exc}"
                    )

                await write_message(orchestrator_svc.process.stdin, response)

            # Stream token notification
            # Tolerate both "token" (canonical) and "text" (legacy orchestrator key)
            elif method == "stream.token":
                params = message.get("params") or {}
                token = params.get("token") or params.get("text", "")
                yield StreamTokenEvent(token=token)

            # Stream thinking notification
            elif method == "stream.thinking":
                thinking = (message.get("params") or {}).get("thinking", "")
                yield StreamThinkingEvent(thinking=thinking)

            # Stream tool call start notification
            elif method == "stream.tool_call_start":
                tool_name = (message.get("params") or {}).get("tool_name", "")
                yield StreamToolCallStartEvent(tool_name=tool_name)

            # Stream content block start notification
            elif method == "stream.content_block_start":
                params = message.get("params") or {}
                block_type = params.get("block_type", "")
                index = params.get("index", 0)
                yield StreamContentBlockStartEvent(block_type=block_type, index=index)

            # Stream content block end notification
            elif method == "stream.content_block_end":
                params = message.get("params") or {}
                block_type = params.get("block_type", "")
                index = params.get("index", 0)
                yield StreamContentBlockEndEvent(block_type=block_type, index=index)

            # Approval request notification
            elif method == "approval_request":
                params = message.get("params") or {}
                yield ApprovalRequestEvent(params=params)

            # Error notification (non-fatal)
            elif method == "error":
                error_message = (message.get("params") or {}).get("message", "")
                yield ErrorEvent(message=error_message)

            # Other stream notifications — log and ignore
            elif method is not None and method.startswith("stream."):
                logger.debug("Unhandled stream notification: %r", method)

            # Final response matching execute_id — success
            elif message.get("id") == execute_id and "result" in message:
                yield CompleteEvent(result=message["result"])
                return

            # Final response matching execute_id — error
            elif message.get("id") == execute_id and "error" in message:
                err = message["error"]
                raise RuntimeError(
                    f"Orchestrator returned error: {err.get('message', err)}"
                )

            else:
                logger.debug("Unrecognised orchestrator message: %r", message)

    # ------------------------------------------------------------------
    # Delegating helper (testable entry point)
    # ------------------------------------------------------------------

    async def _handle_orchestrator_request(self, method: str, params: Any) -> Any:
        """Delegate an orchestrator request to the :class:`Router`.

        This thin wrapper exists to simplify testing — callers can inject a
        pre-built registry and router and call this method directly.

        Args:
            method: The JSON-RPC method string (e.g. ``"request.tool_execute"``).
            params: The JSON-RPC params payload.

        Returns:
            The result returned by the router.

        Raises:
            RuntimeError: If the router has not been initialised yet.
            JsonRpcError: Propagated from the router on routing failure.
        """
        if self._router is None:
            raise RuntimeError("Router has not been initialised")
        return await self._router.route_request(method, params)

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    async def _build_registry(self) -> None:
        """Send ``describe`` to each service and register results in the registry.

        The IPC protocol server wraps capabilities under a ``capabilities`` key
        and represents content as ``{\"paths\": [...]}`` rather than a flat list.
        This method normalises the nested format into the flat dict expected by
        :meth:`~amplifier_ipc_host.registry.CapabilityRegistry.register`.

        Uses a 10-second timeout per service.
        """
        for service_key, service in self._services.items():
            describe_result = await asyncio.wait_for(
                service.client.request("describe"),
                timeout=_DESCRIBE_TIMEOUT_S,
            )
            # The real protocol server nests all capability lists under a
            # "capabilities" key.  Fall back to the raw dict so unit tests
            # that inject pre-flattened dicts continue to work.
            caps = describe_result.get("capabilities", describe_result)

            # "content" may be {"paths": [...]} (nested) or already a list (flat).
            content_field = caps.get("content", [])
            content_paths: list[str] = (
                content_field.get("paths", [])
                if isinstance(content_field, dict)
                else content_field
            )

            flat: dict = {  # type: ignore[type-arg]
                "tools": caps.get("tools", []),
                "hooks": caps.get("hooks", []),
                "orchestrators": caps.get("orchestrators", []),
                "context_managers": caps.get("context_managers", []),
                "providers": caps.get("providers", []),
                "content": content_paths,
            }
            self._registry.register(service_key, flat)

    async def _spawn_services(self) -> None:
        """Spawn all services declared in the session config."""
        for service_name in self._config.services:
            command, working_dir = resolve_service_command(service_name, self._settings)
            service = await spawn_service(service_name, command, working_dir)
            self._services[service_name] = service

    async def _teardown_services(self) -> None:
        """Gracefully shut down all running :class:`ServiceProcess` instances."""
        for service in self._services.values():
            if isinstance(service, ServiceProcess):
                try:
                    await shutdown_service(service)
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "Error shutting down service %r", getattr(service, "name", "?")
                    )
