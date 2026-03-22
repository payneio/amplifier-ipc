# Amplifier IPC Architecture Design

## Goal

Replace amplifier-lite's in-process, dynamic-import-based component loading with an IPC service architecture where every component runs as a separate process communicating via JSON-RPC 2.0 over stdio. This enables:

- Language-agnostic components (orchestrator could be Rust, Go, TypeScript)
- Dependency isolation via `uv tool install` (each service gets its own venv)
- Simple YAML configuration (reference service commands, not class paths)
- Elimination of `import_and_create()`, `mount()`, entry-point discovery, and all dynamic loading machinery

## Background

amplifier-lite currently has 12 packages in `packages/`. Only 5 have Python runtime code:

- **amplifier-foundation** — 1 orchestrator (StreamingOrchestrator), 1 context manager (SimpleContextManager), 12 hooks, 14+ tools
- **amplifier-providers** — 8 LLM provider adapters (anthropic, openai, gemini, ollama, azure, vllm, github copilot, mock)
- **amplifier-modes** — 1 hook (ModeHook) + 1 tool (ModeTool)
- **amplifier-skills** — 1 tool (SkillsTool)
- **amplifier-routing-matrix** — 1 hook (RoutingHook) + routing matrix YAML files

The remaining 7 packages are pure content — no Python, just `.md` agents, `.yaml` behaviors/recipes, and `.md` context docs.

The MCP conversation (documented in `working/ipc.md`) explored the full design space: single-venv vs multi-process, which components benefit from externalization, latency analysis (IPC overhead is negligible vs LLM call time), and arrived at the "everything is a service" model.

## Approach

Every amplifier-lite package becomes a standalone service process. A central host spawns services, routes JSON-RPC 2.0 messages between them over stdio, and manages service lifecycle. The orchestrator drives all logic — the host is a dumb message bus. No schema generation layer (protobuf, JSON Schema) — the shared `amplifier-ipc-protocol` Python library defines the wire protocol, decorators for component discovery, and protocol definitions for service authors.

## Architecture

```
amplifier-ipc-host (message bus / router)
    │
    ├── stdio ←→ Orchestrator service   (any language)
    ├── stdio ←→ Context Manager service (any language)
    ├── stdio ←→ Provider service        (any language)
    ├── stdio ←→ Tool service(s)         (any language)
    ├── stdio ←→ Hook service(s)         (any language)
    └── stdio ←→ Content-only service(s) (any language)
```

The host is a dumb router/message bus. The orchestrator drives all logic:

- The orchestrator sends requests to the host for tool calls, hook emits, context operations, and provider calls
- The host routes those requests to the appropriate service
- The host fans out hook emits to all registered hook services and chains results
- The host persists transcript messages as they flow through
- The host resolves content from services and assembles system prompts
- The host relays streaming notifications from the orchestrator to the CLI

The orchestrator keeps its full loop logic — DENY checking, ephemeral injection queuing, MODIFY detection, parallel tool dispatch — unchanged from the current StreamingOrchestrator. Only the transport changes: direct Python method calls become JSON-RPC requests through the host.

## Directory Structure

