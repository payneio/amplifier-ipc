# Sub-Session CLI Rendering Design

## Goal

Make child session activity (delegate/spawn) visible in the CLI by forwarding child events through the parent's event stream and rendering them with proper formatting and nesting.

## Background

The IPC Host supports child sessions via `session_spawn` requests from the orchestrator. When an agent delegates work to a sub-agent, a child Host is created and runs independently. Currently, `_run_child_session()` in `spawner.py` iterates the child's events but only captures `CompleteEvent.result` — all other events (streaming tokens, tool calls, thinking blocks, todo updates) are silently discarded. The user sees nothing during sub-session execution, which can last minutes for complex delegations.

The reference CLI (`amplifier-app-cli`) solves this by sharing a `CLIDisplaySystem` across parent and child sessions. In the IPC architecture, we use async event streams instead of shared mutable state, so the solution must fit that model.

## Approach

**Yield child events through the parent's event stream** using a callback + queue pattern. This keeps the architecture consistent — the Host already communicates via yielded events, and the CLI already handles events uniformly through `handle_event`. Child events are wrapped in a `ChildSessionEvent` with a nesting depth, and the CLI renders the inner event with indentation proportional to depth.

This approach was chosen over passing a render callback because:
- It preserves the clean event stream architecture
- The CLI remains the only component that knows about rendering
- Events can be logged, recorded, or forwarded uniformly
- Nesting depth is explicit and composable (child of child works automatically)

## Architecture

Three layers are modified:

1. **Host layer** — New event types, event forwarding via callback + queue, spawn handler wiring
2. **Orchestrator layer** — New notifications (`stream.tool_call`, `stream.tool_result`, `stream.todo_update`) emitted alongside existing notifications, mapped to event types in the Host
3. **CLI layer** — Rich rendering for all new event types with formatting, colors, and nesting indentation

## Components

### 1. Event Forwarding from Child Sessions

Currently `_run_child_session()` iterates child events but discards everything except `CompleteEvent.result`:

```python
# Current behavior (spawner.py)
async for event in host.run(instruction):
    if isinstance(event, CompleteEvent):
        response = event.result
```

The fix adds an `event_callback` parameter to `_run_child_session()` and `spawn_child_session()`. The parent Host's spawn handler provides a callback that queues child events onto the parent's event stream.

```python
# Fixed behavior
async for event in host.run(instruction):
    if event_callback:
        event_callback(event)  # Forward to parent
    if isinstance(event, CompleteEvent):
        response = event.result
```

The parent's spawn handler creates a queue and callback:

```python
child_event_queue = asyncio.Queue()

def _forward_child_event(event):
    child_event_queue.put_nowait(ChildSessionEvent(depth=1, inner=event))
```

The parent's orchestrator loop in `_drive_orchestrator()` drains this queue alongside normal message processing (same pattern as `_provider_notification_queue`):

```python
# In the while True loop, after draining _provider_notification_queue:
while not self._child_event_queue.empty():
    yield self._child_event_queue.get_nowait()
```

Recursive nesting works naturally: if a child spawns its own child, the grandchild's events arrive as `ChildSessionEvent(depth=1, inner=...)` at the child, which the child's callback wraps again as `ChildSessionEvent(depth=2, inner=ChildSessionEvent(depth=1, inner=...))`. The CLI unwraps to get the effective depth.

### 2. New Event Types

Added to `src/amplifier_ipc/host/events.py`:

```python
class ToolCallEvent(HostEvent):
    """Emitted when a tool call starts, with full arguments for display."""
    tool_name: str = ""
    arguments: dict[str, Any] = {}

class ToolResultEvent(HostEvent):
    """Emitted when a tool call completes with its output."""
    tool_name: str = ""
    success: bool = True
    output: str = ""

class TodoUpdateEvent(HostEvent):
    """Emitted when the todo list changes."""
    todos: list[dict[str, Any]] = []
    status: str = ""  # "created", "updated", "listed"

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
    depth: int = 1
    inner: HostEvent = None  # requires model_config for arbitrary types
```

The existing `StreamToolCallStartEvent` is kept for backward compatibility. `ToolCallEvent` provides richer data (full arguments dict) for display purposes.

The orchestrator emits new notifications that the Host maps to these event types:

| Notification | Event Type | Trigger |
|---|---|---|
| `stream.tool_call` | `ToolCallEvent` | Tool call parsed with arguments |
| `stream.tool_result` | `ToolResultEvent` | Tool execution completes |
| `stream.todo_update` | `TodoUpdateEvent` | Todo tool call processed |

### 3. CLI Rendering

The CLI's event handlers (`streaming.py`, `repl.py`, `commands/run.py`) handle the new event types. All rendering uses Rich markup for colors and formatting.

**Tool calls:**
```
🔧 Using tool: bash
   command: "pytest tests/ -v"
   timeout: 30
```
- Arguments formatted as YAML-style key: value pairs
- Truncated to 10 lines with `... (N more)` indicator
- Single lines longer than 200 chars truncated with `...`

**Tool results:**
```
✅ Tool result: bash
   6 passed in 1.2s
```
- `✅` green for success, `❌` red for failures
- Output truncated to 10 lines

**Thinking blocks:**
```
🧠 Thinking...
══════════════════════════════════════════════════════════════
Thinking:
──────────────────────────────────────────────────────────────
I need to analyze the authentication module...
══════════════════════════════════════════════════════════════
```
- Thinking text rendered dim
- Border width: 60 chars or `terminal_width - 4`, whichever is smaller
- `═` double line for outer border, `─` single line for inner separator

