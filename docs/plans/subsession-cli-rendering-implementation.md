# Sub-Session CLI Rendering Implementation Plan

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Make child session activity visible in the CLI by forwarding child events through the parent's event stream and rendering tool calls, tool results, thinking blocks, todo updates, and child session nesting with proper formatting.

**Architecture:** Three layers modified bottom-up: (1) new event types + event forwarding infrastructure in the host, (2) orchestrator notifications for tool calls/results/todos, mapped to events in the host loop, (3) Rich CLI rendering for all new event types with nesting indentation. Child events flow via an `asyncio.Queue` on the parent Host, drained in the `_orchestrator_loop` alongside normal message processing.

**Tech Stack:** Python 3.12+, Pydantic BaseModel, asyncio, Rich (console rendering), pytest (asyncio_mode=auto)

---

## Layer 1: Host Event Types + Event Forwarding

### Task 1: Add new event types to events.py

**Files:**
- Modify: `src/amplifier_ipc/host/events.py`
- Modify: `tests/host/test_events.py`

**Step 1: Write the failing tests**

Add these tests to `tests/host/test_events.py`. Follow the exact pattern of the existing tests in that file (each test is a standalone function, asserts `isinstance(event, HostEvent)` and checks fields):

```python
# Add these imports at the top (extend the existing import block):
# ToolCallEvent, ToolResultEvent, TodoUpdateEvent,
# ChildSessionStartEvent, ChildSessionEndEvent, ChildSessionEvent

def test_tool_call_event() -> None:
    """ToolCallEvent holds tool_name and arguments dict."""
    event = ToolCallEvent(tool_name="bash", arguments={"command": "ls"})
    assert isinstance(event, HostEvent)
    assert event.tool_name == "bash"
    assert event.arguments == {"command": "ls"}


def test_tool_call_event_defaults() -> None:
    """ToolCallEvent fields have sensible defaults."""
    event = ToolCallEvent()
    assert event.tool_name == ""
    assert event.arguments == {}


def test_tool_result_event() -> None:
    """ToolResultEvent holds tool_name, success, and output."""
    event = ToolResultEvent(tool_name="bash", success=True, output="hello world")
    assert isinstance(event, HostEvent)
    assert event.tool_name == "bash"
    assert event.success is True
    assert event.output == "hello world"


def test_tool_result_event_failure() -> None:
    """ToolResultEvent can represent a failed tool call."""
    event = ToolResultEvent(tool_name="bash", success=False, output="command not found")
    assert event.success is False


def test_todo_update_event() -> None:
    """TodoUpdateEvent holds todos list and status string."""
    todos = [{"content": "Fix bug", "status": "completed", "activeForm": "Fixing bug"}]
    event = TodoUpdateEvent(todos=todos, status="updated")
    assert isinstance(event, HostEvent)
    assert event.todos == todos
    assert event.status == "updated"


def test_child_session_start_event() -> None:
    """ChildSessionStartEvent holds agent_name, session_id, and depth."""
    event = ChildSessionStartEvent(agent_name="explorer", session_id="abc123", depth=1)
    assert isinstance(event, HostEvent)
    assert event.agent_name == "explorer"
    assert event.session_id == "abc123"
    assert event.depth == 1


def test_child_session_end_event() -> None:
    """ChildSessionEndEvent holds session_id and depth."""
    event = ChildSessionEndEvent(session_id="abc123", depth=1)
    assert isinstance(event, HostEvent)
    assert event.session_id == "abc123"
    assert event.depth == 1


def test_child_session_event() -> None:
    """ChildSessionEvent wraps an inner HostEvent with a nesting depth."""
    inner = StreamTokenEvent(token="hello")
    event = ChildSessionEvent(depth=1, inner=inner)
    assert isinstance(event, HostEvent)
    assert event.depth == 1
    assert event.inner is inner
    assert isinstance(event.inner, StreamTokenEvent)


def test_child_session_event_nested() -> None:
    """ChildSessionEvent can nest another ChildSessionEvent for recursive depth."""
    inner_inner = ToolCallEvent(tool_name="bash", arguments={"command": "ls"})
    inner = ChildSessionEvent(depth=1, inner=inner_inner)
    outer = ChildSessionEvent(depth=2, inner=inner)
    assert outer.depth == 2
    assert isinstance(outer.inner, ChildSessionEvent)
    assert outer.inner.inner.tool_name == "bash"
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/host/test_events.py -v
```

Expected: Multiple FAIL with `ImportError` — the new event classes don't exist yet.

**Step 3: Write the implementation**

Add these classes to `src/amplifier_ipc/host/events.py`, after the existing `CompleteEvent` class. Note: `ChildSessionEvent` needs `model_config` because `inner` holds an arbitrary `HostEvent` subclass:

```python
from pydantic import BaseModel, ConfigDict, Field  # update existing import to add ConfigDict


class ToolCallEvent(HostEvent):
    """Emitted when a tool call starts, with full arguments for display."""

    tool_name: str = ""
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResultEvent(HostEvent):
    """Emitted when a tool call completes with its output."""

    tool_name: str = ""
    success: bool = True
    output: str = ""


class TodoUpdateEvent(HostEvent):
    """Emitted when the todo list changes."""

    todos: list[dict[str, Any]] = Field(default_factory=list)
    status: str = ""


class ChildSessionStartEvent(HostEvent):
    """Emitted when a child session begins."""

    agent_name: str = ""
    session_id: str = ""
    depth: int = 1


class ChildSessionEndEvent(HostEvent):
    """Emitted when a child session completes."""

    session_id: str = ""
    depth: int = 1


class ChildSessionEvent(HostEvent):
    """Wraps any event from a child session with nesting depth."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    depth: int = 1
    inner: HostEvent | None = None
```

**Step 4: Update the `__init__.py` re-exports**

In `src/amplifier_ipc/host/__init__.py`, add the new event types to both the import block and `__all__`:

Add to the `from amplifier_ipc.host.events import (` block:
```python
    ChildSessionEndEvent,
    ChildSessionEvent,
    ChildSessionStartEvent,
    TodoUpdateEvent,
    ToolCallEvent,
    ToolResultEvent,
```

Add to `__all__` in the Events section:
```python
    "ToolCallEvent",
    "ToolResultEvent",
    "TodoUpdateEvent",
    "ChildSessionStartEvent",
    "ChildSessionEndEvent",
    "ChildSessionEvent",
```

**Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/host/test_events.py -v
```

Expected: All tests PASS.

**Step 6: Commit**

```bash
git add src/amplifier_ipc/host/events.py src/amplifier_ipc/host/__init__.py tests/host/test_events.py
git commit -m "feat: add ToolCallEvent, ToolResultEvent, TodoUpdateEvent, ChildSession*Event types"
```

---

### Task 2: Add event_callback to spawner

**Files:**
- Modify: `src/amplifier_ipc/host/spawner.py`
- Modify: `tests/host/test_spawner.py`
- Modify: `tests/host/test_spawn_integration.py`

**Step 1: Write the failing tests**

Add these tests to `tests/host/test_spawner.py`. The test verifies that `_run_child_session` calls the callback for every event from the child Host:

```python
# Add to tests/host/test_spawner.py

async def test_run_child_session_calls_event_callback() -> None:
    """_run_child_session invokes event_callback for every event from child Host."""
    from amplifier_ipc.host.events import CompleteEvent, StreamTokenEvent

    received_events: list = []

    def callback(event):
        received_events.append(event)

    async def mock_run(prompt: str):
        yield StreamTokenEvent(token="Hello ")
        yield StreamTokenEvent(token="World")
        yield CompleteEvent(result="Hello World")

    with patch("amplifier_ipc.host.host.Host") as MockHost:
        mock_instance = MagicMock()
        MockHost.return_value = mock_instance
        mock_instance.run = mock_run

        await _run_child_session(
            child_session_id="child-cb",
            child_config={
                "services": [],
                "orchestrator": "",
                "context_manager": "",
                "provider": "",
            },
            instruction="go",
            request=SpawnRequest(agent="self", instruction="go"),
            event_callback=callback,
        )

    # Should have received all 3 events
    assert len(received_events) == 3
    assert isinstance(received_events[0], StreamTokenEvent)
    assert received_events[0].token == "Hello "
    assert isinstance(received_events[1], StreamTokenEvent)
    assert isinstance(received_events[2], CompleteEvent)


