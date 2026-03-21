# Amplifier IPC Providers and Protocol Extensions Design

## Goal

Resolve the three remaining open protocol questions (provider streaming, cross-service shared state, sub-session spawning), implement all 8 LLM providers as IPC services, and prove the full stack works end-to-end with a real LLM.

## Background

The amplifier-ipc spec (March 2026) established the core architecture: JSON-RPC 2.0 over stdio, host as message bus, orchestrator-driven agent loop. Three protocol questions were left open:

1. **Provider streaming** — how streaming tokens flow from a provider service back through the host to the orchestrator and CLI
2. **Cross-service shared state** — how tools and hooks that previously shared in-process state (e.g., `session.state["todo_state"]`) communicate over IPC
3. **Sub-session spawning** — how `DelegateTool` and `TaskTool` create child sessions when every component runs in a separate process

Additionally, only the `mock` provider was implemented. The 7 real providers (Anthropic, OpenAI, Gemini, Azure OpenAI, Ollama, vLLM, GitHub Copilot) existed as stubs.

This design resolves all three protocol questions and defines the provider porting strategy.

## Approach

Three work streams executed in order:

1. **Protocol extensions** — add wire protocol methods for streaming, state, and sub-session spawning
2. **Anthropic provider** — faithful port from upstream as the reference implementation
3. **Remaining providers + smoke test** — pattern-match from Anthropic, then prove the full chain works

## Architecture

### Architectural Shift: Registry and Definitions Move to Host

Registry and definitions modules move from `amplifier-ipc-cli` to `amplifier-ipc-host`. The host owns session lifecycle including definition resolution. The CLI becomes a thin UI shell.

This enables:
- Host handles sub-session spawning directly (no CLI involvement)
- Headless operation (testing, embedded use)
- Tools can delegate without a terminal attached

The CLI retains `$AMPLIFIER_HOME` filesystem management (alias files, cached definitions) and user-facing commands (`discover`, `register`, `install`). The host gains definition resolution and the ability to spawn child sessions autonomously.

## Components

### Protocol Extension 1: Provider Streaming

The provider emits `stream.provider.*` notifications while processing a `provider.complete` request. The host relays these to the orchestrator. The orchestrator re-emits them as `stream.*` notifications to the host, which surfaces them to the CLI via the event stream.

The orchestrator MUST be in the streaming path because it processes individual streaming events: fires `content_block:start`/`content_block:end` hooks, handles thinking blocks, accumulates text for the final response.

#### Data Flow

```
Provider service
  → (stream.provider.token notification)
  → Host
  → (relay to orchestrator)
  → Orchestrator
  → (stream.token notification)
  → Host
  → (event)
  → CLI
```

The final `ChatResponse` (with full content, usage, tool_calls) is still returned as the normal JSON-RPC response to the `provider.complete` request.

#### New Wire Protocol Methods

All notifications — no `id` field, fire-and-forget:

| Method | Direction | Params | Host Action |
|---|---|---|---|
| `stream.provider.token` | Provider → Host | `{text}` | Relay to orchestrator |
| `stream.provider.thinking` | Provider → Host | `{text}` | Relay to orchestrator |
| `stream.provider.content_block_start` | Provider → Host | `{type, index}` | Relay to orchestrator |
| `stream.provider.content_block_end` | Provider → Host | `{type, index}` | Relay to orchestrator |

Non-streaming providers return the response directly with no notifications. The orchestrator handles both cases transparently. The provider decides whether to stream based on its config.

### Protocol Extension 2: Cross-Service Shared State

The host's session already has persistence (`transcript.jsonl` + `metadata.json`). This extends it with a state dict loaded at turn start, saved at turn end, stored as `state.json`.

#### New Wire Protocol Methods

| Method | Direction | Params | Returns |
|---|---|---|---|
| `state.get` | Service → Host | `{key}` | `{value}` |
| `state.set` | Service → Host | `{key, value}` | `{ok: true}` |
| `request.state_get` | Orchestrator → Host | `{key}` | `{value}` |
| `request.state_set` | Orchestrator → Host | `{key, value}` | `{ok: true}` |