```
amplifier-ipc/
├── amplifier-ipc-protocol/          # Shared JSON-RPC 2.0 library
│   ├── pyproject.toml
│   └── src/amplifier_ipc_protocol/
│       ├── __init__.py
│       ├── server.py                # Generic Server base with component discovery
│       ├── client.py                # Client class (send requests, match responses)
│       ├── framing.py               # read_message() / write_message() over stdio
│       ├── errors.py                # JSON-RPC 2.0 error codes
│       ├── decorators.py            # @tool, @hook, @orchestrator, @context_manager, @provider
│       ├── protocols.py             # Protocol definitions (ToolProtocol, HookProtocol, etc.)
│       └── models.py                # Shared data models (ToolResult, HookResult, Message, etc.)
│
├── amplifier-ipc-host/              # The host / message bus / router
│   ├── pyproject.toml
│   └── src/amplifier_ipc_host/
│       ├── __main__.py              # CLI entry: amplifier-ipc run session.yaml
│       ├── router.py                # Message routing between services
│       ├── registry.py              # Service capability registry (from describe responses)
│       ├── lifecycle.py             # Spawn/teardown services per orchestrator loop
│       ├── content.py               # Content resolution + system prompt assembly
│       ├── persistence.py           # Session transcript/metadata persistence
│       └── config.py                # Session config + settings parsing
│
└── services/                        # One per current amplifier-lite package
    ├── amplifier-foundation/        # Orchestrator, context mgr, hooks, tools, content
    │   ├── pyproject.toml           # [project.scripts] amplifier-foundation-serve = ...
    │   └── src/amplifier_foundation/
    │       ├── __main__.py          # Entry point
    │       ├── server.py            # Uses generic Server from protocol lib
    │       ├── orchestrators/       # @orchestrator StreamingOrchestrator
    │       ├── context_managers/    # @context_manager SimpleContextManager
    │       ├── hooks/               # @hook ApprovalHook, LoggingHook, etc.
    │       ├── tools/               # @tool BashTool, ReadTool, etc.
    │       ├── agents/              # .md content files
    │       ├── behaviors/           # .yaml files
    │       ├── context/             # .md files
    │       ├── recipes/             # .yaml files
    │       └── sessions/            # .yaml files
    │
    ├── amplifier-providers/         # @provider Anthropic, OpenAI, etc.
    ├── amplifier-modes/             # @hook ModeHook + @tool ModeTool + content
    ├── amplifier-skills/            # @tool SkillsTool + content
    ├── amplifier-routing-matrix/    # @hook RoutingHook + routing matrices + content
    ├── amplifier-core/              # Content only (docs, contracts)
    ├── amplifier-amplifier/         # Content only (ecosystem meta)
    ├── amplifier-browser-tester/    # Content only (browser agents)
    ├── amplifier-design-intelligence/ # Content only (design agents)
    ├── amplifier-filesystem/        # Content only (editing guidance)
    ├── amplifier-recipes/           # Content only (recipe authoring)
    └── amplifier-superpowers/       # Content only (dev methodology)
```

## Components

### amplifier-ipc-protocol (Shared Library)

The shared library that every service depends on. Provides:

- **Framing** (`framing.py`): `read_message()` / `write_message()` over stdio — newline-delimited JSON
- **Server base** (`server.py`): Generic JSON-RPC server with stdin read loop, method dispatch, component discovery via decorated classes, automatic `describe` response generation, and content serving from package data directories
- **Client** (`client.py`): Send JSON-RPC requests over stdio, match responses by `id`
- **Decorators** (`decorators.py`): `@tool`, `@hook`, `@orchestrator`, `@context_manager`, `@provider` — attach `cls.__amplifier_component__` metadata for discovery
- **Protocol definitions** (`protocols.py`): Interface contracts so service authors know what to implement
- **Data models** (`models.py`): `ToolResult`, `HookResult`, `Message`, `ChatRequest`, `ChatResponse`, etc.
- **Error codes** (`errors.py`): Standard JSON-RPC 2.0 error codes

### amplifier-ipc-host (Message Bus)

The central process that spawns services and routes messages. Owns:

- **Service lifecycle** (`lifecycle.py`): Spawn at turn start, SIGTERM at turn end
- **Message routing** (`router.py`): Route orchestrator requests to the right service based on the capability registry
- **Hook fan-out** (`router.py`): When orchestrator emits a hook event, send to all registered hook services for that event, chain results (MODIFY), return final HookResult
- **Capability registry** (`registry.py`): Built from `describe` responses at startup — maps tool names, hook events, orchestrator/context_manager/provider names to their owning services
- **Content resolution** (`content.py`): Call `content.read` on services to resolve `@namespace:path` references, assemble system prompts
- **Session persistence** (`persistence.py`): Log messages to transcript as they flow through the router
- **Config parsing** (`config.py`): Read session YAML, settings overrides, build service spawn commands

The host does NOT:

