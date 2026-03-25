# IPC Event Parity Design

## Goal

Restore full event coverage from the old Amplifier kernel to the new IPC system. The old system emits 41 canonical events + ~8 module-level custom events; the new IPC system only fires 10. Thirty-five events are either completely missing or subscribed-to-but-never-fired. This design restores full event parity across 5 phases.

## Background

The old Amplifier kernel defined a comprehensive event system that hooks relied on for logging, redaction, routing, deprecation warnings, and UI streaming. When the system was re-architected around IPC, most event emission sites were not carried forward. The result:

- **6 hooks subscribe to `session:start`/`session:end` but never receive them.** RoutingMatrixHook silently fails to initialize because it depends on `session:start`.
- **`provider:response` never fires.** LoggingHook, StreamingUIHook, and RedactionHook subscribe but get nothing. The audit log (`events.jsonl`) has no record of successful provider responses.
- **`content_block:start/end` has a naming mismatch.** Hooks subscribe to `content_block:start` (underscore) but the orchestrator defines `content:block_start` (colon). Neither fires anyway.
- **`events.jsonl` is partially deaf.** LoggingHook receives 7 of its 10 subscribed events.

## Approach: Hybrid Constants

**Canonical events (41):** Defined as constants in a shared module in `amplifier-ipc-protocol`. Both Host and services import from it.

**Module-specific events (`delegate:*`, `deprecation:*`):** Defined as string constants within individual service modules. Modules are independently deployable, so their custom events live with them.

This matches the old system pattern (kernel constants + module-defined custom events) and prevents the naming mismatch bug by giving both emitters and subscribers a single source of truth.

## Architecture: Two Event Emitter Locations

### Host Emits Session-Level Lifecycle Events

The Host owns the Router and dispatches hook events directly through it (no IPC round-trip). Session lifecycle events (`session:start`, `session:end`, and later `session:fork`, `session:resume`, cancellation) are Host-level concerns — they represent passing control to/from the orchestrator.

The Host gains a helper method (`_emit_hook_event(event_name, data)`) that calls through to the Router's hook dispatch — the same code path that `request.hook_emit` ultimately reaches, just without IPC indirection.

### Orchestrator Emits Turn-Level Events

Everything inside the prompt-response loop (provider calls, tool invocations, content blocks, thinking, etc.) continues to be emitted by the streaming orchestrator via the existing `_hook_emit()` mechanism.

### Secret Redaction

No special logic in the Host. The `raw` field in `session:start` is emitted with the full config. RedactionHook (which already subscribes to `session:start`) handles redaction via the normal `MODIFY` hook response.

## Event Inventory

### Canonical Events (41)

| Category | Event | Payload |
|---|---|---|
| **Session Lifecycle** | `session:start` | `{session_id, parent_id}` + optional `{metadata}`, `{raw}` |
| | `session:end` | `{session_id, status}` (completed/cancelled/failed) |
| | `session:fork` | `{parent, session_id}` + optional `{metadata}`, `{raw}` |
| | `session:resume` | identical to `session:start` |
| **Prompt** | `prompt:submit` | `{prompt}` |
| | `prompt:complete` | `{prompt}` |
| **Planning** | `plan:start` | |
| | `plan:end` | |
| **Provider** | `provider:request` | emitted before provider call |
| | `provider:response` | `{provider, response, usage}` |
| | `provider:retry` | between retry attempts |
| | `provider:error` | on final failure after retries |
| | `provider:throttle` | |
| | `provider:tool_sequence_repaired` | |
| | `provider:resolve` | |
| **LLM** | `llm:request` | |
| | `llm:response` | |
| **Content Blocks** | `content_block:start` | |
| | `content_block:delta` | |
| | `content_block:end` | |
| **Thinking** | `thinking:delta` | |
| | `thinking:final` | |
| **Tools** | `tool:pre` | `{tool_name, tool_call_id, tool_input}` |
| | `tool:post` | `{tool_name, tool_call_id, tool_input, result}` |
| | `tool:error` | `{tool_name, tool_call_id, error}` |
| **Context** | `context:pre_compact` | |
| | `context:post_compact` | |
| | `context:compaction` | |
| | `context:include` | |
| **Orchestrator** | `orchestrator:complete` | `{orchestrator, turn_count, status}` |
| | `execution:start` | |
| | `execution:end` | |
| **User** | `user:notification` | |
| **Artifacts** | `artifact:write` | |
| | `artifact:read` | |
| **Policy/Approvals** | `policy:violation` | |
| | `approval:required` | |
| | `approval:granted` | |
| | `approval:denied` | |
| **Cancellation** | `cancel:requested` | |
| | `cancel:completed` | `{was_immediate}` or `{was_immediate, error}` |