#### Host Behavior

The host:
- Loads `state.json` at turn start (alongside transcript)
- Serves `state.get`/`state.set` to any service that requests it
- Serves `request.state_get`/`request.state_set` from the orchestrator
- Persists `state.json` at turn end

#### Example

`TodoTool` calls `state.set("todo_state", {...})` after mutations. `todo_display` and `todo_reminder` hooks call `state.get("todo_state")` when they fire. Both go through the host — no shared memory needed.

### Protocol Extension 3: Sub-Session Spawning

The host handles sub-session spawning directly. When the orchestrator sends `request.session_spawn`, the host resolves child agent definitions, builds child config, spawns child services, runs child orchestrator, and returns the result.

This design was validated against v1's implementation (~6,000 lines across 13 files in 3 repos). The IPC design is architecturally simpler because process isolation eliminates the need for manual capability propagation, but all 10 essential v1 features are preserved.

#### New Wire Protocol Methods

| Method | Direction | Params | Returns |
|---|---|---|---|
| `request.session_spawn` | Orchestrator → Host | See params below | `{session_id, response, turn_count, metadata}` |
| `request.session_resume` | Orchestrator → Host | `{session_id, instruction}` | `{session_id, response, turn_count, metadata}` |

#### request.session_spawn Params

```python
{
    "agent": str,              # agent name, "self", or "namespace:path"
    "instruction": str,        # what the child should do

    # Context inheritance
    "context_depth": "none" | "recent" | "all",
    "context_scope": "conversation" | "agents" | "full",
    "context_turns": int | None,

    # Component filtering
    "exclude_tools": list[str] | None,    # blocklist
    "inherit_tools": list[str] | None,    # allowlist (mutually exclusive with exclude)
    "exclude_hooks": list[str] | None,
    "inherit_hooks": list[str] | None,
    "agents": "all" | "none" | list[str] | None,  # sub-agent access control

    # Provider preferences
    "provider_preferences": list[dict] | None,  # [{provider, model}] with glob patterns
    "model_role": str | None,
}
```

#### Host Spawn Flow

1. Generate child session ID with lineage (`{parent_span}-{child_span}_{agent}`) — W3C trace context style
2. If `agent="self"`, clone parent config; otherwise resolve child agent definitions
3. Merge configs — child overrides parent, tool/hook lists merge by ID
4. Apply tool/hook filtering (`exclude_tools` removes delegate tool by default to prevent infinite recursion)
5. Apply provider preferences
6. Format parent context according to depth/scope params
7. Spawn child services, run child orchestrator with instruction
8. Propagate cancellation from parent to child
9. Persist child transcript for resume
10. Return `{session_id, response, turn_count, metadata}`

#### Self-Delegation

When `agent="self"`, the host reuses parent config with depth tracking. `max_self_delegation_depth=3`, enforced by host. Exceeding the limit returns an error response.

#### Fork

`request.session_fork` (snapshot transcript at turn N, create new session ID) is a separate persistence operation. It can be added later without protocol changes.

### 10 Essential V1 Features Preserved

These features were identified by auditing v1's implementation (~6,000 lines across `amplifier-lite`, `amplifier-lite-cli`, and `amplifier-module-tool-agents`):

| # | Feature | IPC Mechanism |
|---|---|---|
| 1 | Config merge semantics | Tool/hook lists merge by ID, not replace |
| 2 | Tool/hook filtering | Sub-agents don't get delegate tool (prevents infinite recursion) |
| 3 | Agent access control | `agents` param restricts which sub-agents are available |
| 4 | Context depth/scope | 2-parameter system (`context_depth` × `context_scope`) |
| 5 | Self-delegation with depth limit | `max_self_delegation_depth=3`, host-enforced |
| 6 | Cancellation propagation | Ctrl+C reaches nested agents via host |
| 7 | Session resume | `request.session_resume` with persisted transcript |
| 8 | Provider preference override | Glob patterns on model names in `provider_preferences` |
| 9 | Session ID lineage | W3C trace context style for debugging |
| 10 | Fork at turn N | Deferred — `request.session_fork` as future addition |

### Anthropic Provider Implementation (Reference)

