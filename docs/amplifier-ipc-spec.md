# Amplifier IPC Specification

> **Status:** Authoritative source-of-truth for the amplifier-ipc architecture.
> This document supersedes all design documents in `docs/plans/` and `docs/design-direction.md`.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Architecture](#2-architecture)
3. [Registration and Discovery](#3-registration-and-discovery)
4. [Agent and Behavior Definitions](#4-agent-and-behavior-definitions)
5. [Wire Protocol](#5-wire-protocol)
6. [Data Models](#6-data-models)
7. [Component Types](#7-component-types)
8. [Service Implementation](#8-service-implementation)
9. [Host](#9-host)
10. [Session Configuration](#10-session-configuration)
11. [Service Inventory](#11-service-inventory)
12. [CLI](#12-cli)
13. [Error Handling](#13-error-handling)
14. [Testing Strategy](#14-testing-strategy)
15. [Project Structure](#15-project-structure)
16. [Open Questions and Future Work](#16-open-questions-and-future-work)

---

## 1. Overview

Amplifier IPC replaces amplifier-lite's in-process, dynamic-import-based component loading with an **IPC service architecture** where every component runs as a separate process communicating via **JSON-RPC 2.0 over stdio**. A central host process orchestrates all tools and services, each running in its own process.

### Goals

- **Language-agnostic components** — orchestrator, tools, hooks, providers can be written in any language (Python, Rust, Go, TypeScript)
- **Dependency isolation** — each service gets its own virtualenv via `uv`, eliminating dependency conflicts
- **Simple YAML configuration** — reference service commands and definition URLs, not class paths
- **Composable agents and behaviors** — a rich definition model where agents compose behaviors by URL, each with independent service backing
- **Micro-service future** — the IPC boundary sets up a natural migration path to networked services

### What It Replaces

Amplifier IPC eliminates:
- `import_and_create()` machinery and all dynamic loading
- The `Session` class (host replaces its wiring role)
- `Engine` / `environments.py` (replaced by `uv` + service spawning)
- `ContentComposer` (rebuilt in host with service-based content resolution)
- `protocols.py` (replaced by decorators + wire protocol definitions)

---

## 2. Architecture

### The IPC Service Model

```
amplifier-ipc-host (message bus / router)
    │
    ├── stdio ↔ Orchestrator service   (any language)
    ├── stdio ↔ Context Manager service (any language)
    ├── stdio ↔ Provider service        (any language)
    ├── stdio ↔ Tool service(s)         (any language)
    ├── stdio ↔ Hook service(s)         (any language)
    └── stdio ↔ Content-only service(s) (any language)
```

### Host as Dumb Router

The host is a **dumb message bus**. It does NOT:
- Interpret hook results (DENY, MODIFY, INJECT — that's the orchestrator's job)
- Drive the agent loop (that's the orchestrator)
- Hold conversation state (that's the context manager service)
- Call LLMs (that's the provider service)

The host DOES:
- Spawn and tear down service processes
- Route orchestrator requests to the appropriate service
- Fan out hook emits to all registered hook services and chain results
- Persist transcript messages as they flow through
- Resolve content from services and assemble system prompts
- Relay streaming notifications from the orchestrator to the CLI

### Orchestrator Drives All Logic

The orchestrator keeps its full loop logic unchanged from the current StreamingOrchestrator:
- DENY checking on `prompt:submit`, `provider:request`, and `tool:pre` hook results
- Ephemeral injection queuing from `prompt:submit` and `tool:post` hook results
- MODIFY detection on `tool:post` hook results
- Parallel tool dispatch via `asyncio.gather`
- The only change: direct Python method calls become `self.client.request(...)` JSON-RPC calls

### Service Lifecycle Per Turn

```
User types prompt
  → Host SETUP:
    1. Read session config (resolved from agent/behavior definitions)
    2. Spawn all service processes
    3. Send `describe` to each → build routing table
    4. Resolve content via `content.read` → assemble system prompt
    5. Send `orchestrator.execute` to orchestrator service

  → ORCHESTRATOR LOOP (orchestrator drives, host routes):
    - Orchestrator sends request.* messages → host routes to services
    - Host fans out hook emits, chains results, returns to orchestrator
    - Host persists messages as they flow through (transcript)
    - Orchestrator streams tokens via notifications → host relays to CLI
    - Orchestrator completes → sends final response

  → Host TEARDOWN:
    1. Persist final transcript state
    2. SIGTERM all service processes (SIGKILL after timeout)
    3. Return response to CLI
    4. Wait for next prompt

User types next prompt
  → Spawn everything again (fresh processes, no stale state)
```

Process startup cost (~200ms for heavy imports) is paid once per user turn. Tearing down between turns means no stale state, simple versioning, and no concurrency concerns within services.

---

## 3. Registration and Discovery

Amplifier IPC uses a **UUID-based registration system** that discovers, caches, and manages agent and behavior definitions.

### AMPLIFIER_HOME Layout

```
$AMPLIFIER_HOME/
├── agents.yaml                    # Alias → ID mapping for agents
├── behaviors.yaml                 # Alias → ID mapping for behaviors
├── definitions/                   # Cached definition files
│   ├── agent_<local_ref>_<uuid>.yaml
│   └── behavior_<local_ref>_<uuid>.yaml
└── environments/                  # Per-service virtualenvs
    ├── agent_<local_ref>_<uuid>/
    │   └── bin/python
    └── behavior_<local_ref>_<uuid>/
        └── bin/python
```

### Identity Model

Every agent and behavior has:
- **uuid** — A globally unique identifier (GUID)
- **local_ref** — A human-readable local reference name, used within the agent/behavior definition and for composition (e.g., including one behavior within another)
- **ID** — Computed as `<agent|behavior>_<local_ref>_<uuid>` — used for filesystem paths and internal lookups

### Discovery and Registration CLI

```bash
# Discover all agents and behaviors at a location (git repo, fsspec path)
amplifier-ipc discover git+https://github.com/payneio/amplifier-ipc@main#subdirectory=/services/foundation \
  --register --install

# Register a single agent or behavior definition
amplifier-ipc register <fsspec> --install
```

The `discover` command:
1. Scans the target location for agent and behavior YAML definition files, returns uris
2. If --register flag, for each definition found, runs the equivalent of `register`

The `register` command:
1. Reads the definition's `local_ref` and `uuid`
2. Computes the ID: `<agent|behavior>_<local_ref>_<uuid>`
3. Caches the definition to `$AMPLIFIER_HOME/definitions/<ID>.yaml`
4. Adds an alias entry in `agents.yaml` or `behaviors.yaml` (alias defaults to `local_ref`)
5. If `--install` is passed, creates the virtualenv and installs the service

### Alias Files

`agents.yaml` and `behaviors.yaml` map human-friendly names to definition IDs:

```yaml
# $AMPLIFIER_HOME/agents.yaml
foundation: agent_foundation_3898a638-71de-427a-8183-b80eba8b26be
amplifier-dev: agent_amplifier-dev_e6a49802-fd80-4026-b9b8-2a790a0ccb5e
```

### Environment Installation

When a service section specifies `installer: uv`, the system creates an isolated virtualenv:

```bash
ENVIRONMENT=$AMPLIFIER_HOME/environments/$ID
uv venv --create $ENVIRONMENT
PYTHON=$ENVIRONMENT/bin/python
uv pip install --python $PYTHON <source>
```

Service processes are spawned from these environments:

```bash
uv run --venv $ENVIRONMENT <entrypoint>
```

The entrypoint defaults to `run` if not declared in the definition.

Installation is lazy — it runs automatically the first time you use an agent or behavior, or explicitly via `amplifier-ipc install <agent>`.

---

## 4. Agent and Behavior Definitions

### Behavior Definition Schema

A behavior is a composable unit of functionality. It can declare tools, context, sub-agents, nested behaviors, and a backing service.

```yaml
behavior:
  local_ref: <string>        # Human-readable reference name (required)
  uuid: <uuid>               # Globally unique identifier (required)
  version: <int>             # Definition version (optional)
  description: <string>      # Human-readable description (optional)

  # Component declarations — what this behavior contributes
  tools: <bool | list>       # true = all tools from service, or explicit list
  context: <bool>            # true = include context files from service
  hooks: <bool>              # true = include hooks from service

  # Composition — other agents and behaviors this one includes
  agents:
    include:
      - <service>:<agent_name>
  behaviors:
    - <alias>: <url_to_behavior_yaml>

  # Service backing — how to install and run the service process
  service:
    installer: uv            # Package installer (currently only "uv")
    source: <pip_installable> # e.g., git+https://github.com/org/repo@main#subdirectory=/path
```

**Example:**

```yaml
behavior:
  local_ref: amplifier-dev-behavior
  uuid: a6a2e2b5-8dd0-40ce-b2c7-327e4e62b645
  version: 2
  description: Amplifier ecosystem development behavior.

  tools: True
  context: True
  agents:
    include:
    - foundation:ecosystem-expert
  behaviors:
    - design-intelligence: https://raw.github.com/microsoft/amplifier-design-intelligence/main/behavior.yaml

  service:
    installer: uv
    source: git+https://github.com/microsoft/amplifier-ipc@main#subdirectory=/services/amplifier-dev
```

### Agent Definition Schema

An agent is the top-level entry point. It declares which orchestrator, context manager, tools, hooks, and behaviors to compose.

```yaml
agent:
  local_ref: <string>        # Human-readable reference name (required)
  uuid: <uuid>               # Globally unique identifier (required)
  version: <int>             # Definition version (optional)
  description: <string>      # Human-readable description (optional)
  base: <url>                # URL to base agent markdown (system prompt source)

  # Singleton component selections
  orchestrator: <service>:<name>     # e.g., foundation:streaming
  context_manager: <service>:<name>  # e.g., foundation:simple
  provider: <service>:<name>         # e.g., providers:anthropic (optional — can also be set at session level)

  # Component declarations
  tools: <bool>              # true = include tools from own service
  hooks: <bool>              # true = include hooks from own service
  agents: <bool>             # true = include sub-agents from own service
  context: <bool>            # true = include context from own service

  # Behaviors to compose (ordered list)
  behaviors:
    - <alias>: <url_to_behavior_yaml>

  # Optional service backing
  service:
    installer: uv
    source: <pip_installable>
```

**Example — Foundation Agent:**

```yaml
agent:
  local_ref: foundation
  uuid: 3898a638-71de-427a-8183-b80eba8b26be

  orchestrator: foundation:streaming
  context_manager: foundation:simple
  tools: True
  hooks: True
  agents: True
  context: True

  behaviors:
    - agents: https://raw.github.com/microsoft/amplifier-ipc/main/behaviors/agents.yaml
    - amplifier-dev: https://raw.github.com/microsoft/amplifier-ipc/main/behaviors/amplifier-dev.yaml
    - skills: https://raw.github.com/microsoft/amplifier-ipc/main/behaviors/skills.yaml
    - modes: https://raw.github.com/microsoft/amplifier-module-tool-modes/main/behavior.yaml
    # ... additional behaviors

  service:
    installer: uv
    source: git+https://github.com/microsoft/amplifier-ipc@main#subdirectory=/services/foundation
```

### Composition Resolution

At `run` time, the host:
1. Looks up the agent ID from `$AMPLIFIER_HOME/agents.yaml`
2. Loads the agent definition from `$AMPLIFIER_HOME/definitions/<ID>.yaml`
3. Recursively walks all referenced behaviors (fetching remote URLs as needed)
4. For each agent/behavior with a `service` section:
   - Ensures the virtualenv exists and sources are installed
   - Adds the service to the spawn list
5. Merges all component declarations into a unified in-memory map of `name → service:tool`
6. Spawns all services and begins the orchestrator loop

---

## 5. Wire Protocol

### Transport

**JSON-RPC 2.0 over stdio** with newline-delimited JSON framing.

- Each message is a single JSON object on one line, terminated by `\n`
- Messages are read via `readline()` and parsed with `json.loads()`
- Blank lines between messages are skipped
- Compact JSON serialization: `json.dumps(message, separators=(",", ":"))`

### Handshake

On startup, the host sends `describe` to each service:

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
      "providers": [],
      "content": {
        "paths": ["agents/explorer.md", "context/KERNEL_PHILOSOPHY.md"]
      }
    }
  }
}
```

### Host-to-Service Methods

These are requests the host sends to services:

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

### Orchestrator-to-Host Requests

These are requests the orchestrator sends back to the host for routing:

| Method | Params | Host Action | Returns |
|---|---|---|---|
| `request.hook_emit` | `{event, data}` | Fan out to hook services, chain results | `HookResult` |
| `request.tool_execute` | `{name, input}` | Route to owning tool service | `ToolResult` |
| `request.context_add_message` | `{message}` | Route to context manager service | `{ok: true}` |
| `request.context_get_messages` | `{provider_info}` | Route to context manager service | `{messages: [...]}` |
| `request.context_clear` | none | Route to context manager service | `{ok: true}` |
| `request.provider_complete` | `{request}` | Route to provider service | `ChatResponse` |

### Orchestrator-to-Host Streaming Notifications

Fire-and-forget notifications (no `id` field, no response expected):

| Method | Params | Host Action |
|---|---|---|
| `stream.token` | `{text}` | Relay to CLI |
| `stream.tool_call_start` | `{name, id}` | Relay to CLI |
| `stream.thinking` | `{text}` | Relay to CLI |

### Bidirectional Communication

The orchestrator is both a **service** (receives `orchestrator.execute`) and a **client** (sends `request.*` messages back to the host). This works over a single stdio channel:

1. The host sends `orchestrator.execute` as a JSON-RPC request with an `id`
2. The orchestrator sends `request.*` messages as JSON-RPC requests with their own `id`s — the host routes them and sends responses back
3. The orchestrator sends `stream.*` messages as JSON-RPC notifications (no `id`) — fire-and-forget
4. When the orchestrator loop completes, it sends the final JSON-RPC response matching the original `orchestrator.execute` request `id`

### Hook Event Names

Standard lifecycle events:

| Event | Fired When |
|---|---|
| `prompt:submit` | User prompt received, before processing |
| `prompt:complete` | Full response ready to return |
| `provider:request` | Before sending request to LLM provider |
| `provider:error` | Provider returns an error |
| `tool:pre` | Before executing a tool call |
| `tool:post` | After tool execution completes |
| `tool:error` | Tool execution fails |
| `orchestrator:complete` | Orchestrator loop finishes |
| `content_block:start` | Streaming content block begins |
| `content_block:end` | Streaming content block ends |

---

## 6. Data Models

All wire-format data uses **Pydantic v2 models** that round-trip cleanly through `model_dump(mode="json")` → `json.dumps` → `json.loads` → `model_validate`.

### DescribeResult

The `describe` handshake response has a formal model:

```python
class OrchestratorDescriptor(BaseModel):
    name: str

class ContextManagerDescriptor(BaseModel):
    name: str

class HookDescriptor(BaseModel):
    name: str
    events: list[str]
    priority: int = 100

class ContentCapabilities(BaseModel):
    paths: list[str] = Field(default_factory=list)

class Capabilities(BaseModel):
    orchestrators: list[OrchestratorDescriptor] = Field(default_factory=list)
    context_managers: list[ContextManagerDescriptor] = Field(default_factory=list)
    tools: list[ToolSpec] = Field(default_factory=list)
    hooks: list[HookDescriptor] = Field(default_factory=list)
    providers: list[dict[str, Any]] = Field(default_factory=list)
    content: ContentCapabilities = Field(default_factory=ContentCapabilities)

class DescribeResult(BaseModel):
    name: str
    capabilities: Capabilities
```

The `content.paths` list in the describe response is the **static manifest** of all content files the service can serve. The `content.list` wire method provides **dynamic discovery** with optional prefix filtering — it returns the same set but can be called at any time without a fresh describe cycle. Typically, the host uses `content.paths` from the describe response at startup and does not need `content.list` unless performing targeted lookups later.

### ToolCall

```python
class ToolCall(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)
    id: str
    name: str = Field(validation_alias=AliasChoices("name", "tool"), serialization_alias="tool")
    arguments: dict[str, Any] = Field(default_factory=dict)
```

### ToolSpec

```python
class ToolSpec(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)
```

### ToolResult

```python
class ToolResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    success: bool = True
    output: Any = None
    error: dict[str, Any] | None = None

    def get_serialized_output(self) -> str:
        """Serialize output for conversation context."""
        if self.output is not None:
            if isinstance(self.output, (dict, list)):
                return json.dumps(self.output)
            return str(self.output)
        return ""
```

### Message

```python
class Message(BaseModel):
    model_config = ConfigDict(extra="allow")
    role: str
    content: str | list[Any] | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None
    metadata: dict[str, Any] | None = None
    thinking_block: dict[str, Any] | None = None
```

### HookAction (enum)

```python
class HookAction(str, Enum):
    CONTINUE = "CONTINUE"
    DENY = "DENY"
    MODIFY = "MODIFY"
    INJECT_CONTEXT = "INJECT_CONTEXT"
    ASK_USER = "ASK_USER"
```

### HookResult

```python
class HookResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    action: HookAction = HookAction.CONTINUE
    data: dict[str, Any] | None = None
    reason: str | None = None
    message: Message | None = None
    question: str | None = None
    injected_messages: list[Message] = Field(default_factory=list)
    ephemeral: bool = False
    context_injection: str | None = None
    context_injection_role: str = "user"
    append_to_last_tool_result: bool = False
    suppress_output: bool = False
    user_message: str | None = None
    user_message_level: str = "info"
    user_message_source: str | None = None
    approval_prompt: str | None = None
    approval_options: list[str] | None = None
    approval_timeout: float = 300.0
    approval_default: str = "deny"
```

### ChatRequest

```python
class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    messages: list[Message]
    tools: list[ToolSpec] | None = None
    system: str | None = None
    reasoning_effort: str | None = None
    max_output_tokens: int | None = None
    temperature: float | None = None
    response_format: Any | None = None
```

### ChatResponse

```python
class ChatResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    content: str | list[Any] | None = None
    tool_calls: list[ToolCall] | None = None
    text: str | None = None
    usage: Any | None = None
    content_blocks: list[Any] | None = None
    metadata: dict[str, Any] | None = None
    finish_reason: str | None = None
```

### Content Block Types

```python
class TextBlock(BaseModel):
    type: str = "text"
    text: str = ""
    visibility: str | None = None

class ThinkingBlock(BaseModel):
    type: str = "thinking"
    thinking: str = ""
    signature: str | None = None
    visibility: str | None = None
    content: list[Any] | None = None

class ToolCallBlock(BaseModel):
    type: str = "tool_call"
    id: str = ""
    name: str = ""
    input: dict[str, Any] = Field(default_factory=dict)
    visibility: str | None = None
```

### Usage

```python
class Usage(BaseModel):
    model_config = ConfigDict(extra="allow")
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    reasoning_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
```

---

## 7. Component Types

There are **5 runtime component types** plus **content**. Each has a corresponding decorator, protocol definition, and wire protocol methods.

### Tool

**Decorator:** `@tool`
**Protocol:**
```python
@runtime_checkable
class ToolProtocol(Protocol):
    name: str
    description: str
    input_schema: dict[str, Any]
    async def execute(self, input: dict[str, Any]) -> ToolResult: ...
```
**Wire method:** `tool.execute` with params `{name, input}` → returns `ToolResult`

### Hook

**Decorator:** `@hook(events=["tool:pre", ...], priority=10)`
**Protocol:**
```python
@runtime_checkable
class HookProtocol(Protocol):
    name: str
    events: list[str]
    priority: int
    async def handle(self, event: str, data: dict[str, Any]) -> HookResult: ...
```
**Wire method:** `hook.emit` with params `{event, data}` → returns `HookResult`

**Priority:** Lower number = runs first. Hooks for the same event across services are sorted by priority ascending.

**Short-circuit:** DENY and ASK_USER actions stop the hook chain immediately — later hooks are not called. MODIFY updates the data dict for subsequent hooks.

### Orchestrator

**Decorator:** `@orchestrator`
**Protocol:**
```python
@runtime_checkable
class OrchestratorProtocol(Protocol):
    name: str
    async def execute(self, prompt: str, config: dict[str, Any], client: Any) -> str: ...
```
**Wire method:** `orchestrator.execute` with params `{prompt, system_prompt, tools, hooks, config}` → returns final response string

The orchestrator receives a `Client` instance for making requests back to the host.

### Context Manager

**Decorator:** `@context_manager`
**Protocol:**
```python
@runtime_checkable
class ContextManagerProtocol(Protocol):
    name: str
    async def add_message(self, message: Message) -> None: ...
    async def get_messages(self, provider_info: dict[str, Any]) -> list[Message]: ...
    async def clear(self) -> None: ...
```
**Wire methods:** `context.add_message`, `context.get_messages`, `context.clear`

Context manager state is accessed exclusively via request/response — no direct property access over IPC. The orchestrator calls `request.context_get_messages` each time it needs the message list.

### Provider

**Decorator:** `@provider`
**Protocol:**
```python
@runtime_checkable
class ProviderProtocol(Protocol):
    name: str
    async def complete(self, request: ChatRequest) -> ChatResponse: ...
```
**Wire method:** `provider.complete` with params `{request}` → returns `ChatResponse`

Provider streaming uses JSON-RPC notifications flowing back through the host to the orchestrator. The initial implementation uses non-streaming request/response; full streaming support is a future enhancement.

### Content

Content is not a runtime component — it is static files (`.md`, `.yaml`) served by services.

**Wire methods:** `content.read` with params `{path}` → `{content: "..."}`, `content.list` with params `{prefix?}` → `{paths: [...]}`

Content is discovered from conventional directories: `agents/`, `behaviors/`, `context/`, `recipes/`, `sessions/`.

---

## 8. Service Implementation

### Decorator-Based Discovery

The `amplifier-ipc-protocol` library provides decorators that mark classes as components by attaching metadata attributes. Decorators do NOT change class behavior — they only add `__amplifier_component__` (and hook-specific attributes like `__amplifier_hook_events__`, `__amplifier_hook_priority__`).

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
    events = ["tool:pre"]
    priority = 10
    async def handle(self, event: str, data: dict) -> HookResult: ...
```

### Package Layout Convention

Services follow a standard layout. The server discovers components from conventional directories:

```
src/<package_name>/
    __init__.py
    __main__.py              → Entry point: Server("<package_name>").run()
    orchestrators/*.py       → scan for @orchestrator classes
    context_managers/*.py    → scan for @context_manager classes
    tools/**/*.py            → scan for @tool classes
    hooks/**/*.py            → scan for @hook classes
    providers/**/*.py        → scan for @provider classes
    agents/*.md              → content
    behaviors/*.yaml         → content
    context/**/*.md          → content
    recipes/*.yaml           → content
    sessions/*.yaml          → content
```

**Important:** `scan_package()` only scans top-level `.py` files in each component directory — it does NOT recurse into subdirectories. Components in subdirectories require a **proxy file** at the top level:

```python
# tools/bash_tool.py — proxy for discovery
from my_package.tools.bash import BashTool  # noqa: F401
```

### Generic Server

The `Server` base class from the protocol library handles:
- Stdin read loop and JSON-RPC framing
- Method dispatch to handler methods
- Component discovery via `scan_package()` (finds decorated classes)
- Content discovery via `scan_content()` (finds files in content directories)
- `describe` response generation from discovered components
- `tool.execute`, `hook.emit`, `content.read`, `content.list` dispatch

Every service uses the same server code:

```python
# __main__.py
from amplifier_ipc_protocol import Server

def main():
    Server("my_package_name").run()
```

A content-only service discovers zero components and only serves content files.

### Client

The `Client` class sends JSON-RPC requests and matches responses by `id`:

```python
from amplifier_ipc_protocol.client import Client

client = Client(reader, writer, on_notification=callback)
result = await client.request("describe")
result = await client.request("tool.execute", {"name": "bash", "input": {...}})
await client.send_notification("stream.token", {"text": "hello"})
```

---

## 9. Host

The host is implemented as `amplifier-ipc-host`, a standalone Python package.

### Directory Structure

```
amplifier-ipc-host/
├── pyproject.toml
└── src/amplifier_ipc_host/
    ├── __init__.py
    ├── __main__.py          # CLI entry point
    ├── config.py            # Session config + settings parsing
    ├── lifecycle.py         # Spawn/teardown service subprocesses
    ├── registry.py          # Capability registry from describe responses
    ├── router.py            # Message routing + hook fan-out
    ├── content.py           # Content resolution + system prompt assembly
    ├── persistence.py       # Session transcript persistence (JSONL)
    └── host.py              # Main Host class tying everything together
```

### Config Parsing

```python
@dataclass
class ServiceOverride:
    command: list[str]
    working_dir: str | None = None

@dataclass
class HostSettings:
    service_overrides: dict[str, ServiceOverride]

@dataclass
class SessionConfig:
    services: list[str]
    orchestrator: str
    context_manager: str
    provider: str
    component_config: dict[str, dict[str, Any]]
```

### Service Lifecycle

```python
@dataclass
class ServiceProcess:
    name: str
    process: asyncio.subprocess.Process
    client: Client

async def spawn_service(name: str, command: list[str], working_dir: str | None = None) -> ServiceProcess
async def shutdown_service(service: ServiceProcess, timeout: float = 5.0) -> None
```

Shutdown is graceful: SIGTERM first, wait up to `timeout` seconds, then SIGKILL.

### Capability Registry

Built from `describe` responses at startup. Maps component names to their owning service keys:

```python
class CapabilityRegistry:
    def register(self, service_key: str, describe_result: dict) -> None
    def get_tool_service(self, tool_name: str) -> str | None
    def get_hook_services(self, event: str) -> list[dict]  # sorted by priority
    def get_orchestrator_service(self, name: str) -> str | None
    def get_context_manager_service(self, name: str) -> str | None
    def get_provider_service(self, name: str) -> str | None
    def get_content_services(self) -> dict[str, list[str]]
    def get_all_tool_specs(self) -> list[dict]
    def get_all_hook_descriptors(self) -> list[dict]
```

### Message Router

Routes `request.*` methods from the orchestrator to the appropriate service:

```python
class Router:
    async def route_request(self, method: str, params: Any) -> Any
```

**Routing table:**
- `request.tool_execute` → look up tool name in registry → `tool.execute` on owning service
- `request.hook_emit` → fan out to all hook services for the event, sorted by priority
- `request.context_*` → route to the active context manager service
- `request.provider_complete` → route to the active provider service

**Hook fan-out behavior:**
1. Get all hook services registered for the event, sorted by priority (ascending)
2. Call each service's `hook.emit` sequentially
3. If any returns DENY or ASK_USER → stop immediately, return that result
4. If any returns MODIFY with data → merge data into the data dict for subsequent hooks
5. Return the final HookResult

### Content Resolution

Resolves `@namespace:path` mentions by calling `content.read` on the appropriate service:

```python
async def resolve_mention(mention: str, registry, services) -> str
async def assemble_system_prompt(registry, services, mentions=None) -> str
```

System prompt assembly:
1. Gather all `context/` files from all services
2. Resolve any extra `@mentions`
3. Deduplicate by SHA-256 hash
4. Wrap each in `<context_file path="...">` tags

### Session Persistence

JSONL-based transcript persistence:

```python
class SessionPersistence:
    def __init__(self, session_id: str, base_dir: Path)
    def append_message(self, message: dict) -> None      # Append to transcript.jsonl
    def save_metadata(self, metadata: dict) -> None       # Write metadata.json
    def finalize(self) -> None                            # Mark session as completed
    def load_transcript(self) -> list[dict]               # Read back all messages
```

Files are stored at `<base_dir>/<session_id>/transcript.jsonl` and `<base_dir>/<session_id>/metadata.json`.

### Event Model

The Host's `run()` method returns an **async iterator of structured events** rather than a bare response. This is how the CLI (or any other consumer) receives streaming tokens, tool call notifications, and approval requests from the orchestrator loop.

The Host does NOT know about terminals, Rich consoles, or any UI concerns — it is a **pure event-emitting engine**. Consumers decide how to render events.

**Event types:**

| Event Type | Payload | Meaning |
|---|---|---|
| `stream.token` | `{text}` | Text chunk from LLM |
| `stream.thinking` | `{text}` | Thinking/reasoning text |
| `stream.tool_call_start` | `{name, id}` | Tool call beginning |
| `approval_request` | `{prompt, options, timeout, default}` | Hook requested user approval |
| `complete` | `{response}` | Turn finished, final response available |

These events originate as JSON-RPC notifications from the orchestrator service (`stream.*`) or as internal host events (`approval_request`, `complete`). The Host relays them uniformly through the async iterator, decoupling the orchestrator's wire protocol from the consumer's event loop.

```python
# Consumer pattern (used by CLI, but any caller can use this)
async for event in host.run(prompt):
    match event.type:
        case "stream.token":           handle_token(event)
        case "stream.thinking":        handle_thinking(event)
        case "stream.tool_call_start": handle_tool_start(event)
        case "approval_request":       result = await get_approval(event)
                                       host.send_approval(result)
        case "complete":               break
```

This design is consistent with the host's role as a message bus: the IPC boundary is between the host and services (JSON-RPC over stdio), not between the host and its caller. The host surfaces the orchestrator's notifications as first-class events rather than requiring callback registration.

---

## 10. Session Configuration

Session configuration operates at two levels: the **high-level agent/behavior definition model** (Section 3-4) and the **low-level session YAML** that the host uses internally after resolution.

### Low-Level Session YAML

After the host resolves agent and behavior definitions, it produces an internal session configuration:

```yaml
session:
  # Services to spawn
  services:
    - amplifier-foundation-serve
    - amplifier-providers-serve
    - amplifier-modes-serve
    - amplifier-skills-serve
    - amplifier-routing-matrix-serve
    - amplifier-core-serve
    - amplifier-superpowers-serve

  # Component selections (from describe responses)
  orchestrator: streaming
  context_manager: simple
  provider: anthropic

  # Per-component config overrides
  config:
    bash:
      timeout: 60
    streaming:
      max_iterations: 50
    anthropic:
      model: claude-sonnet-4-20250514
```

### Service Overrides (Local Development)

Override any service command via settings files:

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

**Resolution order** (first match wins):
1. Project settings (`.amplifier/settings.yaml` → `amplifier_ipc.service_overrides`)
2. User settings (`~/.amplifier/settings.yaml` → `amplifier_ipc.service_overrides`)
3. Session config service name → PATH lookup (from `uv tool install`)

### Local Overrides

All component selections (orchestrator, context manager, tools, hooks, providers) and content can be overridden locally in `ipc-overrides.yaml`. Custom agents and behaviors can also be created locally.

---

## 11. Service Inventory

### Services with Runtime Code (5)

#### amplifier-foundation

The primary service. Contains the core orchestrator, context manager, tools, and hooks.

| Component Type | Count | Names |
|---|---|---|
| Orchestrator | 1 | `streaming` (StreamingOrchestrator) |
| Context Manager | 1 | `simple` (SimpleContextManager) |
| Tools | 14+ | `bash`, `read_file`, `write_file`, `edit_file`, `grep`, `glob`, `web_search`, `web_fetch`, `todo`, `delegate` (stub), `task` (stub), `mcp` (stub), `recipes` (stub), `apply_patch` (stub), `python_check` (stub), `shadow` (stub) |
| Hooks | 12 | `approval`, `logging`, `routing`, `session_naming`, `shell`, `status_context`, `streaming_ui`, `deprecation`, `progress_monitor`, `redaction`, `todo_display`, `todo_reminder` |
| Content | 50+ files | agents (16), behaviors (12), context (~20), recipes (4), sessions (5) |

#### amplifier-providers

LLM provider adapters.

| Component Type | Count | Names |
|---|---|---|
| Providers | 8 | `mock`, `anthropic`, `openai`, `azure_openai`, `gemini`, `ollama`, `vllm`, `github_copilot` |

Note: Only `mock` is fully implemented initially; the remaining 7 are stubs that register the provider name for the service architecture. Real implementations are ported incrementally.

#### amplifier-modes

Runtime mode management — enforces tool restrictions when a mode is active.

| Component Type | Count | Names |
|---|---|---|
| Hook | 1 | `mode` (ModeHook) — events: `tool:pre`, `provider:request`, priority: 5 |
| Tool | 1 | `mode` (ModeTool) — operations: set, clear, list, current |
| Content | 2+ | `behaviors/modes.yaml`, `context/modes-instructions.md` |

#### amplifier-skills

Skill discovery and loading.

| Component Type | Count | Names |
|---|---|---|
| Tool | 1 | `load_skill` (SkillsTool) — operations: list, search, info, load, register source |
| Content | 3+ | `behaviors/skills-tool.yaml`, `behaviors/skills.yaml`, `context/skills-instructions.md` |

#### amplifier-routing-matrix

Model routing based on curated role-to-provider matrices.

| Component Type | Count | Names |
|---|---|---|
| Hook | 1 | `routing` (RoutingHook) — events: `provider:request` |
| Content | 4+ | `behaviors/routing.yaml`, `context/role-definitions.md`, `context/routing-instructions.md`, plus 7 routing matrix YAML data files |

### Content-Only Services (7)

These services discover zero runtime components and only serve `.md`/`.yaml` files.

| Service | Content |
|---|---|
| `amplifier-core` | Core documentation, contracts, shared context |
| `amplifier-amplifier` | Amplifier ecosystem meta-information |
| `amplifier-browser-tester` | Browser testing agents and guidance |
| `amplifier-design-intelligence` | Design agents and intelligence |
| `amplifier-filesystem` | Filesystem editing guidance |
| `amplifier-recipes` | Recipe authoring guidance |
| `amplifier-superpowers` | Development methodology content |

---

## 12. CLI

### Package Structure

`amplifier-ipc-cli/` is a new top-level package alongside `amplifier-ipc-protocol/` and `amplifier-ipc-host/`.

**Dependencies:**
- `amplifier-ipc-host` (which transitively brings `amplifier-ipc-protocol`)
- `click`, `prompt-toolkit`, `rich`, `pyyaml`

**Entry point:**
```toml
[project.scripts]
amplifier-ipc = "amplifier_ipc_cli.main:main"
```

**Lineage:** Based on `amplifier-lite-cli` with Layer 3 (session engine) replaced by IPC Host delegation.

### CLI ↔ Host Relationship

The CLI imports the Host **as a library** — it calls `Host.run()` in-process. The IPC boundary is between the host and services (JSON-RPC over stdio), NOT between the CLI and the host.

The Host is a **pure event-emitting engine**. It yields structured events and does not know about terminals, Rich consoles, or interactive approval dialogs. The CLI consumes the Host's event stream and handles all UI concerns: streaming display, approval dialogs, error formatting.

```python
# session_launcher.py — the core integration point
async for event in host.run(prompt):
    match event.type:
        case "stream.token":           streaming_handler(event)
        case "stream.thinking":        streaming_handler(event)
        case "stream.tool_call_start": streaming_handler(event)
        case "approval_request":       result = await approval_dialog(event)
                                       host.send_approval(result)
        case "complete":               break
```

The Host relays `stream.*` notifications from the orchestrator as events to its caller. Approval requests surface the same way. The CLI decides how to render them.

### Module Inventory

The CLI is derived from `amplifier-lite-cli`. Modules fall into four categories based on how they relate to the original codebase.

#### New Modules

| Module | Purpose |
|---|---|
| `definitions.py` | Agent/behavior YAML resolution + remote URL fetching + content hash tracking |
| `registry.py` | `$AMPLIFIER_HOME` filesystem management (alias files, definitions cache, environments) |
| `session_launcher.py` | Resolve definitions → build `SessionConfig` → `Host.run()` event loop |

#### Adapted from amplifier-lite-cli

| Module | Changes |
|---|---|
| `session_spawner.py` | Thinned for IPC — delegates heavy lifting to Host |
| `repl.py` | Consumes Host event stream instead of `session.run()` |
| `streaming.py` | Adapted for Host events instead of HookRegistry callbacks |
| `approval_provider.py` | Adapted for Host approval events |
| `settings.py`, `paths.py` | Path updates to `$AMPLIFIER_HOME` |
| `types.py` | Adapted for IPC contracts |
| `main.py` | Click group + slash commands |

#### Copied Wholesale from amplifier-lite-cli

- `console.py`, `key_manager.py`
- `ui/`: `message_renderer.py`, `display.py`, `error_display.py`
- `commands/`: `notify.py`, `allowed_dirs.py`, `denied_dirs.py`, `version.py`

#### Commands — Rewritten or New

| Command | Status |
|---|---|
| `commands/run.py` | **Rewritten** — definition resolution → Host event stream |
| `commands/discover.py` | **New** — scan locations for agent/behavior definitions |
| `commands/register.py` | **New** — cache a single definition to `$AMPLIFIER_HOME` |
| `commands/install.py` | **New** — create venv and install service dependencies |

#### Commands — Adapted

| Command | Changes |
|---|---|
| `commands/session.py` | Fork via Host instead of direct session creation |
| `commands/provider.py`, `commands/routing.py`, `commands/reset.py` | Path updates |

#### Deleted (Replaced by IPC Architecture)

- `session_runner.py`, `commands/environment.py`, `commands/init.py`, `commands/update.py`

### Definition Resolution (`definitions.py`)

The resolution flow when running an agent:

1. Read `$AMPLIFIER_HOME/agents.yaml` → look up agent name → get definition ID
2. Load `$AMPLIFIER_HOME/definitions/<ID>.yaml` → parse agent definition
3. Extract singleton selections (orchestrator, context_manager, provider)
4. Walk the agent's `behaviors` list recursively:
   - If already registered locally (alias in `behaviors.yaml`): load from `definitions/`
   - If a remote URL: fetch the YAML, cache to `definitions/` with UUID, add alias to `behaviors.yaml` (auto-register on first encounter)
   - Collect the behavior's service entry
   - If the behavior declares nested behaviors, recurse
5. Deduplicate services by UUID (same service from multiple behaviors = spawn once)
6. Merge any `--add-behavior` additions
7. Return `ResolvedAgent` which `session_launcher` converts to `SessionConfig`

### Registry Management (`registry.py`)

`$AMPLIFIER_HOME` defaults to `~/.amplifier`, overridable via environment variable. The registry is a thin filesystem wrapper — no database, no lock files. Alias files (`agents.yaml`, `behaviors.yaml`) are plain YAML dicts that can be hand-edited.

```python
class Registry:
    def __init__(self, home: Path = None)  # defaults to $AMPLIFIER_HOME or ~/.amplifier

    # Lookups
    def resolve_agent(self, name: str) -> Path          # alias → definition file path
    def resolve_behavior(self, name: str) -> Path       # alias → definition file path

    # Registration
    def register_definition(self, yaml_content: str, source_url: str | None = None) -> str
        # Parse YAML, extract type/local_ref/uuid, compute ID
        # Write to definitions/<ID>.yaml with _meta block
        # Add alias to agents.yaml or behaviors.yaml
        # Return the ID

    # Environment management
    def get_environment_path(self, definition_id: str) -> Path
    def is_installed(self, definition_id: str) -> bool

    # Update support
    def get_source_meta(self, definition_id: str) -> dict | None  # _meta block
```

### Cached Definition Metadata

When a definition is fetched from a remote URL, a `_meta` block is appended to the cached file:

```yaml
_meta:
  source_url: https://raw.github.com/microsoft/amplifier-ipc/main/behaviors/amplifier-dev.yaml
  source_hash: sha256:a1b2c3d4...    # SHA-256 of raw fetched bytes (before parsing)
  fetched_at: 2026-03-21T04:00:00Z
```

The `_meta` block is CLI-managed metadata, not part of the definition schema itself. The hash is SHA-256 of the raw YAML bytes before parsing — simple, deterministic, no normalization needed.

This enables:
- **`amplifier-ipc update <agent>`** — re-fetch all behavior URLs in the agent's tree, compare `source_hash` against new content, report what changed, update only if different
- **`amplifier-ipc update --check`** — dry-run, report which definitions have upstream changes without applying them
- **`amplifier-ipc run`** does NOT check freshness — uses cached definitions as-is for speed. Freshness is an explicit `update` concern

### Run Command Flow

```
amplifier-ipc run --agent foundation "hello"

  1. KeyManager loads API keys
  2. session_launcher.launch_session(agent_name, ...) called
  3. Registry resolves agent name → definition file
  4. definitions.resolve_agent() walks behavior tree,
     fetches remote URLs if needed, collects services
  5. Lazy install: for each service not yet installed, create venv and install
  6. Build SessionConfig from ResolvedAgent
  7. Create Host(session_config) — imported as library
  8. If prompt given: iterate host.run(prompt) event stream, render to terminal
  9. If no prompt: enter interactive REPL, calling host.run() per turn
```

The REPL (`repl.py`) calls `host.run(prompt)` per turn instead of `session.run(prompt)` — same shape, different backend.

### Core Commands

#### `amplifier-ipc discover`

Find and optionally register agents and behaviors from a remote or local location.

```bash
amplifier-ipc discover <location> [--register] [--install]
```

- `<location>` — Git URL, fsspec path, or local path
- `--register` — Cache definitions and create alias entries
- `--install` — Also create virtualenvs and install service dependencies

#### `amplifier-ipc register`

Register a single agent or behavior definition.

```bash
amplifier-ipc register <fsspec> [--install]
```

#### `amplifier-ipc install`

Ensure a service's virtualenv exists and dependencies are installed.

```bash
amplifier-ipc install <agent_or_behavior>
```

#### `amplifier-ipc run`

Run an agent session.

```bash
amplifier-ipc run \
  --agent <agent> \
  --add-behavior <behavior> \
  --session <session_id> \
  --project <project_name> \
  --working-dir <fsspec> \
  "<message>"
```

---

## 13. Error Handling

### JSON-RPC 2.0 Error Codes

| Code | Constant | Meaning |
|---|---|---|
| -32700 | `PARSE_ERROR` | Invalid JSON received |
| -32600 | `INVALID_REQUEST` | JSON is not a valid request object |
| -32601 | `METHOD_NOT_FOUND` | Method does not exist |
| -32602 | `INVALID_PARAMS` | Invalid method parameters |
| -32603 | `INTERNAL_ERROR` | Internal JSON-RPC error |

### Error Response Format

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "error": {"code": -32603, "message": "Tool execution failed", "data": {"traceback": "..."}}
}
```

### Error Helpers

```python
from amplifier_ipc_protocol.errors import JsonRpcError, make_error_response

# Create error response dict
resp = make_error_response(request_id=1, code=INTERNAL_ERROR, message="Failed", data={...})

# Raise as exception (caught by Server and converted to error response)
raise JsonRpcError(INVALID_PARAMS, "Unknown tool: 'foo'")
```

### Error Philosophy

- The **host relays errors transparently** — it does not interpret or recover from them
- The **orchestrator decides** how to handle errors (retry, abort, synthesize error message to user)
- **Service crashes** are detected by the host via EOF on the service's stdout and reported to the orchestrator as JSON-RPC error responses
- Service processes that crash mid-turn are NOT restarted — the host reports the failure to the orchestrator, which can abort the turn or continue without the crashed service

---

## 14. Testing Strategy

### amplifier-ipc-protocol

Unit tests for:
- **Framing** — read/write JSON-RPC messages, round-trip, blank line handling, malformed JSON
- **Errors** — error code constants, `make_error_response()`, `JsonRpcError` exception
- **Models** — JSON round-trip for all Pydantic models, field defaults, alias handling
- **Decorators** — metadata attachment, class identity preservation
- **Protocols** — structural subtyping checks via `isinstance()`
- **Discovery** — `scan_package()` finds decorated classes, `scan_content()` finds files
- **Client/Server** — round-trip over in-process pipes

### amplifier-ipc-host

Integration tests:
- **Config** — YAML parsing, settings merging, service command resolution
- **Lifecycle** — spawn real processes, verify creation, graceful + force-kill shutdown
- **Registry** — register describe results, lookup tools/hooks/providers/orchestrators
- **Router** — tool routing, hook fan-out with DENY short-circuit, context/provider routing
- **Content** — mention resolution, system prompt assembly, deduplication
- **Persistence** — JSONL append, metadata save, transcript loading

### Service Packages

Per-service tests:
- **Scaffolding** — package importable, entry point exists
- **Describe** — Server responds to describe with correct capabilities
- **Content** — `scan_content()` finds expected files
- **Component** — individual tool/hook/orchestrator/context_manager/provider unit tests

### End-to-End

Full session tests:
- Start the host with a session config
- Run a prompt through the full orchestrator loop
- Verify tool calls, hook emissions, provider completions
- Verify transcript persistence

---

## 15. Project Structure

```
amplifier-ipc/
├── amplifier-ipc-protocol/          # Shared JSON-RPC 2.0 library
│   ├── pyproject.toml
│   └── src/amplifier_ipc_protocol/
│       ├── __init__.py
│       ├── framing.py               # read_message() / write_message()
│       ├── errors.py                # JSON-RPC 2.0 error codes
│       ├── models.py                # Pydantic v2 wire-format models
│       ├── decorators.py            # @tool, @hook, @orchestrator, etc.
│       ├── protocols.py             # typing.Protocol definitions
│       ├── discovery.py             # scan_package() / scan_content()
│       ├── client.py                # JSON-RPC client
│       ├── server.py                # Generic JSON-RPC server
│       └── content.py               # Content file serving
│
├── amplifier-ipc-host/              # Central message bus / router
│   ├── pyproject.toml
│   └── src/amplifier_ipc_host/
│       ├── __init__.py
│       ├── __main__.py              # CLI entry point
│       ├── config.py                # Session config + settings parsing
│       ├── lifecycle.py             # Spawn/teardown services
│       ├── registry.py              # Capability registry
│       ├── router.py                # Message routing + hook fan-out
│       ├── content.py               # Content resolution
│       ├── persistence.py           # JSONL transcript persistence
│       └── host.py                  # Main Host class
│
├── amplifier-ipc-cli/               # CLI application (user-facing entry point)
│   ├── pyproject.toml
│   └── src/amplifier_ipc_cli/
│       ├── __init__.py
│       ├── main.py                  # Click group + slash commands
│       ├── definitions.py           # Agent/behavior YAML resolution + URL fetching
│       ├── registry.py              # $AMPLIFIER_HOME filesystem management
│       ├── session_launcher.py      # Definitions → SessionConfig → Host.run()
│       ├── repl.py                  # Interactive REPL (Host event stream consumer)
│       ├── streaming.py             # Stream event rendering
│       ├── approval_provider.py     # Interactive approval dialogs
│       ├── key_manager.py           # API key management
│       ├── settings.py              # Settings + path resolution
│       ├── console.py               # Rich console setup
│       ├── ui/                      # Display components
│       │   ├── message_renderer.py
│       │   ├── display.py
│       │   └── error_display.py
│       └── commands/                # CLI commands
│           ├── run.py               # Run agent sessions
│           ├── discover.py          # Scan for definitions
│           ├── register.py          # Cache definitions locally
│           ├── install.py           # Create venvs + install
│           ├── session.py           # Session management
│           ├── provider.py          # Provider selection
│           ├── routing.py           # Routing configuration
│           └── ...
│
└── services/                        # One package per service
    ├── amplifier-foundation/        # Orchestrator, context mgr, hooks, tools, content
    ├── amplifier-providers/         # LLM provider adapters
    ├── amplifier-modes/             # Mode hook + tool + content
    ├── amplifier-skills/            # Skills tool + content
    ├── amplifier-routing-matrix/    # Routing hook + matrices + content
    ├── amplifier-core/              # Content only
    ├── amplifier-amplifier/         # Content only
    ├── amplifier-browser-tester/    # Content only
    ├── amplifier-design-intelligence/ # Content only
    ├── amplifier-filesystem/        # Content only
    ├── amplifier-recipes/           # Content only
    └── amplifier-superpowers/       # Content only
```

### Tech Stack

- **Python 3.11+**
- **Pydantic v2** — all wire-format models
- **hatchling** — build system for all packages
- **uv** — package management and virtualenv creation
- **PyYAML** — configuration parsing
- **pytest + pytest-asyncio** — test framework
- **Zero other required external dependencies** in the protocol library

---

## 16. Open Questions and Future Work

### Resolved

| Question | Resolution |
|---|---|
| Hook ordering across services | Priority field in the hook descriptor. Hooks sorted by priority ascending (lower = first). Cross-service priority conflicts are resolved by registration order as tiebreaker. |
| Service crash recovery | Host detects EOF on service stdout, reports error to orchestrator as a JSON-RPC error response. No automatic retry — orchestrator decides. |
| Parallel tool calls across services | Host dispatches concurrently via `asyncio.gather`. Each tool's pre→execute→post cycle runs concurrently when tools are in different services. |
| Context manager state access over IPC | Request-based access only — no property access. Orchestrator calls `request.context_get_messages` each time it needs messages. |
| Remote behavior fetching | Definitions fetched from URLs are cached in `$AMPLIFIER_HOME/definitions/` with a `_meta` block containing `source_url`, `source_hash` (SHA-256 of raw bytes), and `fetched_at`. Auto-registered on first encounter during definition resolution. See Section 12 (CLI — Cached Definition Metadata). |
| Definition versioning | `source_hash` in `_meta` enables `amplifier-ipc update <agent>` to re-fetch URLs, compare hashes, and update only if changed. `amplifier-ipc update --check` does a dry-run. `amplifier-ipc run` does NOT check freshness — uses cached definitions as-is. See Section 12 (CLI — Cached Definition Metadata). |
| Approval flow over IPC | Approval requests surface through the Host's event stream as `approval_request` events. The CLI handles the interactive dialog and sends the result back via `host.send_approval()`. The Host does not know about terminals or UI. See Section 9 (Host — Event Model) and Section 12 (CLI — CLI ↔ Host Relationship). |

### Open

| Question | Status |
|---|---|
| **Provider streaming** | The current orchestrator calls `provider.stream()` returning an async iterator. Over IPC, this needs JSON-RPC notifications flowing back through the host. Initial implementation uses non-streaming `provider.complete`. Full streaming protocol TBD. |
| **Cross-service shared state** | Hooks like `todo_display` and `todo_reminder` previously accessed `session.state["todo_state"]` directly. Over IPC, there's no shared state between services. Solutions: (a) request-based state access through the host, (b) state service, (c) hook-specific state passed in event data. TBD. |
| **Sub-session spawning** | `DelegateTool` and `TaskTool` spawn sub-sessions. Over IPC, this requires the host to support nested session creation. Currently stubbed — implementation TBD. |
| **CLI↔Host error propagation** | How do service crashes surface through the Host's event stream? The host detects EOF on service stdout, but the event type and payload for propagating this to the CLI (and whether the REPL can recover gracefully) is unspecified. |

### Future Enhancements

- **Networked services** — replace stdio with HTTP/gRPC transport for true microservice deployment
- **Hot-reload** — detect service source changes and re-spawn without restarting the full session
- **Service health checks** — periodic pings to detect hung services
- **Metrics and observability** — structured logging, request tracing, latency histograms
- **Multi-language SDKs** — protocol library implementations for TypeScript, Rust, Go
- **AMPLIFIER_HOME persistence abstraction** — support for different storage backends (filesystem, S3, database) for session data and settings