### Module-Level Custom Events

| Module | Event | Payload |
|---|---|---|
| **Delegate** | `delegate:agent_spawned` | `{agent, sub_session_id, parent_session_id, tool_call_id, parallel_group_id}` |
| | `delegate:agent_completed` | same fields |
| | `delegate:agent_resumed` | `{session_id, parent_session_id, tool_call_id, parallel_group_id}` |
| | `delegate:error` | `{agent, sub_session_id, parent_session_id, error, tool_call_id, parallel_group_id}` |
| **Deprecation** | `deprecation:warning` | `{bundle_name, replacement, severity, source_files}` |

### IPC-Only Events (not in old system)

| Event | Payload |
|---|---|
| `orchestrator:rate_limit_delay` | `{delay_ms, configured_ms, elapsed_ms, iteration}` |

## Current IPC Status

10 of ~49 total events are properly emitted today:

- `prompt:submit`, `prompt:complete`
- `provider:request`, `provider:error`, `provider:retry`
- `tool:pre`, `tool:post`, `tool:error`
- `orchestrator:complete`
- `orchestrator:rate_limit_delay` (IPC-only, not in old system)

## Components

### Events Constants Module

**Location:** `amplifier-ipc-protocol/src/amplifier_ipc_protocol/events.py`

All 41 canonical event constants, with the same constant names and string values as old `amplifier_core.events`. Defined upfront in Phase 1 so Phases 2–5 just add emission sites without touching the constants module.

### Host Hook Emission Path

A helper method on the Host (`_emit_hook_event(event_name, data)`) that dispatches hook events through the Router. This is the same code path that `request.hook_emit` reaches, without IPC indirection. Used for session lifecycle events.

### Orchestrator Emission Sites

The streaming orchestrator's existing `_hook_emit()` mechanism, extended with new emission calls at the appropriate points in the prompt-response loop.

## Data Flow

### Session Lifecycle (Host-emitted)

```
Host.run() starts
  → Host._emit_hook_event("session:start", {session_id, parent_id, ...})
    → Router dispatches to subscribed hooks
      → RedactionHook receives, strips secrets from `raw` via MODIFY response
      → RoutingMatrixHook receives, initializes routing
      → LoggingHook receives, writes to events.jsonl
  → Orchestrator runs (emits turn-level events via _hook_emit)
  → Host._emit_hook_event("session:end", {session_id, status})
    → Router dispatches to subscribed hooks
```

### Provider Response (Orchestrator-emitted)

```
Orchestrator._hook_emit("provider:request", {...})
  → provider.complete() call
    → Success: _hook_emit("provider:response", {provider, response, usage})
    → Failure (after retries): _hook_emit("provider:error", {...})
```

### Content Blocks (Orchestrator-emitted)

```
Stream begins content block
  → _hook_emit("content_block:start", {...})
  → [content_block:delta events in Phase 2]
  → _hook_emit("content_block:end", {...})
```

## Phasing

### Phase 1: Unblock Existing Hooks