Faithful port from upstream (`amplifier-module-provider-anthropic`, 2,449 lines). Only change what IPC requires.

#### What Changes

- **Imports:** `amplifier_core.*` → `amplifier_ipc_protocol.*` (direct swap)
- **Lifecycle:** Drop `mount()`, `__amplifier_module_type__`, coordinator references. Add `@provider` decorator.
- **`__init__`:** Takes `config: dict | None` instead of `(api_key, config, coordinator)`. Reads API key from `config["api_key"]` or `ANTHROPIC_API_KEY` env var.
- **Dropped methods:** `get_info()`, `list_models()`, `close()` — not in IPC protocol yet. Note in README.md for future.

#### What Stays Identical

- `_convert_messages()` — Amplifier messages → Anthropic API format
- `_convert_tools_from_request()` — tool spec conversion
- `_convert_to_chat_response()` — Anthropic response → ChatResponse with TextBlock/ThinkingBlock/ToolCallBlock
- Tool-result repair logic (inject synthetic error results for missing tool_results)
- Error translation (AnthropicRateLimitError → JSON-RPC errors)
- Rate limit header tracking
- `retry_with_backoff` logic
- Prompt caching with `cache_control` on system blocks
- Extended thinking support

#### Estimated Size

~800–1000 lines (vs 2,449 upstream). The reduction comes from dropping v1 lifecycle machinery, not functionality.

### Remaining 6 Providers

After Anthropic is proven, the remaining 6 follow the same porting recipe:

| Provider | Upstream Size | SDK | Notes |
|---|---|---|---|
| OpenAI | 2,335 + 523 lines | `openai` (Responses API) | Most complex — continuation logic, native tools, reasoning blocks |
| Gemini | 1,360 lines | `google-genai` | Synthetic tool call IDs, thinking_budget, image support |
| Azure OpenAI | ~similar to OpenAI | `openai` + `azure-identity` | OpenAI wrapper with Azure auth |
| Ollama | ~moderate | `ollama` | Local models, simpler API |
| vLLM | ~moderate | `openai` (compatible API) | Uses OpenAI SDK against vLLM endpoint |
| GitHub Copilot | ~moderate | `openai` + `github-copilot-sdk` | OpenAI-compatible with Copilot auth |

#### Porting Recipe (Per Provider)

1. Copy upstream source
2. Swap imports (`amplifier_core.*` → `amplifier_ipc_protocol.*`)
3. Drop `mount()`, coordinator refs, `get_info()`, `list_models()`, `close()`
4. Add `@provider` decorator
5. Change `__init__` to take `config: dict | None`
6. Fix any field name differences inline
7. Note dropped functionality in README.md

Azure, vLLM, and Copilot are OpenAI-compatible — preserve shared code relationships from upstream. If upstream has shared base classes or utilities, keep them shared in the IPC port.

#### Upstream Source References

| Provider | Repository |
|---|---|
| Anthropic | `microsoft/amplifier-module-provider-anthropic` |
| OpenAI | `microsoft/amplifier-module-provider-openai` |
| Azure OpenAI | `microsoft/amplifier-module-provider-azure-openai` |
| Gemini | `microsoft/amplifier-module-provider-gemini` |
| vLLM | `microsoft/amplifier-module-provider-vllm` |
| Ollama | `microsoft/amplifier-module-provider-ollama` |
| GitHub Copilot | `microsoft/amplifier-module-provider-github-copilot` |
| Mock | `microsoft/amplifier-module-provider-mock` |

## Data Flow

### Provider Streaming (Full Path)

```
1. Orchestrator sends request.provider_complete to Host
2. Host routes to Provider service as provider.complete
3. Provider calls LLM API with streaming enabled
4. For each streaming chunk:
   a. Provider sends stream.provider.token notification to Host
   b. Host relays to Orchestrator (forwarding notification)
   c. Orchestrator processes (fires hooks, accumulates text)
   d. Orchestrator sends stream.token notification to Host
   e. Host surfaces as event to CLI
   f. CLI renders token to terminal
5. LLM stream completes
6. Provider returns ChatResponse as JSON-RPC response to provider.complete
7. Host relays ChatResponse back to Orchestrator as response to request.provider_complete
```