async def test_run_child_session_no_callback_still_works() -> None:
    """_run_child_session works fine without event_callback (backward compat)."""
    from amplifier_ipc.host.events import CompleteEvent

    async def mock_run(prompt: str):
        yield CompleteEvent(result="done")

    with patch("amplifier_ipc.host.host.Host") as MockHost:
        mock_instance = MagicMock()
        MockHost.return_value = mock_instance
        mock_instance.run = mock_run

        result = await _run_child_session(
            child_session_id="child-nocb",
            child_config={
                "services": [],
                "orchestrator": "",
                "context_manager": "",
                "provider": "",
            },
            instruction="go",
            request=SpawnRequest(agent="self", instruction="go"),
            # No event_callback — should not raise
        )

    assert result["response"] == "done"


async def test_spawn_child_session_forwards_event_callback() -> None:
    """spawn_child_session passes event_callback through to _run_child_session."""
    callback = MagicMock()

    with patch(
        "amplifier_ipc.host.spawner._run_child_session", new_callable=AsyncMock
    ) as mock_run:
        mock_run.return_value = {
            "session_id": "child-123",
            "response": "result",
            "turn_count": 1,
            "metadata": {},
        }
        await spawn_child_session(
            parent_session_id="parent-123",
            parent_config={"tools": []},
            transcript=[],
            request=SpawnRequest(agent="self", instruction="Do something"),
            current_depth=0,
            event_callback=callback,
        )

    assert mock_run.called
    _, kwargs = mock_run.call_args
    assert kwargs.get("event_callback") is callback
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/host/test_spawner.py::test_run_child_session_calls_event_callback tests/host/test_spawner.py::test_run_child_session_no_callback_still_works tests/host/test_spawner.py::test_spawn_child_session_forwards_event_callback -v
```

Expected: FAIL — `event_callback` parameter doesn't exist yet.

**Step 3: Write the implementation**

Modify `_run_child_session` in `src/amplifier_ipc/host/spawner.py` to accept and use `event_callback`:

In the function signature of `_run_child_session` (line ~306), add the parameter after `shared_registry`:
```python
async def _run_child_session(
    child_session_id: str,
    child_config: dict[str, Any],
    instruction: str,
    request: SpawnRequest,
    settings: Any | None = None,
    session_dir: Any | None = None,
    service_configs: dict[str, Any] | None = None,
    shared_services: dict[str, Any] | None = None,
    shared_registry: Any | None = None,
    event_callback: Any | None = None,
) -> dict[str, Any]:
```

In the event iteration loop (line ~385), add the callback invocation:
```python
    # 4. Run the host, iterating async events, collecting CompleteEvent response
    response = ""
    turn_count = 0
    async for event in host.run(instruction):
        if event_callback is not None:
            event_callback(event)
        if isinstance(event, CompleteEvent):
            response = event.result
            turn_count += 1
```

Modify `spawn_child_session` signature (line ~404) to accept and forward the callback:
```python
async def spawn_child_session(
    parent_session_id: str,
    parent_config: dict[str, Any],
    transcript: list[dict[str, Any]],
    request: SpawnRequest,
    current_depth: int = 0,
    settings: Any | None = None,
    service_configs: dict[str, Any] | None = None,
    shared_services: dict[str, Any] | None = None,
    shared_registry: Any | None = None,
    event_callback: Any | None = None,
) -> Any:
```

And at the bottom of `spawn_child_session` where it calls `_run_child_session` (line ~487), add the keyword argument:
```python
    return await _run_child_session(
        child_session_id,
        child_config,
        instruction,
        request,
        settings=settings,
        service_configs=service_configs,
        shared_services=shared_services,
        shared_registry=shared_registry,
        event_callback=event_callback,
    )
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/host/test_spawner.py -v
uv run pytest tests/host/test_spawn_integration.py -v
```

Expected: All PASS (existing tests still work, new tests pass).

**Step 5: Commit**

```bash
git add src/amplifier_ipc/host/spawner.py tests/host/test_spawner.py
git commit -m "feat: add event_callback parameter to _run_child_session and spawn_child_session"
```

---

### Task 3: Wire event forwarding in host.py

**Files:**
- Modify: `src/amplifier_ipc/host/host.py`
- Modify: `tests/host/test_host.py`

**Step 1: Write the failing tests**

Add to `tests/host/test_host.py`. These tests verify:
(a) The child event queue is drained in the orchestrator loop.
(b) The spawn handler provides a callback that queues `ChildSessionEvent` wrappers.

```python
# Add these imports to the existing import block at the top of tests/host/test_host.py:
# from amplifier_ipc.host.events import ChildSessionEvent, ChildSessionStartEvent, ChildSessionEndEvent

async def test_orchestrator_loop_drains_child_event_queue() -> None:
    """Events placed on _child_event_queue are yielded by _orchestrator_loop."""
    from amplifier_ipc.host.events import ChildSessionEvent, StreamTokenEvent

    config = SessionConfig(
        services=["orch"],
        orchestrator="loop",
        context_manager="simple",
        provider="anthropic",
    )
    settings = HostSettings()

    host = Host(config=config, settings=settings)

    fake_process = MagicMock()
    fake_process.stdin = MagicMock()
    fake_process.stdout = MagicMock()

    fake_service = MagicMock()
    fake_service.process = fake_process
    host._services = {"orch": fake_service}

    captured_id: list[str] = []

    async def fake_write(stream: object, message: dict) -> None:
        if message.get("method") == "orchestrator.execute":
            captured_id.append(message["id"])

    read_call_count = 0

    async def fake_read(stream: object) -> dict | None:
        nonlocal read_call_count
        read_call_count += 1
        if read_call_count == 1:
            # Before returning the final response, queue a child event
            child_event = ChildSessionEvent(
                depth=1,
                inner=StreamTokenEvent(token="from child"),
            )
            host._child_event_queue.put_nowait(child_event)
            # Return a normal stream token
            return {
                "jsonrpc": "2.0",
                "method": "stream.token",
                "params": {"token": "parent"},
            }
        else:
            return {
                "jsonrpc": "2.0",
                "id": captured_id[0],
                "result": "done",
            }

    with (
        patch("amplifier_ipc.host.host.write_message", fake_write),
        patch("amplifier_ipc.host.host.read_message", fake_read),
    ):
        events = []
        async for event in host._orchestrator_loop(
            orchestrator_key="orch",
            prompt="hello",
            system_prompt="be helpful",
        ):
            events.append(event)

    # Should have: StreamTokenEvent("parent"), ChildSessionEvent, CompleteEvent
    event_types = [type(e).__name__ for e in events]
    assert "ChildSessionEvent" in event_types, f"Missing ChildSessionEvent in {event_types}"
    child_events = [e for e in events if isinstance(e, ChildSessionEvent)]
    assert len(child_events) == 1
    assert child_events[0].inner.token == "from child"