- Interpret hook results (DENY, MODIFY, INJECT — that's the orchestrator's job)
- Drive the agent loop (that's the orchestrator)
- Hold conversation state (that's the context manager service)
- Call LLMs (that's the provider service)

### Service Packages (12 services)

Each service follows the same pattern. Content-only services discover zero components and only serve content files. Services with Python runtime code use decorators to mark components.

## Data Flow

### JSON-RPC 2.0 Wire Protocol

#### Handshake

On startup, the host sends `describe` to each service. Services respond with their full capabilities:

```json
{"jsonrpc": "2.0", "method": "describe", "id": 1}
```

Response:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "name": "amplifier-foundation",
    "capabilities": {
      "orchestrators": [{"name": "streaming"}],
      "context_managers": [{"name": "simple"}],
      "tools": [
        {"name": "bash", "description": "...", "input_schema": {}},
        {"name": "read_file", "description": "...", "input_schema": {}}
      ],
      "hooks": [
        {"name": "approval", "events": ["tool:pre"], "priority": 10},
        {"name": "logging", "events": ["*"], "priority": 100}
      ],
      "content": {
        "namespaces": ["foundation"],
        "paths": ["agents/explorer.md", "context/KERNEL_PHILOSOPHY.md"]
      }
    }
  }
}
```

#### Host-to-Service Methods

| Method | Params | Returns | Used by |
|---|---|---|---|
| `describe` | none | Capabilities object | Host at startup |
| `tool.execute` | `{name, input}` | `ToolResult` | Host routing orchestrator's tool calls |
| `hook.emit` | `{event, data}` | `HookResult` | Host fanning out hook events |
| `context.add_message` | `{message}` | `{ok: true}` | Host routing context calls |
| `context.get_messages` | `{provider_info}` | `{messages: [...]}` | Host routing context calls |
| `context.clear` | none | `{ok: true}` | Host routing context calls |
| `provider.complete` | `{request}` | `ChatResponse` | Host routing provider calls |
| `orchestrator.execute` | `{prompt, system_prompt, tools, hooks, config}` | Final response | Host starting the loop |
| `content.read` | `{path}` | `{content: "..."}` | Host during prompt assembly |
| `content.list` | `{prefix?}` | `{paths: [...]}` | Host discovering content |

#### Orchestrator-to-Host Methods (Requests)

| Method | Params | Host Action | Returns |
|---|---|---|---|
| `request.hook_emit` | `{event, data}` | Fan out to hook services, chain results | `HookResult` |
| `request.tool_execute` | `{name, input}` | Route to owning tool service | `ToolResult` |
| `request.context_add_message` | `{message}` | Route to context manager service | `{ok: true}` |
| `request.context_get_messages` | `{provider_info}` | Route to context manager service | `{messages: [...]}` |
| `request.context_clear` | none | Route to context manager service | `{ok: true}` |
| `request.provider_complete` | `{request}` | Route to provider service | `ChatResponse` |

#### Orchestrator-to-Host Notifications (Streaming)

| Method | Params | Host Action |
|---|---|---|
| `stream.token` | `{text}` | Relay to CLI |
| `stream.tool_call_start` | `{name, id}` | Relay to CLI |
| `stream.thinking` | `{text}` | Relay to CLI |

### Orchestrator-Host Bidirectional Communication

The orchestrator is both a service (receives `orchestrator.execute`) and a client (sends requests back to the host). This bidirectional communication over a single stdio channel works because:

1. The host sends `orchestrator.execute` as a JSON-RPC request with an `id`
2. The orchestrator sends `request.*` messages as JSON-RPC requests with their own `id`s — the host routes them and sends responses back
3. The orchestrator sends `stream.*` messages as JSON-RPC notifications (no `id`) — fire-and-forget
4. When the orchestrator loop completes, it sends the final JSON-RPC response matching the original `orchestrator.execute` request `id`

The orchestrator keeps its full loop logic from the current StreamingOrchestrator:

- DENY checking on `prompt:submit`, `provider:request`, and `tool:pre` hook results
- Ephemeral injection queuing from `prompt:submit` and `tool:post` hook results (`_pending_ephemeral_injections` stays as orchestrator instance state)
- MODIFY detection on `tool:post` hook results (object comparison on `data["result"]`)
- Parallel tool dispatch via `asyncio.gather` (each tool's pre-execute-post cycle runs concurrently)
- The only change: direct Python method calls become `self.client.request(...)` calls

### Service Lifecycle Per Turn

```
User types prompt
  -> Host SETUP:
    1. Read session config
    2. Spawn all service processes
    3. Send `describe` to each -> build routing table
    4. Resolve content via `content.read` -> assemble system prompt
    5. Send `orchestrator.execute` to orchestrator service

  -> ORCHESTRATOR LOOP (orchestrator drives, host routes):
    - Orchestrator sends request.* messages -> host routes to services
    - Host fans out hook emits, chains results, returns to orchestrator
    - Host persists messages as they flow through (transcript)
    - Orchestrator streams tokens via notifications -> host relays to CLI
    - Orchestrator completes -> sends final response

  -> Host TEARDOWN:
    1. Persist final transcript state
    2. SIGTERM all service processes
    3. Return response to CLI
    4. Wait for next prompt

User types next prompt
  -> Spawn everything again (fresh processes, no stale state)
```

Process startup cost (~200ms for heavy imports) is paid once per user turn — acceptable since the user just hit enter. Tearing down between turns means:

- No stale state across turns
- Versioning is simple — host can spawn different service versions per turn
- No concurrency concerns within services

## Service Implementation Pattern

### Component Discovery via Decorators

The `amplifier-ipc-protocol` library provides decorators that mark classes as components:

```python
from amplifier_ipc_protocol import tool, hook, orchestrator, context_manager, provider

@tool
class BashTool:
    name = "bash"
    description = "Execute shell commands"
    input_schema = {...}
    async def execute(self, input: dict) -> ToolResult: ...

@hook(events=["tool:pre"], priority=10)
class ApprovalHook:
    name = "approval"
    async def handle(self, event: str, data: dict) -> HookResult: ...

@orchestrator
class StreamingOrchestrator:
    name = "streaming"
    async def execute(self, prompt, config, client) -> str: ...

@context_manager
class SimpleContextManager:
    name = "simple"
    async def add_message(self, message) -> None: ...
    async def get_messages(self, provider_info) -> list: ...
    async def clear(self) -> None: ...

@provider
class AnthropicProvider:
    name = "anthropic"
    async def complete(self, request) -> ChatResponse: ...
```

Decorators attach metadata (e.g., `cls.__amplifier_component__ = "tool"`) without changing class behavior. The generic `Server` from the protocol library scans all `.py` files in the package at startup and finds decorated classes.

### Protocol Definitions

The protocol library includes protocol definitions (like the current `protocols.py`) so service authors know what to implement:

```python
class ToolProtocol:
    name: str
    description: str
    input_schema: dict
    async def execute(self, input: dict) -> ToolResult

class HookProtocol:
    name: str
    events: list[str]
    priority: int
    async def handle(self, event: str, data: dict) -> HookResult

class OrchestratorProtocol:
    name: str
    async def execute(self, prompt: str, config: dict, client: Client) -> str

class ContextManagerProtocol:
    name: str
    async def add_message(self, message: Message) -> None
    async def get_messages(self, provider_info: dict) -> list[Message]
    async def clear(self) -> None

class ProviderProtocol:
    name: str
    async def complete(self, request: ChatRequest) -> ChatResponse
```

### Generic Server

The `Server` base class from the protocol library handles:

- Stdin read loop and JSON-RPC framing
- Method dispatch to handler methods
- Component discovery (scan package for decorated classes)
- `describe` response generation from discovered components
- `content.read` / `content.list` from package data directories

Every service runs the same server code. A content-only service discovers zero components and only serves content.

### Package Layout Convention

Services follow the standard package layout. The server discovers components from conventional directories:

```
src/<package_name>/
    orchestrators/*.py    -> scan for @orchestrator classes
    context_managers/*.py -> scan for @context_manager classes
    tools/**/*.py         -> scan for @tool classes
    hooks/**/*.py         -> scan for @hook classes
    providers/**/*.py     -> scan for @provider classes
    agents/*.md           -> content
    behaviors/*.yaml      -> content
    context/**/*.md       -> content
    recipes/*.yaml        -> content
    sessions/*.yaml       -> content
```

## Session Configuration

```yaml
session:
  # Which services to spawn (command name from uv tool install)
  services:
    - amplifier-foundation-serve
    - amplifier-providers-serve
    - amplifier-modes-serve
    - amplifier-skills-serve
    - amplifier-routing-matrix-serve
    - amplifier-core-serve
    - amplifier-superpowers-serve

  # Which specific components to activate (from describe responses)
  orchestrator: streaming        # from foundation's describe
  context_manager: simple        # from foundation's describe
  provider: anthropic            # from providers' describe

  # All tools and hooks from all services available by default

  # Config overrides per component
  config:
    bash:
      timeout: 60
    streaming:
      max_iterations: 50
    anthropic:
      model: claude-sonnet-4-20250514
```

The host reads this, spawns all listed services, sends `describe` to each, builds the routing table, then picks the named orchestrator/context_manager/provider from the capabilities. All discovered tools and hooks across all services are available by default.

The `config` section provides per-component overrides. The host passes the relevant config subset when it activates a component (e.g., sends `{"method": "orchestrator.execute", "params": {..., "config": {"max_iterations": 50}}}` to the foundation service).

## Service Overrides (Local Development)

For development, you can override any service command via settings:

```yaml
# ~/.amplifier/settings.yaml
amplifier_ipc:
  service_overrides:
    amplifier-providers-serve:
      command: ["python", "-m", "amplifier_providers.server"]
      working_dir: ~/dev/amplifier-providers
```

Or using `uv run` for full environment control:

```yaml
amplifier_ipc:
  service_overrides:
    amplifier-providers-serve:
      command: ["uv", "run", "--directory", "~/dev/amplifier-providers",
                "python", "-m", "amplifier_providers.server"]
```

Resolution order:

1. **Project settings** (`.amplifier/settings.yaml` -> `amplifier_ipc.service_overrides`)
2. **User settings** (`~/.amplifier/settings.yaml` -> `amplifier_ipc.service_overrides`)
3. **Session config** service name -> PATH lookup (from `uv tool install`)

## Error Handling

Error handling follows JSON-RPC 2.0 conventions. Services return standard error responses for failures:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "error": {"code": -32603, "message": "Tool execution failed", "data": {...}}
}
```

The host relays errors transparently — it does not interpret or recover from them. The orchestrator decides how to handle errors (retry, abort, synthesize an error message to the user), just as it does today. Service process crashes are detected by the host via EOF on the service's stdout and reported to the orchestrator as error responses.

## Testing Strategy

- **amplifier-ipc-protocol**: Unit tests for framing (read/write JSON-RPC messages), decorator metadata attachment, component discovery from mock packages, and Server/Client round-trip over in-process pipes
- **amplifier-ipc-host**: Integration tests that spawn real service processes, send `describe`, verify routing, test hook fan-out and chaining, test content resolution, and test lifecycle (spawn/teardown)
- **Service packages**: Existing component tests (tool execution, hook handling, provider completion) remain unchanged — the component code is the same. Add thin integration tests verifying each service starts, responds to `describe`, and handles its methods correctly
- **End-to-end**: Full session tests that start the host with a session config, run a prompt through the full orchestrator loop, and verify the output matches expected behavior

## Scope: New Code vs Ported Code

### New code (~1500 lines)

- **amplifier-ipc-protocol/** — JSON-RPC 2.0 framing, generic Server with decorator-based discovery, Client class, protocol definitions, shared data models (~400-500 lines)
- **amplifier-ipc-host/** — config parsing, service spawning/teardown, message routing, hook fan-out, content resolution, system prompt assembly, session persistence (~800-1000 lines)

### Ported from amplifier-lite/packages/ with minimal changes

- All 12 service packages — same Python component code (tools, hooks, orchestrators, context managers, providers), same content files
- Changes per service:
  - Add `@tool`, `@hook`, `@orchestrator`, `@context_manager`, `@provider` decorators
  - Add `[project.scripts]` entry to `pyproject.toml`
  - StreamingOrchestrator: replace direct object calls with `self.client.request(...)` calls

### Not ported (replaced by IPC architecture)

- `Session` class (host replaces its wiring role)
- `Engine` / `environments.py` (replaced by `uv tool install` + service spawning)
- `ContentComposer` (rebuilt in host with service-based content resolution)
- `import_and_create()` machinery (eliminated entirely)
- `protocols.py` (replaced by decorators + wire protocol definitions in amplifier-ipc-protocol)

## Open Questions

1. **Hook ordering across services**: When multiple services register hooks for the same event, what determines execution order? Priority field in the hook descriptor is the current answer, but cross-service priority conflicts need a resolution strategy.

2. **Service crash recovery**: What happens when a service process crashes mid-turn? The host needs a strategy — retry the service? Abort the turn? Synthesize an error response to the orchestrator?

3. **Parallel tool calls across services**: If the orchestrator requests parallel tool execution and the tools live in different services, the host needs to dispatch to multiple services concurrently. This is straightforward but needs explicit handling in the router.

4. **Context manager state access over IPC**: The orchestrator currently accesses `context.messages` directly as a property. Over IPC, this becomes a request. The protocol needs to define what subset of context manager state is accessible and how frequently it can be queried without excessive round-trips.

5. **Provider streaming**: The current orchestrator calls `provider.stream()` which returns an async iterator. Over IPC, provider streaming would need to use JSON-RPC notifications flowing back through the host to the orchestrator. This is a more complex flow than simple request/response and needs its own protocol design.
