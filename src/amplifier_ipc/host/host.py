"""Host orchestration — ties config, lifecycle, registry, router, content, and persistence.

The :class:`Host` is the top-level coordinator for an IPC session.  It spawns
service subprocesses, discovers their capabilities, builds a routing table, runs
the orchestrator turn loop, persists the transcript, and tears everything down.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from collections.abc import AsyncIterator, Callable, Coroutine
from pathlib import Path
from typing import Any

from amplifier_ipc.host.config import (
    HostSettings,
    SessionConfig,
    resolve_service_command,
)
from amplifier_ipc.host.content import assemble_system_prompt
from amplifier_ipc.host.mentions import (
    MentionResolverChain,
    WorkingDirResolver,
    parse_mentions,
    resolve_and_load,
)
from amplifier_ipc.host.events import (
    ApprovalRequestEvent,
    ChildSessionEndEvent,
    ChildSessionEvent,
    ChildSessionStartEvent,
    CompleteEvent,
    ErrorEvent,
    HostEvent,
    StreamContentBlockEndEvent,
    StreamContentBlockStartEvent,
    StreamThinkingEvent,
    StreamTokenEvent,
    StreamToolCallStartEvent,
    TodoUpdateEvent,  # noqa: F401  # re-exported for downstream consumers
    ToolCallEvent,  # noqa: F401  # re-exported for downstream consumers
    ToolResultEvent,  # noqa: F401  # re-exported for downstream consumers
)
from amplifier_ipc.host.lifecycle import ServiceProcess, shutdown_service, spawn_service
from amplifier_ipc.host.persistence import SessionPersistence
from amplifier_ipc.host.service_index import ServiceIndex
from amplifier_ipc.host.router import Router
from amplifier_ipc.host.spawner import (
    SpawnRequest,
    _run_child_session,
    generate_child_session_id,
    spawn_child_session,
)
from amplifier_ipc.protocol.errors import (
    METHOD_NOT_FOUND,
    JsonRpcError,
    make_error_response,
)
from amplifier_ipc_protocol.events import (
    CANCEL_COMPLETED,
    CANCEL_REQUESTED,
    CONTEXT_INCLUDE,
    SESSION_END,
    SESSION_FORK,
    SESSION_RESUME,
    SESSION_START,
)
from amplifier_ipc.protocol.framing import read_message, write_message

logger = logging.getLogger(__name__)

_SERVICE_INIT_TIMEOUT_S = 10.0


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
        service_configs: dict[str, Any] | None = None,
        shared_services: dict[str, Any] | None = None,
        shared_registry: ServiceIndex | None = None,
        spawn_depth: int = 0,
        parent_session_id: str | None = None,
        working_dir: Path | None = None,
    ) -> None:
        self._config = config
        self._settings = settings
        self._session_dir = session_dir or (Path.home() / ".amplifier" / "sessions")
        self._working_dir = working_dir
        self._spawn_depth = spawn_depth

        # When shared_services/shared_registry are provided (child sessions), the Host
        # reuses the parent's already-running service processes and service index
        # rather than spawning new ones.  _owns_services tracks whether teardown is
        # the responsibility of this Host instance.
        self._owns_services: bool = shared_services is None

        # Internal state — populated during run()
        self._services: dict[str, Any] = (
            dict(shared_services) if shared_services else {}
        )
        # Per-service merged component configs for the configure protocol.
        # Populated from resolved.service_configs via launch_session().
        self._service_configs: dict[str, Any] = service_configs or {}
        self._registry: ServiceIndex = (
            shared_registry if shared_registry is not None else ServiceIndex()
        )
        self._router: Router | None = None
        self._persistence: SessionPersistence | None = None
        self._state: dict[str, Any] = {}
        self._provider_notification_queue: asyncio.Queue[dict[str, Any]] = (
            asyncio.Queue()
        )
        self._child_event_queue: asyncio.Queue[HostEvent] = asyncio.Queue()
        self._approval_queue: asyncio.Queue[bool] = asyncio.Queue()
        self._session_id: str | None = None
        self._resume_session_id: str | None = None
        self._parent_session_id: str | None = (
            parent_session_id  # consumed by future callers (e.g. session event payloads)
        )
        # MentionResolverChain for sync mention resolution (e.g. WorkingDirResolver).
        # NamespaceResolver is async and must NOT be added here — the chain's
        # resolve() method is synchronous and cannot await async callables.
        self.mention_resolver: MentionResolverChain = MentionResolverChain()
        if working_dir is not None:
            self.mention_resolver.append(WorkingDirResolver(working_dir))

    # ------------------------------------------------------------------
    # Hook event emission (session-level)
    # ------------------------------------------------------------------

    async def _emit_hook_event(self, event_name: str, data: dict[str, Any]) -> None:
        """Emit a hook event through the router.

        No-op when no router is active (e.g. before ``run()`` is called).
        Exceptions from the router are caught and logged so that a failing
        hook never crashes the session.

        Args:
            event_name: The hook event name (e.g. ``"session:start"``).
            data: Arbitrary payload attached to the event.
        """
        if self._router is None:
            return
        try:
            await self._router.route_request(
                "request.hook_emit",
                {"event": event_name, "data": data},
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to emit hook event %r", event_name)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Query methods (REPL introspection — callable between turns)
    # ------------------------------------------------------------------

    def get_tools(self) -> list[dict]:
        """Return list of registered tools with name and description.

        Reads from the in-process :class:`ServiceIndex` populated after
        the last ``run()`` call.  Returns an empty list before the first turn.
        """
        return [
            {
                "name": spec.get("name", ""),
                "description": spec.get("description", ""),
            }
            for spec in self._registry.get_all_tool_specs()
        ]

    def get_session_info(self) -> dict:
        """Return current session info: session_id, orchestrator, message_count, etc."""
        message_count = 0
        if self._persistence is not None:
            try:
                message_count = len(self._persistence.load_transcript())
            except Exception:  # noqa: BLE001
                pass
        return {
            "session_id": self._session_id,
            "orchestrator": self._config.orchestrator,
            "provider": self._config.provider,
            "context_manager": self._config.context_manager,
            "services": list(self._config.services),
            "message_count": message_count,
            "active_mode": self.get_active_mode(),
        }

    def get_agents(self) -> list[dict]:
        """Return list of available agents from the definition registry.

        Reads ``$AMPLIFIER_HOME/agents.yaml``.  Returns an empty list if the
        file does not exist or cannot be read.
        """
        try:
            import yaml  # noqa: PLC0415

            from amplifier_ipc.host.definition_registry import (  # noqa: PLC0415
                Registry,
            )

            reg = Registry()
            agents_path = reg.home / "agents.yaml"
            if not agents_path.exists():
                return []
            raw = yaml.safe_load(agents_path.read_text(encoding="utf-8")) or {}
            return [
                {"name": name, "definition_id": def_id}
                for name, def_id in raw.items()
                if isinstance(name, str)
            ]
        except Exception:  # noqa: BLE001
            return []

    def get_active_mode(self) -> str | None:
        """Return name of active mode, if any, from session state."""
        active = self._state.get("active_mode")
        return str(active) if active is not None else None

    def get_available_modes(self) -> list[dict]:
        """Return list of available modes.

        Checks session state (populated by a modes service) first, then falls
        back to the ``modes.available`` key in component_config.
        """
        # 1. Session state — populated at runtime by the modes service
        state_modes: list[Any] = self._state.get("available_modes", [])  # type: ignore[assignment]
        if state_modes:
            return [{"name": m} if isinstance(m, str) else dict(m) for m in state_modes]
        # 2. Static component config
        modes_cfg = self._config.component_config.get("modes", {})
        if isinstance(modes_cfg, dict):
            cfg_modes: list[Any] = modes_cfg.get("available", [])
            if cfg_modes:
                return [
                    {"name": m} if isinstance(m, str) else dict(m) for m in cfg_modes
                ]
        return []

    async def clear_context(self) -> None:
        """Clear conversation context via the context manager service.

        If a :class:`Router` is active, sends ``request.context_clear`` to the
        context manager.  Also removes the persisted transcript so that the
        next ``run()`` call starts with a fresh context.
        """
        if self._router is not None:
            try:
                await self._router.route_request("request.context_clear", {})
            except Exception:  # noqa: BLE001
                logger.warning("Failed to clear context via router")
        if self._persistence is not None:
            try:
                if self._persistence.transcript_path.exists():
                    self._persistence.transcript_path.unlink()
            except Exception:  # noqa: BLE001
                logger.warning("Failed to remove persisted transcript")

    async def set_mode(self, mode_name: str | None) -> dict:
        """Set or clear the active mode.

        Persists the value via ``request.state_set`` when a router is
        available; otherwise writes directly to the in-process state dict.

        Args:
            mode_name: Mode to activate, or ``None`` to clear the active mode.

        Returns:
            ``{"ok": True}`` on success.
        """
        if self._router is not None:
            try:
                result = await self._router.route_request(
                    "request.state_set",
                    {"key": "active_mode", "value": mode_name},
                )
                return result if isinstance(result, dict) else {"ok": True}
            except Exception:  # noqa: BLE001
                pass
        # Fallback: update in-process state directly
        self._state["active_mode"] = mode_name
        if self._persistence is not None:
            self._persistence.save_state(self._state)
        return {"ok": True, "mode": mode_name}

    def get_config_summary(self) -> dict:
        """Return resolved config summary (orchestrator, provider, tools, hooks).

        Useful for displaying the active configuration in the REPL without
        triggering any IPC calls.
        """
        tools = [s.get("name", "") for s in self._registry.get_all_tool_specs()]
        hooks = [h.get("name", "") for h in self._registry.get_all_hook_descriptors()]
        return {
            "orchestrator": self._config.orchestrator,
            "context_manager": self._config.context_manager,
            "provider": self._config.provider,
            "services": list(self._config.services),
            "tools": tools,
            "hooks": hooks,
            "component_config": dict(self._config.component_config),
        }

    @property
    def session_id(self) -> str | None:
        """Return the session ID from the most recent ``run()`` call, or ``None``."""
        return self._session_id

    def send_approval(self, approved: bool) -> None:
        """Submit an approval decision to unblock the orchestrator loop.

        Called by the CLI when an :class:`~amplifier_ipc.host.events.ApprovalRequestEvent`
        is received.  The orchestrator loop awaits this value after yielding
        the event, so calling this method unblocks it.

        Args:
            approved: ``True`` to approve the pending action, ``False`` to deny.
        """
        self._approval_queue.put_nowait(approved)

    def set_resume_session_id(self, session_id: str) -> None:
        """Set the session ID to resume when running this session.

        Call this after :func:`~amplifier_ipc.cli.session_launcher.launch_session`
        to indicate that the session should continue from an existing session.

        Args:
            session_id: The ID of the session to resume.
        """
        self._resume_session_id = session_id

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
        # Generate session ID and persistence on the first call only so that
        # the transcript accumulates across turns and can be replayed into the
        # (freshly spawned) context manager at the start of each subsequent turn.
        if self._session_id is None:
            self._session_id = str(uuid.uuid4())
        if self._persistence is None:
            self._persistence = SessionPersistence(self._session_id, self._session_dir)

        session_id = self._session_id
        assert self._persistence is not None

        _session_status = "completed"
        try:
            # 1b. Load shared state from persistence
            self._state = self._persistence.load_state()

            # 2. Spawn services (skipped for child sessions that share parent's processes)
            if self._owns_services:
                await self._spawn_services()

            # 3. Build registry (skipped for child sessions that share parent's registry)
            if self._owns_services:
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

            _handle_spawn = self._build_spawn_handler(session_id, self._spawn_depth)
            _handle_resume = self._build_resume_handler(session_id)

            self._router = Router(
                registry=self._registry,
                services=self._services,
                context_manager_key=context_manager_key,
                provider_key=provider_key,
                provider_name=self._config.provider or None,
                state=self._state,
                on_provider_notification=_queue_provider_notification,
                spawn_handler=_handle_spawn,
                resume_handler=_handle_resume,
            )

            # 5a. Emit session:start or session:resume hook event
            _lifecycle_event = (
                SESSION_RESUME if self._resume_session_id is not None else SESSION_START
            )
            await self._emit_hook_event(
                _lifecycle_event,
                {
                    "session_id": self._session_id,
                    "parent_id": self._parent_session_id,
                    "raw": self._config.model_dump(),
                },
            )

            # 5b. Resume session: restore previous transcript if resuming
            if self._resume_session_id is not None:
                session_id = await self._restore_from_session()
                self._session_id = session_id
                self._resume_session_id = None  # consumed — don't replay again
            else:
                # Replay existing transcript into the freshly-spawned context
                # manager so that conversation history survives across turns.
                existing_transcript = self._persistence.load_transcript()
                for message_params in existing_transcript:
                    await self._router.route_request(
                        "request.context_add_message",
                        message_params,
                    )

            # 6. Assemble system prompt
            system_prompt = await assemble_system_prompt(
                self._registry, self._services, resolver_chain=self.mention_resolver
            )

            # 6a. Append working directory context (AGENTS.md + .amplifier/*.md)
            working_dir_content = await self._load_working_dir_content()
            if working_dir_content:
                system_prompt = system_prompt + "\n" + working_dir_content

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
            existing_meta: dict[str, Any] = {}
            try:
                existing_meta = json.loads(self._persistence.metadata_path.read_text())
            except Exception:  # noqa: BLE001
                pass
            existing_meta.update({"session_id": session_id, "prompt": prompt})
            self._persistence.save_metadata(existing_meta)
            self._persistence.finalize()

        except asyncio.CancelledError:
            _session_status = "cancelled"
            await self._emit_hook_event(
                CANCEL_REQUESTED,
                {"session_id": self._session_id, "was_immediate": False},
            )
            await self._emit_hook_event(
                CANCEL_COMPLETED,
                {"session_id": self._session_id, "was_immediate": False},
            )
            raise
        except Exception:
            _session_status = "failed"
            raise
        finally:
            await self._emit_hook_event(
                SESSION_END,
                {"session_id": self._session_id, "status": _session_status},
            )
            await self._teardown_services()

    # ------------------------------------------------------------------
    # Spawn handler factory
    # ------------------------------------------------------------------

    def _build_spawn_handler(
        self, session_id: str, current_depth: int = 0
    ) -> Callable[[Any], Coroutine[Any, Any, Any]]:
        """Build and return the async ``_handle_spawn`` closure for *session_id*.

        The returned coroutine function handles ``request.session_spawn`` by
        building a ``parent_config`` dict populated from the host's resolved
        configuration and service index, then delegating to
        :func:`~amplifier_ipc.host.spawner.spawn_child_session`.

        Extracting this into a factory method makes the spawn logic directly
        testable without running the full :meth:`run` lifecycle.

        Args:
            session_id: The current session's ID (captured in the closure).

        Returns:
            An async callable ``(params: Any) -> Any`` suitable for passing
            as the ``spawn_handler`` argument to :class:`~amplifier_ipc.host.router.Router`.
        """

        async def _handle_spawn(params: Any) -> Any:
            """Handle request.session_spawn from the orchestrator."""
            p = params if isinstance(params, dict) else {}
            agent_name = p.get("agent", "self")
            instruction = p.get("instruction", "")
            agent_base = self._resolve_agent_base(agent_name)
            if agent_base:
                instruction = agent_base + "\n\n" + instruction
            spawn_request = SpawnRequest(
                agent=agent_name,
                instruction=instruction,
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
            child_session_id = generate_child_session_id(session_id, agent_name)

            await self._emit_hook_event(
                SESSION_FORK,
                {
                    "session_id": child_session_id,
                    "parent_id": session_id,
                    "agent": agent_name,
                },
            )

            def _forward_child_event(event: HostEvent) -> None:
                """Wrap a child event and enqueue it for the orchestrator loop."""
                # depth is always 1 here; nested grandchild events arrive already
                # wrapped (e.g. ChildSessionEvent(depth=2)) and will be re-wrapped
                # as ChildSessionEvent(depth=1, inner=ChildSessionEvent(depth=2, ...))
                # rather than being promoted.  Depth promotion is not in scope at
                # this layer.
                self._child_event_queue.put_nowait(
                    ChildSessionEvent(depth=1, inner=event)
                )

            transcript = (
                self._persistence.load_transcript() if self._persistence else []
            )
            parent_config: dict[str, Any] = {
                "services": list(self._config.services),
                "orchestrator": self._config.orchestrator,
                "context_manager": self._config.context_manager,
                "provider": self._config.provider,
                "component_config": dict(self._config.component_config),
                "tools": self._registry.get_all_tool_specs(),
                "hooks": self._registry.get_all_hook_descriptors(),
            }
            try:
                self._child_event_queue.put_nowait(
                    ChildSessionStartEvent(
                        agent_name=agent_name,
                        session_id=child_session_id,
                    )
                )
                return await spawn_child_session(
                    parent_session_id=session_id,
                    parent_config=parent_config,
                    transcript=transcript,
                    request=spawn_request,
                    settings=self._settings,
                    service_configs=self._service_configs,
                    event_callback=_forward_child_event,
                    current_depth=current_depth,
                    child_session_id=child_session_id,
                )
            finally:
                self._child_event_queue.put_nowait(
                    ChildSessionEndEvent(session_id=child_session_id)
                )

        return _handle_spawn

    def _build_resume_handler(self, session_id: str) -> Any:
        """Build and return the async ``_handle_resume`` closure for *session_id*.

        The returned coroutine function handles ``request.session_resume`` by
        loading the child session's transcript, prepending it as context lines
        in ``role: content`` format, and delegating to
        :func:`~amplifier_ipc.host.spawner._run_child_session`.

        Extracting this into a factory method makes the resume logic directly
        testable without running the full :meth:`run` lifecycle.

        Args:
            session_id: The current (parent) session's ID (captured in closure).

        Returns:
            An async callable ``(params: Any) -> Any`` suitable for passing
            as the ``resume_handler`` argument to :class:`~amplifier_ipc.host.router.Router`.
        """

        async def _handle_resume(params: Any) -> Any:
            """Handle request.session_resume from the orchestrator."""
            p = params if isinstance(params, dict) else {}

            # 1. Extract session_id and instruction from params
            child_session_id: str = p.get("session_id", "")
            instruction: str = p.get("instruction", "")

            await self._emit_hook_event(
                SESSION_RESUME,
                {
                    "session_id": child_session_id,
                    "parent_id": session_id,
                },
            )

            # 2. Create SessionPersistence for the child session
            child_persistence = SessionPersistence(child_session_id, self._session_dir)

            # 3. Load the child session's transcript
            child_transcript = child_persistence.load_transcript()

            # 4. Build child_config from parent config
            child_config: dict[str, Any] = {
                "services": list(self._config.services),
                "orchestrator": self._config.orchestrator,
                "context_manager": self._config.context_manager,
                "provider": self._config.provider,
                "component_config": dict(self._config.component_config),
                "tools": self._registry.get_all_tool_specs(),
                "hooks": self._registry.get_all_hook_descriptors(),
            }

            # 5. Prepend previous transcript as context lines (role: content format)
            context_lines = "\n".join(
                f"{msg.get('role', 'unknown')}: {msg.get('content', '')}"
                for msg in child_transcript
            )

            # 6. Build the full instruction (context + new instruction)
            if context_lines:
                full_instruction = f"{context_lines}\n\n{instruction}"
            else:
                full_instruction = instruction

            # Build a minimal SpawnRequest for the child session run
            spawn_request = SpawnRequest(
                agent="self",
                instruction=full_instruction,
            )

            return await _run_child_session(
                child_session_id=child_session_id,
                child_config=child_config,
                instruction=full_instruction,
                request=spawn_request,
                settings=self._settings,
                session_dir=self._session_dir,
                service_configs=self._service_configs,
            )

        return _handle_resume

    # ------------------------------------------------------------------
    # Agent base resolution
    # ------------------------------------------------------------------

    def _resolve_agent_base(self, agent_name: str) -> str:
        """Resolve base context content for an agent from its definition.

        Looks up the agent definition, checks for a ``base`` field, resolves the
        base mention via :attr:`mention_resolver`, and recursively resolves any
        nested ``@mention`` references found inside the base content.

        Args:
            agent_name: The agent ref alias.  Returns ``""`` immediately for
                ``"self"`` since self-spawns inherit the parent's context.

        Returns:
            Combined content string (base + nested), joined with ``"\\n\\n"``,
            or ``""`` when *agent_name* is ``"self"``, when no ``base`` field is
            defined, or when any exception occurs (with a warning log).
        """
        if agent_name == "self":
            return ""
        try:
            from amplifier_ipc.host.definition_registry import (  # noqa: PLC0415
                Registry,
            )
            from amplifier_ipc.host.definitions import (  # noqa: PLC0415
                parse_agent_definition,
            )

            reg = Registry()
            agent_path = reg.resolve_agent(agent_name)
            yaml_content = agent_path.read_text(encoding="utf-8")
            agent_def = parse_agent_definition(yaml_content)

            if not agent_def.base:
                return ""

            base_content = self.mention_resolver.resolve(f"@{agent_def.base}")
            if not base_content:
                return ""

            # Recursively resolve nested @mentions found in the base content
            nested = resolve_and_load(base_content, self.mention_resolver)
            parts = [base_content] + [r.content for r in nested]
            return "\n\n".join(parts)
        except Exception:  # noqa: BLE001
            logger.warning(
                "_resolve_agent_base: failed to resolve base for agent %r",
                agent_name,
            )
            return ""

    # ------------------------------------------------------------------
    # Session resume helper
    # ------------------------------------------------------------------

    async def _restore_from_session(self) -> str:
        """Restore transcript from the resume session for continuation.

        Called from :meth:`run` when ``_resume_session_id`` is set, after the
        router is built.  Loads the previous session's transcript, replays all
        messages into the context manager, and updates :attr:`_persistence` and
        :attr:`_state` so that new writes continue into the previous session
        directory.

        Returns:
            The ``_resume_session_id`` to use as the active session ID going
            forward.

        Raises:
            RuntimeError: If the router has not been initialised yet.
        """
        if self._router is None:
            raise RuntimeError("Router has not been initialised")

        assert self._resume_session_id is not None  # guard — callers check this

        prev_persistence = SessionPersistence(
            self._resume_session_id, self._session_dir
        )
        prev_transcript = prev_persistence.load_transcript()

        for message_params in prev_transcript:
            await self._router.route_request(
                "request.context_add_message",
                message_params,
            )

        # Reuse the previous session ID and its persistence/state
        self._persistence = prev_persistence
        self._state = prev_persistence.load_state()

        return self._resume_session_id

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
                "config": {
                    "tools": self._registry.get_all_tool_specs(),
                    "hooks": self._registry.get_all_hook_descriptors(),
                    "provider_name": self._config.provider or "unknown",
                },
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

            # Drain child event queue and yield events to the caller
            while not self._child_event_queue.empty():
                yield self._child_event_queue.get_nowait()

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

            # Tool call notification
            elif method == "stream.tool_call":
                params = message.get("params") or {}
                yield ToolCallEvent(
                    tool_name=params.get("tool_name", ""),
                    arguments=params.get("arguments", {}),
                )

            # Tool result notification
            elif method == "stream.tool_result":
                params = message.get("params") or {}
                yield ToolResultEvent(
                    tool_name=params.get("tool_name", ""),
                    success=params.get("success", True),
                    output=params.get("output", ""),
                )

            # Context message persistence — the _OrchestratorLocalClient
            # handles context_add_message locally (same-process) and then
            # sends this notification so the host can persist the message
            # to the session transcript for cross-turn replay.
            elif method == "stream.context_message_added":
                params = message.get("params") or {}
                if self._persistence is not None and isinstance(params, dict):
                    self._persistence.append_message(params)

            # Todo update notification
            elif method == "stream.todo_update":
                params = message.get("params") or {}
                yield TodoUpdateEvent(
                    todos=params.get("todos", []),
                    status=params.get("status", ""),
                )

            # Approval request notification — yield event, then wait for the
            # CLI to call send_approval() before continuing the loop.
            elif method == "approval_request":
                params = message.get("params") or {}
                yield ApprovalRequestEvent(params=params)
                await self._approval_queue.get()

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
        if method == "request.tool_execute":
            params = self._preprocess_tool_mentions(params)
        return await self._router.route_request(method, params)

    # ------------------------------------------------------------------
    # Tool input pre-processing
    # ------------------------------------------------------------------

    def _preprocess_tool_mentions(self, params: Any) -> Any:
        """Pre-process tool execution params by resolving @mentions in string arguments.

        Scans each string argument value for ``@mention`` patterns and resolves
        them via the :attr:`mention_resolver` chain.  Non-string argument values
        are left untouched.  Unresolved mentions remain in the string unchanged
        (logged at debug).  Per-mention exceptions are caught and logged at
        warning level so a single failing resolution never corrupts the whole
        call.

        Args:
            params: The JSON-RPC params payload from the orchestrator.

        Returns:
            A shallow copy of *params* with the ``arguments`` dict updated when
            at least one mention was resolved, or the original *params* object
            unchanged when no mentions were resolved or the input is not in the
            expected format.
        """
        if not isinstance(params, dict):
            return params

        arguments = params.get("arguments")
        if not isinstance(arguments, dict):
            return params

        new_args = dict(arguments)
        changed = False

        for key, value in arguments.items():
            if not isinstance(value, str):
                continue

            mentions = parse_mentions(value)
            if not mentions:
                continue

            new_value = value
            for mention in mentions:
                try:
                    resolved = self.mention_resolver.resolve(mention)
                    if resolved is None:
                        logger.debug(
                            "_preprocess_tool_mentions: unresolved mention %r in arg %r",
                            mention,
                            key,
                        )
                    else:
                        new_value = new_value.replace(mention, resolved)
                        changed = True
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "_preprocess_tool_mentions: error resolving mention %r in arg %r",
                        mention,
                        key,
                    )

            if new_value != value:
                new_args[key] = new_value

        if not changed:
            return params

        return {**params, "arguments": new_args}

    # ------------------------------------------------------------------
    # Working directory content loading
    # ------------------------------------------------------------------

    async def _load_working_dir_content(self) -> str:
        """Scan working directory for AGENTS.md and .amplifier/*.md files.

        Collects:

        * Root ``AGENTS.md`` (if present)
        * All ``*.md`` files under ``.amplifier/`` (sorted)

        For each file the content is deduplicated by SHA-256 hash, wrapped in
        ``<context_file path="...">`` XML, and any ``@mention`` references
        inside the file are recursively resolved via :func:`resolve_and_load`.
        All files in a single call share the same ``seen_hashes`` set so
        identical content is never included twice.

        Returns:
            Combined context string, or ``""`` if :attr:`_working_dir` is
            ``None`` or no matching files were found.
        """
        import hashlib

        if self._working_dir is None:
            return ""

        # Collect candidate files
        files: list[Path] = []
        agents_md = self._working_dir / "AGENTS.md"
        if agents_md.exists():
            files.append(agents_md)

        amplifier_dir = self._working_dir / ".amplifier"
        if amplifier_dir.is_dir():
            files.extend(sorted(amplifier_dir.glob("*.md")))

        if not files:
            return ""

        seen_hashes: set[str] = set()
        parts: list[str] = []

        for file_path in files:
            try:
                text = file_path.read_text(encoding="utf-8")
            except OSError:
                logger.warning(
                    "_load_working_dir_content: could not read %r", str(file_path)
                )
                continue

            content_hash = hashlib.sha256(text.encode()).hexdigest()
            if content_hash in seen_hashes:
                continue
            seen_hashes.add(content_hash)

            rel_path = file_path.relative_to(self._working_dir)
            parts.append(f'<context_file path="{rel_path}">\n{text}\n</context_file>')
            await self._emit_hook_event(
                CONTEXT_INCLUDE, {"path": str(rel_path), "source": "file"}
            )

            # Resolve @mentions found in the file (shared dedup via seen_hashes)
            included_mentions: list[str] = []
            nested = resolve_and_load(
                text,
                self.mention_resolver,
                seen_hashes=seen_hashes,
                on_include=included_mentions.append,
            )
            for resolved in nested:
                parts.append(
                    f'<context_file path="{resolved.key}">\n{resolved.content}\n</context_file>'
                )
            for mention_key in included_mentions:
                await self._emit_hook_event(
                    CONTEXT_INCLUDE, {"path": mention_key, "source": "mention"}
                )

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    async def _build_registry(self) -> None:
        """Send ``describe`` to each service and register results in the registry.

        The IPC protocol server wraps capabilities under a ``capabilities`` key
        and represents content as ``{\"paths\": [...]}`` rather than a flat list.
        This method normalises the nested format into the flat dict expected by
        :meth:`~amplifier_ipc.host.service_index.ServiceIndex.register`.

        If the service has a merged config in ``_service_configs``, a
        ``configure`` call is sent after registration.

        Uses a 10-second timeout per service for both ``describe`` and
        ``configure`` calls.
        """
        for service_key, service in self._services.items():
            describe_result = await asyncio.wait_for(
                service.client.request("describe"),
                timeout=_SERVICE_INIT_TIMEOUT_S,
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

            # Send configure with merged config for this service (if any).
            # If the service does not support configure (METHOD_NOT_FOUND), log
            # a warning and continue — this preserves compatibility with older
            # service installations that pre-date the configure protocol.
            service_config = self._service_configs.get(service_key, {})
            if service_config:
                try:
                    await asyncio.wait_for(
                        service.client.request("configure", {"config": service_config}),
                        timeout=_SERVICE_INIT_TIMEOUT_S,
                    )
                except JsonRpcError as exc:
                    if exc.code == METHOD_NOT_FOUND:
                        logger.warning(
                            "Service '%s' does not support configure; "
                            "skipping (update amplifier-ipc in the service venv "
                            "to enable per-service configuration).",
                            service_key,
                        )
                    else:
                        raise

    async def _spawn_services(self) -> None:
        """Spawn all services declared in the session config.

        No-op when this Host was constructed with ``shared_services`` — the
        parent session already owns and manages those processes.
        """
        if not self._owns_services:
            return
        for service_name in self._config.services:
            command, working_dir = resolve_service_command(service_name, self._settings)
            service = await spawn_service(service_name, command, working_dir)
            self._services[service_name] = service

    async def _teardown_services(self) -> None:
        """Gracefully shut down all running :class:`ServiceProcess` instances.

        Skipped when this Host was constructed with ``shared_services`` — the
        parent session that owns those processes is responsible for teardown.
        """
        if not self._owns_services:
            return
        for service in self._services.values():
            if isinstance(service, ServiceProcess):
                try:
                    await shutdown_service(service)
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "Error shutting down service %r", getattr(service, "name", "?")
                    )