async def test_build_spawn_handler_provides_event_callback() -> None:
    """The spawn handler passes an event_callback that queues ChildSessionEvents."""
    from amplifier_ipc.host.events import (
        ChildSessionEndEvent,
        ChildSessionEvent,
        ChildSessionStartEvent,
        StreamTokenEvent,
    )

    config = SessionConfig(
        services=["foundation"],
        orchestrator="loop",
        context_manager="simple",
        provider="anthropic",
    )
    settings = HostSettings()
    host = Host(config=config, settings=settings)

    registry = CapabilityRegistry()
    registry.register(
        "foundation",
        {
            "tools": [{"name": "bash"}],
            "hooks": [],
            "orchestrators": [],
            "context_managers": [],
            "providers": [],
            "content": [],
        },
    )
    host._registry = registry
    host._services = {"foundation": MagicMock()}
    host._persistence = MagicMock()
    host._persistence.load_transcript.return_value = []

    # Track what spawn_child_session receives
    captured_callback = []

    async def mock_spawn(**kwargs):
        cb = kwargs.get("event_callback")
        captured_callback.append(cb)
        # Simulate child events
        if cb:
            cb(StreamTokenEvent(token="child token"))
        return {
            "session_id": "child-123",
            "response": "done",
            "turn_count": 1,
            "metadata": {"agent": "self"},
        }

    spawn_handler = host._build_spawn_handler("parent-session")

    with patch("amplifier_ipc.host.host.spawn_child_session", mock_spawn):
        await spawn_handler({
            "agent": "self",
            "instruction": "do something",
        })

    # Verify callback was provided
    assert len(captured_callback) == 1
    assert captured_callback[0] is not None

    # Verify the child event was queued as a ChildSessionEvent wrapper
    assert not host._child_event_queue.empty()
    # Drain: should have ChildSessionStartEvent, ChildSessionEvent(token), ChildSessionEndEvent
    queued_events = []
    while not host._child_event_queue.empty():
        queued_events.append(host._child_event_queue.get_nowait())
    
    # Find the wrapped token event
    child_session_events = [e for e in queued_events if isinstance(e, ChildSessionEvent)]
    assert len(child_session_events) >= 1
    token_events = [e for e in child_session_events if isinstance(e.inner, StreamTokenEvent)]
    assert len(token_events) == 1
    assert token_events[0].inner.token == "child token"
    assert token_events[0].depth == 1
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/host/test_host.py::test_orchestrator_loop_drains_child_event_queue tests/host/test_host.py::test_build_spawn_handler_provides_event_callback -v
```

Expected: FAIL — `_child_event_queue` doesn't exist, `event_callback` not passed.

**Step 3: Write the implementation**

**3a. Add `_child_event_queue` to `Host.__init__`** in `src/amplifier_ipc/host/host.py`:

After the existing `_provider_notification_queue` line (line ~98), add:
```python
        self._child_event_queue: asyncio.Queue[HostEvent] = asyncio.Queue()