**Todo lists:**
```
┌─ Todo ──────────────────────────────────────────────────────┐
│ ✓ Fix parser alignment                                      │
│ ▶ Testing lifecycle                                         │
│ ○ Add streaming events                                      │
│ ████████████░░░░░░░░░░░░ 1/3                                │
└─────────────────────────────────────────────────────────────┘
```
- Status symbols: `✓` completed (dim green), `▶` in_progress (bold cyan), `○` pending (dim gray)
- Progress bar: `█` green for completed, `░` dim gray for remaining, 24 chars wide
- Full mode for ≤7 items, condensed mode for >7 (shows counts by status)

**Child session events (indented 4 spaces per depth level):**
```
⚙ delegate → explorer
    🔧 Using tool: read_file
       file_path: "src/main.py"
    ✅ Tool result: read_file
       (42 lines)
    Explorer found: ...
```
- `ChildSessionStartEvent` renders `⚙ delegate → {agent_name}`
- All inner events indented by `"    " * depth` (4 spaces per level)
- `ChildSessionEndEvent` marks return to parent depth (no visible output, just resets indentation)
- Streaming tokens from child sessions rendered inline with indentation on new lines

## Data Flow

```
Orchestrator service                    Host                         CLI
     |                                   |                            |
     |--stream.tool_call_start--------->|                            |
     |                                   |--StreamToolCallStartEvent->|  🔧 Using tool: X
     |--stream.tool_call{args}--------->|                            |
     |                                   |--ToolCallEvent----------->|     arg1: val1
     |                                   |                            |
     |--request.tool_execute----------->|                            |
     |                                   |--[routes to tool svc]---->|
     |<-tool result--------------------|                            |
     |                                   |--ToolResultEvent--------->|  ✅ Tool result: X
     |                                   |                            |
     |--request.session_spawn---------->|                            |
     |                                   |--ChildSessionStartEvent-->|  ⚙ delegate → Y
     |                                   |                            |
     |                    [child host runs, yields events]           |
     |                                   |--ChildSessionEvent------->|      🔧 [indented]
     |                                   |--ChildSessionEvent------->|      ✅ [indented]
     |                                   |--ChildSessionEndEvent---->|  [back to parent]
     |<-spawn result--------------------|                            |
```

## Error Handling

- **Child session crashes**: `_run_child_session` already catches exceptions from `host.run()`. A `ChildSessionEndEvent` is emitted regardless (in a `finally` block) so the CLI always resets indentation.
- **Queue overflow**: The `child_event_queue` is unbounded (`asyncio.Queue()`) since events are small and drain quickly. If the parent's orchestrator loop is blocked, events accumulate in memory — acceptable since child sessions are bounded in duration.
- **Malformed events**: Unknown event types inside `ChildSessionEvent.inner` are silently ignored by the CLI (logged at debug level).
- **Recursive depth**: No hard limit on nesting depth, but indentation grows by 4 spaces per level. At depth 5+, content may be visually cramped — acceptable since deep nesting is rare in practice.

## Testing Strategy

- **Unit tests for event types**: Verify `ChildSessionEvent` serialization/deserialization with nested `HostEvent` payloads.
- **Unit tests for CLI rendering**: Test each renderer (tool call, tool result, thinking, todo, child session) with mock events, verify Rich markup output.
- **Integration tests for event forwarding**: Create a parent Host that spawns a child session, verify child events appear in the parent's event stream wrapped in `ChildSessionEvent`.
- **Manual verification**: Run a delegate-heavy workflow (e.g., brainstorming skill) and visually confirm tool calls, thinking blocks, and todo lists render correctly with proper nesting.

## Files to Modify

| File | Change |
|---|---|
| `src/amplifier_ipc/host/events.py` | Add `ToolCallEvent`, `ToolResultEvent`, `TodoUpdateEvent`, `ChildSessionStartEvent`, `ChildSessionEndEvent`, `ChildSessionEvent` |
| `src/amplifier_ipc/host/host.py` | Add child event queue, drain in orchestrator loop, provide callback to spawn handler |
| `src/amplifier_ipc/host/spawner.py` | Add `event_callback` parameter to `_run_child_session()` and `spawn_child_session()` |
| `src/amplifier_ipc/cli/streaming.py` | Rich rendering for all new event types |
| `src/amplifier_ipc/cli/repl.py` | Handle new event types in REPL mode |
| `src/amplifier_ipc/cli/commands/run.py` | Handle new event types in single-shot mode |
| `services/amplifier-foundation/src/amplifier_foundation/orchestrators/streaming.py` | Emit `stream.tool_call`, `stream.tool_result`, `stream.todo_update` notifications |

## Open Questions

- **Token streaming indentation**: When a child session streams tokens, new lines need the depth-based indent prefix. Should the CLI buffer partial lines to detect newlines, or insert indentation at the Rich console level?
- **Event deduplication**: `StreamToolCallStartEvent` (existing) and `ToolCallEvent` (new) both fire for tool calls. Should the CLI suppress the old event when the new one is available, or render both (name from the first, args from the second)?
- **Large tool outputs**: Tool results like `read_file` can be very long. The 10-line truncation handles this, but should we also add a byte-size cap (e.g., 2KB displayed)?