**Events:** `session:start`, `session:end`, `provider:response`, fix `content_block:start/end` naming

**Deliverables:**

1. **Events constants module** — Create `amplifier-ipc-protocol/src/amplifier_ipc_protocol/events.py` with all 41 canonical event constants. Same names and values as old `amplifier_core.events`.

2. **Host emits `session:start`** — At the top of `Host.run()`, before handing off to the orchestrator. Payload: `{session_id, parent_id, metadata (if present), raw (full config)}`. `parent_id` is `None` for root sessions. Redaction handled by RedactionHook.

3. **Host emits `session:end`** — In the `finally` block of `Host.run()`. Payload: `{session_id, status}` where status is `"completed"`, `"cancelled"`, or `"failed"` based on how execution ended.

4. **Orchestrator emits `provider:response`** — In `streaming.py`, right after a successful `provider.complete` call. Payload: `{provider, response, usage}`. Lifecycle becomes: `provider:request` → call → `provider:response` (success) or `provider:error` (failure after retries).

5. **Fix `content_block:start/end` naming** — Adopt old naming: `content_block:start` and `content_block:end` (underscore style, matching hook subscriptions). Orchestrator imports from constants module instead of defining its own mismatched constants. Emit at the same sites where HostEvent notifications are already sent. Skip `content_block:delta` for Phase 1.

### Phase 2: Complete the Core Loop (~10 events)

`llm:request/response`, `content_block:delta`, `thinking:delta/final`, `execution:start/end`, `provider:throttle/resolve/tool_sequence_repaired`.

All constants already defined in Phase 1 — just add emission sites in the orchestrator.

### Phase 3: Session Lifecycle + Cancellation (~5 events)

`session:fork`, `session:resume`, `cancel:requested/completed`, `user:notification`.

Host emits lifecycle events; cancellation may involve both Host and orchestrator.

### Phase 4: Subsystem Events (~8 events)

`context:pre_compact/post_compact/compaction/include`, `plan:start/end`, `artifact:write/read`.

These depend on the subsystems themselves being implemented. Constants already defined; emission added when subsystems land.

### Phase 5: Policy + Delegation (~8 events)

`approval:required/granted/denied`, `policy:violation`, `delegate:agent_spawned/completed/resumed/error`.

Reconcile the IPC approval notification mechanism with the old hook-event pattern. Delegate events are module-level custom events defined within the delegate service per the hybrid approach.

## Error Handling

- Hook emission failures must not crash the Host or orchestrator. Errors during `_emit_hook_event` are logged but do not propagate.
- If a hook returns an error via its `MODIFY` response (e.g., RedactionHook fails), the event is emitted unmodified and the error is logged.
- `session:end` is emitted in a `finally` block to ensure it fires even when the session fails or is cancelled.

## Testing Strategy

**Per phase:**

- **Unit tests:** Verify events are emitted with correct payloads at the right lifecycle points.
- **Integration tests:** Verify hooks actually receive the events they subscribe to.
- **Regression test:** Specific test for the `content_block` naming mismatch pattern (subscribe with one name, emit with another = silent failure).

**Phase 1 specifics:**

- Test that `session:start` is received by RoutingMatrixHook and it initializes correctly.
- Test that `session:end` fires with the correct status for completed, cancelled, and failed sessions.
- Test that `provider:response` is received by LoggingHook and written to `events.jsonl`.
- Test that `content_block:start/end` constants match the subscription strings in existing hooks.

## Open Questions

1. What payload should `content_block:start/end` carry in the IPC system? The old system had block type and index — need to verify what the IPC streaming path has available.
2. Should `orchestrator:rate_limit_delay` (IPC-only, not in old system) be added to the canonical constants or kept as an orchestrator-local constant?
3. For Phase 3 cancellation events: should the Host or orchestrator emit `cancel:requested`/`cancel:completed`? Likely Host for requested, orchestrator for completed, but needs design.