```

**3b. Add imports for new event types** to the import block in `host.py` (line ~24):

Add to the existing `from amplifier_ipc.host.events import (` block:
```python
    ChildSessionEndEvent,
    ChildSessionEvent,
    ChildSessionStartEvent,
    ToolCallEvent,
    ToolResultEvent,
    TodoUpdateEvent,
```

**3c. Drain `_child_event_queue` in `_orchestrator_loop`**.

In the `_orchestrator_loop` method, right after the existing block that drains `_provider_notification_queue` (lines ~512-514):

```python
            # Drain provider notification queue and forward to orchestrator
            while not self._provider_notification_queue.empty():
                notification = self._provider_notification_queue.get_nowait()
                await write_message(orchestrator_svc.process.stdin, notification)

            # Drain child event queue — yield forwarded child session events
            while not self._child_event_queue.empty():
                yield self._child_event_queue.get_nowait()
```

**3d. Update `_build_spawn_handler` to provide `event_callback`**.

In the `_handle_spawn` closure inside `_build_spawn_handler` (line ~281), replace the `spawn_child_session` call with one that includes an event callback:

```python
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
            parent_config: dict[str, Any] = {
                "services": list(self._config.services),
                "orchestrator": self._config.orchestrator,
                "context_manager": self._config.context_manager,
                "provider": self._config.provider,
                "component_config": dict(self._config.component_config),
                "tools": self._registry.get_all_tool_specs(),
                "hooks": self._registry.get_all_hook_descriptors(),
            }

            # Generate child session ID for start/end events
            agent_name = spawn_request.agent
            from amplifier_ipc.host.spawner import generate_child_session_id
            child_session_id = generate_child_session_id(session_id, agent_name)

            # Build event callback that wraps child events with nesting depth
            def _forward_child_event(event: HostEvent) -> None:
                self._child_event_queue.put_nowait(
                    ChildSessionEvent(depth=1, inner=event)
                )

            # Emit ChildSessionStartEvent
            self._child_event_queue.put_nowait(
                ChildSessionStartEvent(
                    agent_name=agent_name,
                    session_id=child_session_id,
                    depth=1,
                )
            )

            try:
                return await spawn_child_session(
                    parent_session_id=session_id,
                    parent_config=parent_config,
                    transcript=transcript,
                    request=spawn_request,
                    settings=self._settings,
                    service_configs=self._service_configs,
                    shared_services=self._services,
                    shared_registry=self._registry,
                    event_callback=_forward_child_event,
                )
            finally:
                # Always emit ChildSessionEndEvent so CLI resets indentation
                self._child_event_queue.put_nowait(
                    ChildSessionEndEvent(
                        session_id=child_session_id,
                        depth=1,
                    )
                )

        return _handle_spawn
```

Note: The `generate_child_session_id` import is lazy because it's already imported at the top of the file from spawner. Check if it's already in the imports; if so, use it directly without the lazy import. Looking at the existing imports (line 40): `from amplifier_ipc.host.spawner import (SpawnRequest, _run_child_session, spawn_child_session,)` — `generate_child_session_id` is NOT imported. Add it to the existing import:

```python
from amplifier_ipc.host.spawner import (
    SpawnRequest,
    _run_child_session,
    generate_child_session_id,
    spawn_child_session,
)
```

Then remove the lazy `from amplifier_ipc.host.spawner import generate_child_session_id` from inside the closure.

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/host/test_host.py -v
uv run pytest tests/host/test_spawner.py -v
uv run pytest tests/host/test_spawn_integration.py -v
```

Expected: All PASS.

**Step 5: Commit**

```bash
git add src/amplifier_ipc/host/host.py tests/host/test_host.py
git commit -m "feat: wire child event queue and forwarding callback in host spawn handler"
```

---

## Layer 2: Orchestrator Notifications for Rich Events

### Task 4: Emit stream.tool_call notification from orchestrator

**Files:**
- Modify: `services/amplifier-foundation/src/amplifier_foundation/orchestrators/streaming.py`
- Modify: `services/amplifier-foundation/tests/test_orchestrator.py`

**Step 1: Write the failing test**

Add to `services/amplifier-foundation/tests/test_orchestrator.py`:

```python
@pytest.mark.asyncio
async def test_orchestrator_emits_stream_tool_call_notification() -> None:
    """Orchestrator emits stream.tool_call with tool_name and arguments before tool execution."""
    from amplifier_foundation.orchestrators.streaming import StreamingOrchestrator

    orch = StreamingOrchestrator()

    tool_call_response = chat_response(
        text="",
        tool_calls=[{"id": "call_1", "tool": "bash", "arguments": {"command": "ls -la"}}],
    )
    final_response = chat_response("Done!")

    client = MockClient(
        responses={
            "request.hook_emit": hook_continue(),
            "request.context_add_message": None,
            "request.context_get_messages": [],
            "request.provider_complete": Sequence(tool_call_response, final_response),
            "request.tool_execute": tool_result_ok("file1.txt"),
        }
    )

    await orch.execute("List files", {}, client)

    # Find stream.tool_call notifications
    tool_call_notifs = [
        (m, p) for m, p in client.notifications if m == "stream.tool_call"
    ]
    assert len(tool_call_notifs) == 1, (
        f"Expected 1 stream.tool_call notification, got {len(tool_call_notifs)}"
    )
    _, params = tool_call_notifs[0]
    assert params["tool_name"] == "bash"
    assert params["arguments"] == {"command": "ls -la"}
```

**Step 2: Run test to verify it fails**

```bash
cd /data/labs/amplifier-ipc && uv run pytest services/amplifier-foundation/tests/test_orchestrator.py::test_orchestrator_emits_stream_tool_call_notification -v
```

Expected: FAIL — no `stream.tool_call` notification emitted.

**Step 3: Write the implementation**

In `services/amplifier-foundation/src/amplifier_foundation/orchestrators/streaming.py`, add a constant near the top (after line 48):

```python
STREAM_TOOL_CALL = "stream.tool_call"
```

In the `_execute_tool` method, right after the `stream.tool_call_start` notification (line ~288) and before the `tool:pre` hook emit (line ~292), add:

```python
            # --- emit stream.tool_call (with full arguments for display) ---
            await client.send_notification(
                STREAM_TOOL_CALL,
                {"tool_name": tool_call.name, "arguments": tool_call.arguments},
            )
```

**Step 4: Run test to verify it passes**

```bash
cd /data/labs/amplifier-ipc && uv run pytest services/amplifier-foundation/tests/test_orchestrator.py -v
```

Expected: All PASS.

**Step 5: Commit**

```bash
git add services/amplifier-foundation/src/amplifier_foundation/orchestrators/streaming.py services/amplifier-foundation/tests/test_orchestrator.py
git commit -m "feat: emit stream.tool_call notification with arguments from orchestrator"
```

---

### Task 5: Emit stream.tool_result notification from orchestrator

**Files:**
- Modify: `services/amplifier-foundation/src/amplifier_foundation/orchestrators/streaming.py`
- Modify: `services/amplifier-foundation/tests/test_orchestrator.py`

**Step 1: Write the failing test**

Add to `services/amplifier-foundation/tests/test_orchestrator.py`:

```python
@pytest.mark.asyncio
async def test_orchestrator_emits_stream_tool_result_notification() -> None:
    """Orchestrator emits stream.tool_result with success status and output after tool execution."""
    from amplifier_foundation.orchestrators.streaming import StreamingOrchestrator

    orch = StreamingOrchestrator()

    tool_call_response = chat_response(
        text="",
        tool_calls=[{"id": "call_1", "tool": "bash", "arguments": {"command": "echo hi"}}],
    )
    final_response = chat_response("Done!")

    client = MockClient(
        responses={
            "request.hook_emit": hook_continue(),
            "request.context_add_message": None,
            "request.context_get_messages": [],
            "request.provider_complete": Sequence(tool_call_response, final_response),
            "request.tool_execute": tool_result_ok("hi"),
        }
    )

    await orch.execute("Say hi", {}, client)

    # Find stream.tool_result notifications
    result_notifs = [
        (m, p) for m, p in client.notifications if m == "stream.tool_result"
    ]
    assert len(result_notifs) == 1, (
        f"Expected 1 stream.tool_result notification, got {len(result_notifs)}"
    )
    _, params = result_notifs[0]
    assert params["tool_name"] == "bash"
    assert params["success"] is True
    assert "hi" in params["output"]
```

**Step 2: Run test to verify it fails**

```bash
cd /data/labs/amplifier-ipc && uv run pytest services/amplifier-foundation/tests/test_orchestrator.py::test_orchestrator_emits_stream_tool_result_notification -v
```

Expected: FAIL — no `stream.tool_result` notification.

**Step 3: Write the implementation**

Add a constant near the top of the orchestrator file:

```python
STREAM_TOOL_RESULT = "stream.tool_result"
```

In the `_execute_tool` method, after the `tool:post` hook emit and result extraction (after line ~332, before the `return` on line ~341), add:

```python
            # --- emit stream.tool_result (for display) ---
            await client.send_notification(
                STREAM_TOOL_RESULT,
                {
                    "tool_name": tool_call.name,
                    "success": tool_result.success if hasattr(tool_result, 'success') else True,
                    "output": content[:2000],  # cap for display
                },
            )
```

Place this right before the final `return (tool_call.id, tool_call.name, content)` line in the success path.

Also emit a failure result in the exception handler (before the `return` in the `except` block around line ~354):

```python
            # In the except block, before the return:
            await client.send_notification(
                STREAM_TOOL_RESULT,
                {
                    "tool_name": tool_call.name,
                    "success": False,
                    "output": f"Error: {exc}",
                },
            )
```

**Step 4: Run test to verify it passes**

```bash
cd /data/labs/amplifier-ipc && uv run pytest services/amplifier-foundation/tests/test_orchestrator.py -v
```

Expected: All PASS.

**Step 5: Commit**

```bash
git add services/amplifier-foundation/src/amplifier_foundation/orchestrators/streaming.py services/amplifier-foundation/tests/test_orchestrator.py
git commit -m "feat: emit stream.tool_result notification from orchestrator"
```

---

### Task 6: Emit stream.todo_update notification from orchestrator

**Files:**
- Modify: `services/amplifier-foundation/src/amplifier_foundation/orchestrators/streaming.py`
- Modify: `services/amplifier-foundation/tests/test_orchestrator.py`

**Step 1: Write the failing test**

Add to `services/amplifier-foundation/tests/test_orchestrator.py`:

```python
@pytest.mark.asyncio
async def test_orchestrator_emits_stream_todo_update_for_todo_tool() -> None:
    """Orchestrator emits stream.todo_update when a 'todo' tool call returns results."""
    from amplifier_foundation.orchestrators.streaming import StreamingOrchestrator

    orch = StreamingOrchestrator()

    todo_result = {
        "success": True,
        "output": '{"todos": [{"content": "Fix bug", "status": "completed"}], "status": "updated"}',
        "error": None,
    }

    tool_call_response = chat_response(
        text="",
        tool_calls=[{"id": "call_todo", "tool": "todo", "arguments": {"action": "update"}}],
    )
    final_response = chat_response("Updated todos!")

    client = MockClient(
        responses={
            "request.hook_emit": hook_continue(),
            "request.context_add_message": None,
            "request.context_get_messages": [],
            "request.provider_complete": Sequence(tool_call_response, final_response),
            "request.tool_execute": todo_result,
        }
    )

    await orch.execute("Update my todos", {}, client)

    # Find stream.todo_update notifications
    todo_notifs = [
        (m, p) for m, p in client.notifications if m == "stream.todo_update"
    ]
    assert len(todo_notifs) == 1, (
        f"Expected 1 stream.todo_update notification, got {len(todo_notifs)}"
    )
    _, params = todo_notifs[0]
    assert "todos" in params
```

**Step 2: Run test to verify it fails**

```bash
cd /data/labs/amplifier-ipc && uv run pytest services/amplifier-foundation/tests/test_orchestrator.py::test_orchestrator_emits_stream_todo_update_for_todo_tool -v
```

Expected: FAIL — no `stream.todo_update` notification.

**Step 3: Write the implementation**

Add a constant:

```python
STREAM_TODO_UPDATE = "stream.todo_update"
```

In the `_execute_tool` method, after the `stream.tool_result` notification and before the final `return`, add a check for the `todo` tool:

```python
            # --- emit stream.todo_update for todo tool calls ---
            if tool_call.name == "todo":
                try:
                    parsed = json.loads(content) if isinstance(content, str) else content
                    if isinstance(parsed, dict) and "todos" in parsed:
                        await client.send_notification(
                            STREAM_TODO_UPDATE,
                            {
                                "todos": parsed.get("todos", []),
                                "status": parsed.get("status", "updated"),
                            },
                        )
                except (json.JSONDecodeError, TypeError):
                    pass  # Not JSON or not a todo response — skip
```

**Step 4: Run test to verify it passes**

```bash
cd /data/labs/amplifier-ipc && uv run pytest services/amplifier-foundation/tests/test_orchestrator.py -v
```

Expected: All PASS.

**Step 5: Commit**

```bash
git add services/amplifier-foundation/src/amplifier_foundation/orchestrators/streaming.py services/amplifier-foundation/tests/test_orchestrator.py
git commit -m "feat: emit stream.todo_update notification for todo tool calls"
```

---

### Task 7: Map new notifications to event types in host.py

**Files:**
- Modify: `src/amplifier_ipc/host/host.py`
- Modify: `tests/host/test_host.py`

**Step 1: Write the failing tests**

Add to `tests/host/test_host.py`:

```python
from amplifier_ipc.host.events import ToolCallEvent, ToolResultEvent, TodoUpdateEvent


async def test_orchestrator_loop_yields_tool_call_event() -> None:
    """_orchestrator_loop yields ToolCallEvent for stream.tool_call notifications."""
    config = SessionConfig(
        services=["orch"],
        orchestrator="loop",
        context_manager="simple",
        provider="anthropic",
    )
    settings = HostSettings()
    host = Host(config=config, settings=settings)

    fake_process = MagicMock()
    fake_process.stdin = MagicMock()
    fake_process.stdout = MagicMock()
    fake_service = MagicMock()
    fake_service.process = fake_process
    host._services = {"orch": fake_service}

    captured_id: list[str] = []

    async def fake_write(stream: object, message: dict) -> None:
        if message.get("method") == "orchestrator.execute":
            captured_id.append(message["id"])

    read_call_count = 0

    async def fake_read(stream: object) -> dict | None:
        nonlocal read_call_count
        read_call_count += 1
        if read_call_count == 1:
            return {
                "jsonrpc": "2.0",
                "method": "stream.tool_call",
                "params": {"tool_name": "bash", "arguments": {"command": "ls"}},
            }
        elif read_call_count == 2:
            return {
                "jsonrpc": "2.0",
                "method": "stream.tool_result",
                "params": {"tool_name": "bash", "success": True, "output": "file.txt"},
            }
        elif read_call_count == 3:
            return {
                "jsonrpc": "2.0",
                "method": "stream.todo_update",
                "params": {
                    "todos": [{"content": "Do X", "status": "pending"}],
                    "status": "created",
                },
            }
        else:
            return {
                "jsonrpc": "2.0",
                "id": captured_id[0],
                "result": "done",
            }

    with (
        patch("amplifier_ipc.host.host.write_message", fake_write),
        patch("amplifier_ipc.host.host.read_message", fake_read),
    ):
        events = []
        async for event in host._orchestrator_loop(
            orchestrator_key="orch",
            prompt="hello",
            system_prompt="be helpful",
        ):
            events.append(event)

    # Should have ToolCallEvent, ToolResultEvent, TodoUpdateEvent, CompleteEvent
    assert any(isinstance(e, ToolCallEvent) for e in events), (
        f"Missing ToolCallEvent in {[type(e).__name__ for e in events]}"
    )
    assert any(isinstance(e, ToolResultEvent) for e in events)
    assert any(isinstance(e, TodoUpdateEvent) for e in events)

    tool_call = next(e for e in events if isinstance(e, ToolCallEvent))
    assert tool_call.tool_name == "bash"
    assert tool_call.arguments == {"command": "ls"}

    tool_result = next(e for e in events if isinstance(e, ToolResultEvent))
    assert tool_result.tool_name == "bash"
    assert tool_result.success is True
    assert tool_result.output == "file.txt"

    todo_update = next(e for e in events if isinstance(e, TodoUpdateEvent))
    assert todo_update.status == "created"
    assert len(todo_update.todos) == 1
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/host/test_host.py::test_orchestrator_loop_yields_tool_call_event -v
```

Expected: FAIL — `stream.tool_call` etc. are logged as "Unhandled stream notification".

**Step 3: Write the implementation**

In `src/amplifier_ipc/host/host.py`, in the `_orchestrator_loop` method, add new `elif` branches for the three new notification types. Add them right after the `stream.content_block_end` handler (after line ~578) and before the `approval_request` handler (line ~582):

```python
            # Stream tool call notification (with arguments)
            elif method == "stream.tool_call":
                params = message.get("params") or {}
                yield ToolCallEvent(
                    tool_name=params.get("tool_name", ""),
                    arguments=params.get("arguments", {}),
                )

            # Stream tool result notification
            elif method == "stream.tool_result":
                params = message.get("params") or {}
                yield ToolResultEvent(
                    tool_name=params.get("tool_name", ""),
                    success=params.get("success", True),
                    output=params.get("output", ""),
                )

            # Stream todo update notification
            elif method == "stream.todo_update":
                params = message.get("params") or {}
                yield TodoUpdateEvent(
                    todos=params.get("todos", []),
                    status=params.get("status", ""),
                )
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/host/test_host.py -v
```

Expected: All PASS.

**Step 5: Commit**

```bash
git add src/amplifier_ipc/host/host.py tests/host/test_host.py
git commit -m "feat: map stream.tool_call, stream.tool_result, stream.todo_update to events in host"
```

---

## Layer 3: CLI Rendering

### Task 8: Rich rendering of ToolCallEvent

**Files:**
- Modify: `src/amplifier_ipc/cli/streaming.py`
- Modify: `tests/cli/test_streaming.py`

**Step 1: Write the failing test**

Add to `tests/cli/test_streaming.py`:

```python
from amplifier_ipc.host.events import ToolCallEvent


class TestStreamingDisplayToolCall:
    def test_tool_call_renders_name_and_args(self) -> None:
        """ToolCallEvent should render tool name with wrench emoji and formatted args."""
        from amplifier_ipc.cli.streaming import StreamingDisplay

        console, buf = _make_console()
        display = StreamingDisplay(console=console)

        event = ToolCallEvent(
            tool_name="bash",
            arguments={"command": "pytest tests/ -v", "timeout": 30},
        )
        display.handle_event(event)

        output = buf.getvalue()
        assert "bash" in output
        assert "command" in output
        assert "pytest tests/ -v" in output
        assert "timeout" in output

    def test_tool_call_truncates_long_args(self) -> None:
        """ToolCallEvent with many argument lines should be truncated."""
        from amplifier_ipc.cli.streaming import StreamingDisplay

        console, buf = _make_console()
        display = StreamingDisplay(console=console)

        # Create an event with many arguments
        args = {f"arg_{i}": f"value_{i}" for i in range(15)}
        event = ToolCallEvent(tool_name="complex_tool", arguments=args)
        display.handle_event(event)

        output = buf.getvalue()
        assert "complex_tool" in output
        # Should contain truncation indicator
        assert "more" in output.lower() or output.count("\n") <= 14
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/cli/test_streaming.py::TestStreamingDisplayToolCall -v
```

Expected: FAIL — `ToolCallEvent` not handled.

**Step 3: Write the implementation**

In `src/amplifier_ipc/cli/streaming.py`:

Add imports at the top:
```python
from amplifier_ipc.host.events import (
    CompleteEvent,
    ErrorEvent,
    HostEvent,
    StreamThinkingEvent,
    StreamTokenEvent,
    StreamToolCallStartEvent,
    ToolCallEvent,
)
```

Add a handler method and dispatch entry:

In `handle_event`, add after the `StreamToolCallStartEvent` check:
```python
        elif isinstance(event, ToolCallEvent):
            self._handle_tool_call(event)
```

Add the handler method:
```python
    def _handle_tool_call(self, event: ToolCallEvent) -> None:
        """Print tool name with wrench emoji and YAML-formatted arguments."""
        self._console.print(f"\n[bold]\U0001f527 Using tool: {event.tool_name}[/bold]")
        if event.arguments:
            lines: list[str] = []
            for key, value in event.arguments.items():
                val_str = str(value)
                if len(val_str) > 200:
                    val_str = val_str[:200] + "..."
                lines.append(f"   {key}: {val_str}")
            if len(lines) > 10:
                display_lines = lines[:10]
                display_lines.append(f"   ... ({len(lines) - 10} more)")
            else:
                display_lines = lines
            for line in display_lines:
                self._console.print(line, markup=False, highlight=False)
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/cli/test_streaming.py -v
```

Expected: All PASS.

**Step 5: Commit**

```bash
git add src/amplifier_ipc/cli/streaming.py tests/cli/test_streaming.py
git commit -m "feat: render ToolCallEvent with formatted arguments in StreamingDisplay"
```

---

### Task 9: Rich rendering of ToolResultEvent

**Files:**
- Modify: `src/amplifier_ipc/cli/streaming.py`
- Modify: `tests/cli/test_streaming.py`

**Step 1: Write the failing test**

Add to `tests/cli/test_streaming.py`:

```python
from amplifier_ipc.host.events import ToolResultEvent


class TestStreamingDisplayToolResult:
    def test_tool_result_success(self) -> None:
        """ToolResultEvent with success=True should show green check."""
        from amplifier_ipc.cli.streaming import StreamingDisplay

        console, buf = _make_console()
        display = StreamingDisplay(console=console)

        event = ToolResultEvent(tool_name="bash", success=True, output="6 passed in 1.2s")
        display.handle_event(event)

        output = buf.getvalue()
        assert "bash" in output
        assert "6 passed in 1.2s" in output

    def test_tool_result_failure(self) -> None:
        """ToolResultEvent with success=False should show red X."""
        from amplifier_ipc.cli.streaming import StreamingDisplay

        console, buf = _make_console()
        display = StreamingDisplay(console=console)

        event = ToolResultEvent(tool_name="bash", success=False, output="command not found")
        display.handle_event(event)

        output = buf.getvalue()
        assert "bash" in output
        assert "command not found" in output

    def test_tool_result_truncates_long_output(self) -> None:
        """ToolResultEvent with long output should be truncated."""
        from amplifier_ipc.cli.streaming import StreamingDisplay

        console, buf = _make_console()
        display = StreamingDisplay(console=console)

        long_output = "\n".join([f"line {i}" for i in range(50)])
        event = ToolResultEvent(tool_name="read_file", success=True, output=long_output)
        display.handle_event(event)

        output = buf.getvalue()
        assert "read_file" in output
        # Should be truncated — not all 50 lines shown
        assert output.count("line ") <= 12
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/cli/test_streaming.py::TestStreamingDisplayToolResult -v
```

Expected: FAIL — `ToolResultEvent` not handled.

**Step 3: Write the implementation**

In `src/amplifier_ipc/cli/streaming.py`:

Add `ToolResultEvent` to imports and dispatch:
```python
        elif isinstance(event, ToolResultEvent):
            self._handle_tool_result(event)
```

Add the handler:
```python
    def _handle_tool_result(self, event: ToolResultEvent) -> None:
        """Print tool result with success/failure icon and truncated output."""
        if event.success:
            icon = "\u2705"
            style = "green"
        else:
            icon = "\u274c"
            style = "red"
        self._console.print(f"[{style}]{icon} Tool result: {event.tool_name}[/{style}]")
        if event.output:
            lines = event.output.split("\n")
            if len(lines) > 10:
                display_lines = lines[:10]
                display_lines.append(f"... ({len(lines) - 10} more lines)")
            else:
                display_lines = lines
            for line in display_lines:
                truncated = line[:200] + "..." if len(line) > 200 else line
                self._console.print(f"   {truncated}", markup=False, highlight=False)
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/cli/test_streaming.py -v
```

Expected: All PASS.

**Step 5: Commit**

```bash
git add src/amplifier_ipc/cli/streaming.py tests/cli/test_streaming.py
git commit -m "feat: render ToolResultEvent with success/failure icons in StreamingDisplay"
```

---

### Task 10: Rich rendering of TodoUpdateEvent

**Files:**
- Modify: `src/amplifier_ipc/cli/streaming.py`
- Modify: `tests/cli/test_streaming.py`

**Step 1: Write the failing test**

Add to `tests/cli/test_streaming.py`:

```python
from amplifier_ipc.host.events import TodoUpdateEvent


class TestStreamingDisplayTodoUpdate:
    def test_todo_update_renders_items(self) -> None:
        """TodoUpdateEvent should render todo items with status symbols."""
        from amplifier_ipc.cli.streaming import StreamingDisplay

        console, buf = _make_console()
        display = StreamingDisplay(console=console)

        todos = [
            {"content": "Fix parser alignment", "status": "completed", "activeForm": "Fixing parser"},
            {"content": "Testing lifecycle", "status": "in_progress", "activeForm": "Testing"},
            {"content": "Add streaming events", "status": "pending", "activeForm": "Adding events"},
        ]
        event = TodoUpdateEvent(todos=todos, status="updated")
        display.handle_event(event)

        output = buf.getvalue()
        assert "Fix parser alignment" in output
        assert "Testing lifecycle" in output
        assert "Add streaming events" in output
        # Should contain progress indication
        assert "1/3" in output or "3" in output

    def test_todo_update_empty(self) -> None:
        """TodoUpdateEvent with empty todos should not crash."""
        from amplifier_ipc.cli.streaming import StreamingDisplay

        console, buf = _make_console()
        display = StreamingDisplay(console=console)

        event = TodoUpdateEvent(todos=[], status="listed")
        display.handle_event(event)
        # Should not crash — may render nothing or a minimal box
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/cli/test_streaming.py::TestStreamingDisplayTodoUpdate -v
```

Expected: FAIL — `TodoUpdateEvent` not handled.

**Step 3: Write the implementation**

Add `TodoUpdateEvent` to imports and dispatch:
```python
        elif isinstance(event, TodoUpdateEvent):
            self._handle_todo_update(event)
```

Add the handler:
```python
    def _handle_todo_update(self, event: TodoUpdateEvent) -> None:
        """Print todo list with status symbols and progress bar."""
        if not event.todos:
            return
        width = min(60, self._console.width - 4) if self._console.width else 60
        # Status symbols
        status_symbols = {
            "completed": "\u2713",
            "in_progress": "\u25b6",
            "pending": "\u25cb",
        }
        completed = sum(1 for t in event.todos if t.get("status") == "completed")
        total = len(event.todos)

        self._console.print(f"\n\u250c\u2500 Todo {'\u2500' * (width - 9)}\u2510")
        # Full mode for <=7 items, condensed for >7
        if total <= 7:
            for todo in event.todos:
                status = todo.get("status", "pending")
                symbol = status_symbols.get(status, "\u25cb")
                content = todo.get("content", "")[:width - 6]
                padded = content.ljust(width - 6)
                self._console.print(
                    f"\u2502 {symbol} {padded} \u2502", markup=False, highlight=False
                )
        else:
            in_progress = sum(1 for t in event.todos if t.get("status") == "in_progress")
            pending = total - completed - in_progress
            summary = f"{completed} done, {in_progress} active, {pending} pending"
            padded = summary.ljust(width - 4)
            self._console.print(
                f"\u2502 {padded} \u2502", markup=False, highlight=False
            )
        # Progress bar
        bar_width = 24
        filled = int(bar_width * completed / total) if total > 0 else 0
        bar = "\u2588" * filled + "\u2591" * (bar_width - filled)
        progress_text = f"{bar} {completed}/{total}"
        padded_progress = progress_text.ljust(width - 4)
        self._console.print(
            f"\u2502 {padded_progress} \u2502", markup=False, highlight=False
        )
        self._console.print(f"\u2514{'\u2500' * (width - 2)}\u2518")
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/cli/test_streaming.py -v
```

Expected: All PASS.

**Step 5: Commit**

```bash
git add src/amplifier_ipc/cli/streaming.py tests/cli/test_streaming.py
git commit -m "feat: render TodoUpdateEvent with status symbols and progress bar"
```

---

### Task 11: Rich rendering of thinking blocks

**Files:**
- Modify: `src/amplifier_ipc/cli/streaming.py`
- Modify: `tests/cli/test_streaming.py`

The existing `_handle_thinking` in `StreamingDisplay` just prints dim cyan text. The design calls for bordered thinking blocks. However, since thinking tokens arrive incrementally (one `StreamThinkingEvent` per fragment), we need a state machine: track whether we're "in a thinking block" using `StreamContentBlockStartEvent` / `StreamContentBlockEndEvent` with `block_type="thinking"`.

**Step 1: Write the failing test**

Add to `tests/cli/test_streaming.py`:

```python
from amplifier_ipc.host.events import StreamContentBlockStartEvent, StreamContentBlockEndEvent


class TestStreamingDisplayThinkingBlock:
    def test_thinking_block_has_borders(self) -> None:
        """Thinking block should render with header and border characters."""
        from amplifier_ipc.cli.streaming import StreamingDisplay

        console, buf = _make_console()
        display = StreamingDisplay(console=console, show_thinking=True)

        # Simulate: block start -> thinking content -> block end
        display.handle_event(StreamContentBlockStartEvent(block_type="thinking", index=0))
        display.handle_event(StreamThinkingEvent(thinking="I need to analyze the code..."))
        display.handle_event(StreamContentBlockEndEvent(block_type="thinking", index=0))

        output = buf.getvalue()
        # Should contain the thinking text
        assert "I need to analyze the code..." in output
        # Should contain border characters (double line ═ or single line ─)
        assert "\u2550" in output or "\u2500" in output or "Thinking" in output
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/cli/test_streaming.py::TestStreamingDisplayThinkingBlock -v
```

Expected: FAIL — no border characters in output.

**Step 3: Write the implementation**

Add a `_in_thinking_block` state flag to `__init__`:
```python
        self._in_thinking_block: bool = False
```

Update the `handle_event` dispatch to handle content block events for thinking:
```python
        elif isinstance(event, StreamContentBlockStartEvent):
            self._handle_content_block_start(event)
        elif isinstance(event, StreamContentBlockEndEvent):
            self._handle_content_block_end(event)
```

Add `StreamContentBlockStartEvent` and `StreamContentBlockEndEvent` to the imports.

Add handlers:
```python
    def _handle_content_block_start(self, event: StreamContentBlockStartEvent) -> None:
        """Handle content block start — render thinking block header if applicable."""
        if event.block_type == "thinking" and self._show_thinking:
            self._in_thinking_block = True
            width = min(60, self._console.width - 4) if self._console.width else 60
            self._console.print(f"\n[dim]\U0001f9e0 Thinking...[/dim]")
            self._console.print("[dim]" + "\u2550" * width + "[/dim]")

    def _handle_content_block_end(self, event: StreamContentBlockEndEvent) -> None:
        """Handle content block end — render thinking block footer if applicable."""
        if event.block_type == "thinking" and self._in_thinking_block:
            self._in_thinking_block = False
            width = min(60, self._console.width - 4) if self._console.width else 60
            self._console.print()  # newline after thinking text
            self._console.print("[dim]" + "\u2550" * width + "[/dim]")
```

Update the existing `_handle_thinking` to render dim when inside a thinking block (it already does — just verify it doesn't add extra formatting):
```python
    def _handle_thinking(self, event: StreamThinkingEvent) -> None:
        """Print thinking text in cyan dim style when show_thinking is enabled."""
        if self._show_thinking:
            self._console.print(event.thinking, end="", style="cyan dim", markup=False)
```

This is already correct — no changes needed to the existing method.

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/cli/test_streaming.py -v
```

Expected: All PASS.

**Step 5: Commit**

```bash
git add src/amplifier_ipc/cli/streaming.py tests/cli/test_streaming.py
git commit -m "feat: render thinking blocks with bordered header/footer in StreamingDisplay"
```

---

### Task 12: Rich rendering of ChildSessionEvent

**Files:**
- Modify: `src/amplifier_ipc/cli/streaming.py`
- Modify: `tests/cli/test_streaming.py`

**Step 1: Write the failing test**

Add to `tests/cli/test_streaming.py`:

```python
from amplifier_ipc.host.events import (
    ChildSessionStartEvent,
    ChildSessionEndEvent,
    ChildSessionEvent,
)


class TestStreamingDisplayChildSession:
    def test_child_session_start_renders_delegate_header(self) -> None:
        """ChildSessionStartEvent should render a delegate header with agent name."""
        from amplifier_ipc.cli.streaming import StreamingDisplay

        console, buf = _make_console()
        display = StreamingDisplay(console=console)

        event = ChildSessionStartEvent(agent_name="explorer", session_id="abc", depth=1)
        display.handle_event(event)

        output = buf.getvalue()
        assert "explorer" in output
        assert "delegate" in output.lower() or "\u2699" in output

    def test_child_session_event_indents_inner(self) -> None:
        """ChildSessionEvent should render the inner event with indentation."""
        from amplifier_ipc.cli.streaming import StreamingDisplay

        console, buf = _make_console()
        display = StreamingDisplay(console=console)

        inner = ToolCallEvent(tool_name="read_file", arguments={"file_path": "src/main.py"})
        event = ChildSessionEvent(depth=1, inner=inner)
        display.handle_event(event)

        output = buf.getvalue()
        assert "read_file" in output
        # Should be indented — look for leading spaces on lines with content
        lines = [l for l in output.split("\n") if "read_file" in l]
        assert any(l.startswith("    ") for l in lines), (
            f"Expected indentation, got: {lines}"
        )

    def test_child_session_event_depth_2(self) -> None:
        """ChildSessionEvent at depth 2 should have 8 spaces of indentation."""
        from amplifier_ipc.cli.streaming import StreamingDisplay

        console, buf = _make_console()
        display = StreamingDisplay(console=console)

        inner = StreamTokenEvent(token="nested token")
        event = ChildSessionEvent(depth=2, inner=inner)
        display.handle_event(event)

        output = buf.getvalue()
        assert "nested token" in output
        # Lines should have 8-space indentation (4 * depth=2)
        lines = [l for l in output.split("\n") if "nested token" in l]
        assert any(l.startswith("        ") for l in lines), (
            f"Expected 8-space indent at depth 2, got: {lines}"
        )

    def test_child_session_end_is_silent(self) -> None:
        """ChildSessionEndEvent should produce no visible output."""
        from amplifier_ipc.cli.streaming import StreamingDisplay

        console, buf = _make_console()
        display = StreamingDisplay(console=console)

        event = ChildSessionEndEvent(session_id="abc", depth=1)
        display.handle_event(event)

        output = buf.getvalue()
        # Should be empty or just whitespace
        assert output.strip() == ""
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/cli/test_streaming.py::TestStreamingDisplayChildSession -v
```

Expected: FAIL — `ChildSessionEvent` etc. not handled.

**Step 3: Write the implementation**

Add imports for `ChildSessionStartEvent`, `ChildSessionEndEvent`, `ChildSessionEvent` to `streaming.py`.

Add dispatch entries to `handle_event`:
```python
        elif isinstance(event, ChildSessionStartEvent):
            self._handle_child_session_start(event)
        elif isinstance(event, ChildSessionEndEvent):
            pass  # Silent — CLI just resets indentation tracking if needed
        elif isinstance(event, ChildSessionEvent):
            self._handle_child_session_event(event)
```

Add handlers:
```python
    def _handle_child_session_start(self, event: ChildSessionStartEvent) -> None:
        """Print delegate header with gear icon and agent name."""
        indent = "    " * (event.depth - 1)
        self._console.print(
            f"\n{indent}[bold cyan]\u2699 delegate \u2192 {event.agent_name}[/bold cyan]"
        )

    def _handle_child_session_event(self, event: ChildSessionEvent) -> None:
        """Render inner event with indentation based on nesting depth."""
        if event.inner is None:
            return
        indent = "    " * event.depth
        # Create an indented sub-console by capturing inner output and prefixing
        from io import StringIO
        inner_buf = StringIO()
        inner_console = Console(
            file=inner_buf,
            no_color=self._console.no_color if hasattr(self._console, 'no_color') else False,
            width=(self._console.width or 120) - (4 * event.depth),
        )
        inner_display = StreamingDisplay(
            console=inner_console,
            show_thinking=self._show_thinking,
        )
        inner_display.handle_event(event.inner)
        inner_output = inner_buf.getvalue()
        # Prefix each line with indentation
        for line in inner_output.split("\n"):
            if line:  # Skip empty lines to avoid trailing whitespace
                self._console.print(
                    f"{indent}{line}", markup=False, highlight=False
                )
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/cli/test_streaming.py -v
```

Expected: All PASS.

**Step 5: Commit**

```bash
git add src/amplifier_ipc/cli/streaming.py tests/cli/test_streaming.py
git commit -m "feat: render ChildSessionEvent with nesting indentation in StreamingDisplay"
```

---

### Task 13: Apply rendering to REPL and run command surfaces

**Files:**
- Modify: `src/amplifier_ipc/cli/repl.py`
- Modify: `src/amplifier_ipc/cli/commands/run.py`
- Modify: `tests/cli/test_repl.py`

**Step 1: Write the failing tests**

Add to `tests/cli/test_repl.py`:

```python
from amplifier_ipc.host.events import ToolCallEvent, ToolResultEvent, ChildSessionStartEvent


class TestHandleToolCallEvent:
    def test_handle_tool_call_event_no_error(self) -> None:
        """ToolCallEvent should be handled by handle_host_event without raising."""
        from amplifier_ipc.cli.repl import handle_host_event

        event = ToolCallEvent(tool_name="bash", arguments={"command": "ls"})
        # Should not raise
        handle_host_event(event)


class TestHandleToolResultEvent:
    def test_handle_tool_result_event_no_error(self) -> None:
        """ToolResultEvent should be handled by handle_host_event without raising."""
        from amplifier_ipc.cli.repl import handle_host_event

        event = ToolResultEvent(tool_name="bash", success=True, output="ok")
        # Should not raise
        handle_host_event(event)


class TestHandleChildSessionStart:
    def test_handle_child_session_start_no_error(self) -> None:
        """ChildSessionStartEvent should be handled without raising."""
        from amplifier_ipc.cli.repl import handle_host_event

        event = ChildSessionStartEvent(agent_name="explorer", session_id="abc", depth=1)
        # Should not raise
        handle_host_event(event)
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/cli/test_repl.py::TestHandleToolCallEvent tests/cli/test_repl.py::TestHandleToolResultEvent tests/cli/test_repl.py::TestHandleChildSessionStart -v
```

Expected: Tests pass silently (events are currently ignored — they fall through without error because `handle_host_event` has no `else` clause). If the tests pass, that's acceptable — but we still need to add rendering. The real test is visual: events should produce visible output. Add an assertion:

Actually, let's verify the events produce output:

```python
class TestHandleToolCallEvent:
    def test_handle_tool_call_produces_output(self) -> None:
        """ToolCallEvent should produce visible output on stdout."""
        from amplifier_ipc.cli.repl import handle_host_event
        import sys
        from io import StringIO

        event = ToolCallEvent(tool_name="bash", arguments={"command": "ls"})

        captured = StringIO()
        with patch.object(sys, "stdout", captured):
            handle_host_event(event)

        assert "bash" in captured.getvalue()
```

**Step 3: Write the implementation**

**3a. Update `repl.py`**

Add new event imports to `src/amplifier_ipc/cli/repl.py`:
```python
from amplifier_ipc.host.events import (
    ApprovalRequestEvent,
    ChildSessionEndEvent,
    ChildSessionEvent,
    ChildSessionStartEvent,
    CompleteEvent,
    ErrorEvent,
    HostEvent,
    StreamThinkingEvent,
    StreamTokenEvent,
    StreamToolCallStartEvent,
    TodoUpdateEvent,
    ToolCallEvent,
    ToolResultEvent,
)
```

Update `handle_host_event` to handle the new events. Since `repl.py` uses `click.echo` and `sys.stdout.write` (not Rich), we'll use a simple text-based approach:

```python
def handle_host_event(event: HostEvent, state: dict[str, Any] | None = None) -> None:
    """Process a single host event, writing output to stdout or updating state."""
    if isinstance(event, StreamTokenEvent):
        sys.stdout.write(event.token)
        sys.stdout.flush()
    elif isinstance(event, StreamThinkingEvent):
        click.echo(click.style(event.thinking, fg="cyan", dim=True), nl=False)
    elif isinstance(event, StreamToolCallStartEvent):
        click.echo(click.style(f"\n\u2699 {event.tool_name}", dim=True))
    elif isinstance(event, ToolCallEvent):
        click.echo(click.style(f"\n\U0001f527 Using tool: {event.tool_name}", bold=True))
        for key, value in list(event.arguments.items())[:10]:
            val_str = str(value)[:200]
            click.echo(click.style(f"   {key}: {val_str}", dim=True))
        if len(event.arguments) > 10:
            click.echo(click.style(f"   ... ({len(event.arguments) - 10} more)", dim=True))
    elif isinstance(event, ToolResultEvent):
        icon = "\u2705" if event.success else "\u274c"
        color = "green" if event.success else "red"
        click.echo(click.style(f"{icon} Tool result: {event.tool_name}", fg=color))
        if event.output:
            lines = event.output.split("\n")[:10]
            for line in lines:
                click.echo(click.style(f"   {line[:200]}", dim=True))
    elif isinstance(event, TodoUpdateEvent):
        if event.todos:
            completed = sum(1 for t in event.todos if t.get("status") == "completed")
            total = len(event.todos)
            click.echo(click.style(f"\n\u2610 Todo ({completed}/{total} done):", dim=True))
            symbols = {"completed": "\u2713", "in_progress": "\u25b6", "pending": "\u25cb"}
            for todo in event.todos[:7]:
                sym = symbols.get(todo.get("status", "pending"), "\u25cb")
                click.echo(click.style(f"  {sym} {todo.get('content', '')}", dim=True))
            if total > 7:
                click.echo(click.style(f"  ... and {total - 7} more", dim=True))
    elif isinstance(event, ChildSessionStartEvent):
        indent = "    " * (event.depth - 1)
        click.echo(click.style(f"\n{indent}\u2699 delegate \u2192 {event.agent_name}", fg="cyan", bold=True))
    elif isinstance(event, ChildSessionEvent):
        if event.inner is not None:
            # Render inner event text, then indent each line
            import io
            captured = io.StringIO()
            old_stdout = sys.stdout
            sys.stdout = captured
            try:
                handle_host_event(event.inner, state=state)
            finally:
                sys.stdout = old_stdout
            inner_text = captured.getvalue()
            indent = "    " * event.depth
            for line in inner_text.split("\n"):
                if line:
                    sys.stdout.write(f"{indent}{line}\n")
            sys.stdout.flush()
    elif isinstance(event, ChildSessionEndEvent):
        pass  # Silent
    elif isinstance(event, ErrorEvent):
        click.echo(click.style(f"\nError: {event.message}", fg="red"))
    elif isinstance(event, CompleteEvent):
        sys.stdout.write("\n")
        sys.stdout.flush()
        if state is not None:
            state["response"] = event.result
```

**3b. Update `commands/run.py`**

Add new event imports and update `_handle_event` in `src/amplifier_ipc/cli/commands/run.py`:

```python
from amplifier_ipc.host.events import (
    ApprovalRequestEvent,
    ChildSessionEndEvent,
    ChildSessionEvent,
    ChildSessionStartEvent,
    CompleteEvent,
    HostEvent,
    StreamThinkingEvent,
    StreamTokenEvent,
    StreamToolCallStartEvent,
    TodoUpdateEvent,
    ToolCallEvent,
    ToolResultEvent,
)
```

Replace `_handle_event` with a version that delegates to `handle_host_event` from `repl.py` to avoid duplication:

```python
def _handle_event(event: HostEvent) -> None:
    """Handle a single host event, writing output to stdout."""
    from amplifier_ipc.cli.repl import handle_host_event
    handle_host_event(event)
```

This reuses the REPL's handler, which already handles all event types. The only difference is `CompleteEvent` won't store state (since no `state` dict is passed), but that's fine for single-shot mode.

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/cli/test_repl.py -v
uv run pytest tests/cli/ -v
uv run pytest tests/ -v --timeout=30
```

Expected: All PASS.

**Step 5: Commit**

```bash
git add src/amplifier_ipc/cli/repl.py src/amplifier_ipc/cli/commands/run.py tests/cli/test_repl.py
git commit -m "feat: handle all new event types in REPL and run command CLI surfaces"
```

---

## Final Verification

After all 13 tasks, run the full test suite:

```bash
uv run pytest tests/ -v --timeout=60
```

Expected: All 770+ tests pass (plus the ~25 new tests added in this plan).

Also run type checks:

```bash
uv run pyright src/amplifier_ipc/host/events.py src/amplifier_ipc/host/host.py src/amplifier_ipc/host/spawner.py src/amplifier_ipc/cli/streaming.py src/amplifier_ipc/cli/repl.py
```

And run the orchestrator tests in the service:

```bash
cd /data/labs/amplifier-ipc && uv run pytest services/amplifier-foundation/tests/test_orchestrator.py -v
```

---

## Summary of Changes

| File | Lines Changed (approx) | What |
|---|---|---|
| `src/amplifier_ipc/host/events.py` | +60 | 6 new event classes |
| `src/amplifier_ipc/host/__init__.py` | +12 | Re-export new events |
| `src/amplifier_ipc/host/spawner.py` | +10 | `event_callback` parameter |
| `src/amplifier_ipc/host/host.py` | +50 | Queue, drain, callback, notification mapping |
| `services/.../orchestrators/streaming.py` | +30 | 3 new notifications |
| `src/amplifier_ipc/cli/streaming.py` | +120 | 6 new handlers |
| `src/amplifier_ipc/cli/repl.py` | +50 | Handle new events |
| `src/amplifier_ipc/cli/commands/run.py` | +5 | Delegate to repl handler |
| `tests/host/test_events.py` | +80 | 10 new event tests |
| `tests/host/test_spawner.py` | +60 | 3 callback tests |
| `tests/host/test_host.py` | +120 | Queue drain + spawn handler tests |
| `tests/cli/test_streaming.py` | +140 | 12 new rendering tests |
| `tests/cli/test_repl.py` | +30 | 3 new handler tests |
| `services/.../tests/test_orchestrator.py` | +80 | 3 notification tests |