### Sub-Session Spawning (Full Path)

```
1. Orchestrator sends request.session_spawn to Host
2. Host resolves child agent definition (from its own registry)
3. Host generates child session ID with lineage
4. Host merges parent + child configs, applies filtering
5. Host spawns child service processes
6. Host sends describe to child services, builds child routing table
7. Host resolves child content, assembles child system prompt
8. Host sends orchestrator.execute to child orchestrator
9. Child orchestrator runs full loop (tool calls, hooks, provider, streaming)
10. Child orchestrator returns final response
11. Host persists child transcript
12. Host tears down child services
13. Host returns {session_id, response, turn_count, metadata} to parent orchestrator
```

### Cross-Service State (Within a Turn)

```
1. Host loads state.json at turn start
2. Tool executes, calls state.set("todo_state", {...}) → Host updates in-memory dict
3. Hook fires, calls state.get("todo_state") → Host returns current value
4. Another hook fires, calls state.get("todo_state") → Host returns same value
5. Turn ends, Host persists state.json
```

## Error Handling

### Provider Errors

Provider-specific errors (rate limits, auth failures, model errors) are translated to JSON-RPC error responses. The Anthropic provider maps `AnthropicRateLimitError` to appropriate error codes. Other providers follow the same pattern for their SDK-specific exceptions.

### Streaming Errors

If a provider crashes mid-stream, the host detects EOF on the provider's stdout. The pending `provider.complete` request receives a JSON-RPC error response. The orchestrator handles this through its existing error handling — it can retry, abort, or surface the error to the user.

### Sub-Session Errors

Child session failures (service crash, orchestrator error, depth limit exceeded) are returned as error responses to `request.session_spawn`. The parent orchestrator's delegate tool handles these as tool execution failures.

### State Errors

`state.get` for a nonexistent key returns `{value: null}`. `state.set` with non-JSON-serializable values returns a JSON-RPC error.

## Testing Strategy

### End-to-End Smoke Test

After Anthropic is wired up:

1. Create a foundation agent definition YAML pointing to the local foundation service
2. `amplifier-ipc register` the agent definition
3. `amplifier-ipc run --agent foundation "What files are in the current directory?"`
4. Verify the full chain:
   - Definition resolves
   - Host spawns services
   - Orchestrator runs
   - Anthropic provider calls the real API
   - LLM responds
   - Tool calls work (read_file, bash, etc.)
   - Streaming tokens display live
   - Response completes

This tests: CLI → registry → definitions → host → service spawning → describe → content resolution → system prompt assembly → orchestrator loop → provider (Anthropic) → tool execution → hook fan-out → streaming → persistence.

### CI/Automated Testing

Same flow with mock provider (already works) — no API key needed. The mock provider returns canned responses that exercise tool calls and streaming.

### Provider-Specific Tests

Each provider gets:
- Unit tests for message conversion (`_convert_messages`, `_convert_tools_from_request`, `_convert_to_chat_response`)
- Unit tests for error translation
- Integration test with real API (gated behind `--run-live` flag and API key env var)

### Protocol Extension Tests

- **Streaming:** Verify notification flow from provider through host to orchestrator
- **State:** Verify get/set round-trip, persistence across turns, null for missing keys
- **Sub-session:** Verify spawn, resume, self-delegation depth limit, cancellation propagation

## Open Questions

| Question | Notes |
|---|---|
| **CLI↔Host error propagation** | How service crashes surface through the event stream for streaming providers. If the provider dies mid-stream, the CLI needs to know the turn failed. |
| **Provider config injection** | How the host passes provider-specific config (model name, temperature, etc.) from the session config to the provider's `__init__`. The `@provider` decorator receives `config: dict | None` but the exact shape per provider needs definition. |
| **Streaming backpressure** | If the CLI can't consume events fast enough, what happens? Probably not an issue with stdio, but worth noting for future networked transports. |
| **Registry/definitions migration plan** | Exact refactoring steps for moving registry and definitions from CLI to host without breaking existing CLI tests. |