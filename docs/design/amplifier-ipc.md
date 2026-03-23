## Overview

Amplifier IPC is a rearchitecture of the Amplifier platform. Instead of in-process
dynamic-import module loading, every component runs as a separate subprocess
communicating via JSON-RPC 2.0 over stdio.

The system has three layers:
- **Protocol**: JSON-RPC 2.0 library with typed models, decorators, and server/client
- **Host**: Central message bus — spawns services, routes requests, manages sessions
- **CLI**: User-facing commands, REPL, settings management

All three live in a single package (`amplifier-ipc`) with sub-packages at
`src/amplifier_ipc/{protocol,host,cli}/`.

Sessions:

- bb782c99
- 6b596d62: Merged packages. Wrote all def files. Migrated providers. Spawning fixes. CLI UX.

## Usage

Installation:

```bash
uv tool install git+https://github.com/payneio/amplifier-ipc
```

Discover and register agents/behaviors:

```bash
# Scan a location for agent/behavior definitions, register and install them.
amplifier-ipc discover ./services/amplifier-foundation --register --install

# Register a single definition.
amplifier-ipc register <path-or-url> --install

# Install a registered service (creates venv, installs deps).
# Also runs automatically on first use.
amplifier-ipc install <ref>
```

Run a session:

```bash
# Interactive REPL
amplifier-ipc run --agent foundation

# Single-shot
amplifier-ipc run --agent foundation "What files are in this directory?"

# Resume a previous session
amplifier-ipc session resume <session-id>
```

Other CLI commands:

```bash
amplifier-ipc unregister <ref>     # Remove a registered definition
amplifier-ipc uninstall <ref>      # Remove installed environment
amplifier-ipc update <ref>         # Re-fetch remote definition
amplifier-ipc session list         # List past sessions
amplifier-ipc provider             # Provider selection
amplifier-ipc routing              # Routing configuration
amplifier-ipc reset                # Reset settings
amplifier-ipc version              # Print version
```

## Architecture

### Message Flow

```
CLI -> Host.run(prompt) -> [async iterator of HostEvents]
  |
  +- Host spawns service subprocesses (or reuses shared services)
  +- Host sends `describe` -> builds CapabilityRegistry -> sends `configure`
  +- Host calls orchestrator.execute on the orchestrator service
  |
  +- Orchestrator loop reads messages from orchestrator stdout:
      +- request.tool_execute -> Router -> service -> response back
      +- request.hook_emit -> Router -> fan-out across services
      +- request.provider_complete -> Router -> provider service -> response
      +- request.context_* -> Router -> context manager service -> response
      +- request.session_spawn -> Host -> child session lifecycle
      +- stream.token -> yield StreamTokenEvent (to CLI)
      +- stream.thinking -> yield StreamThinkingEvent
      +- stream.tool_call_start -> yield StreamToolCallStartEvent
      +- response -> yield CompleteEvent, return
```

### Service Lifecycle (Per Turn)

1. Load shared state from persistence
2. Spawn all configured service subprocesses
3. `describe` -> build `CapabilityRegistry` -> `configure` each service
4. Replay existing transcript into context manager
5. Assemble system prompt from all `context/` files (SHA-256 deduped)
6. Run orchestrator loop (bidirectional message routing)
7. Save state, metadata, finalize

### Key Design: _OrchestratorLocalClient

The orchestrator and its co-located tools/hooks/context run in the same service
process. Having them call each other over IPC would deadlock (the server can't
read its own requests while blocking on a response). The `_OrchestratorLocalClient`
solves this by routing same-service calls (tools, hooks, context) directly to the
server's handler methods in-process. Only external calls (provider, state,
session_spawn) go through IPC to the host.

### Sub-Session Spawning (Delegation)

- `DelegateTool` calls `request.session_spawn` via the orchestrator's client
- Host builds a child `SpawnRequest` with filtered tools/hooks, parent context
- `spawn_child_session()` enforces max depth (3), creates child Host with
  `shared_services` from parent (avoids re-spawning)
- Child events wrapped in `ChildSessionEvent(depth=N, inner=event)` and
  forwarded to parent

### Session Persistence

- `transcript.jsonl`: Append-only message log per turn
- `metadata.json`: Session metadata (agent, project, timestamps)
- `state.json`: Cross-turn shared state (loaded/saved per turn)

### Settings

Three-scope deep merge: global (`~/.amplifier/settings.yaml`) < project
(`.amplifier/settings.yaml`) < local (`.amplifier/settings.local.yaml`).

## Agent and Behavior Definitions

Every agent/behavior has a `ref` (local reference name), a `uuid`, and optionally
a `service` section with install instructions.

```yaml
# Foundation agent (definitions/foundation-agent.yaml)
agent:
  ref: foundation
  uuid: 3898a638-71de-427a-8183-b80eba8b26be
  description: Full-featured Amplifier agent with all foundation capabilities.

  orchestrator: amplifier-foundation:streaming
  context_manager: amplifier-foundation:simple

  behaviors:
    - amplifier-foundation
    - amplifier-providers
    - amplifier-modes
    - amplifier-skills
    - amplifier-routing-matrix
    - amplifier-core          # content-only
    - amplifier-amplifier     # content-only
    - amplifier-browser-tester
    - amplifier-design-intelligence
    - amplifier-filesystem
    - amplifier-recipes
    - amplifier-superpowers

  service:
    stack: uv
    source: ./services/amplifier-foundation
```

```yaml
# Behavior definition example
behavior:
  ref: amplifier-modes
  uuid: <uuid>
  description: Runtime mode overlays for agent behavior.

  service:
    stack: uv
    source: ./services/amplifier-modes
```

### Definition Registration

```bash
REF=$(yq '.agent.ref // .behavior.ref' $DEFINITION_FILE)
UUID=$(yq '.agent.uuid // .behavior.uuid' $DEFINITION_FILE)
```

`register` caches the definition to `$AMPLIFIER_HOME/definitions/` and creates
alias files in `$AMPLIFIER_HOME/aliases/` mapping ref -> uuid.

### Component Discovery

Services don't declare capabilities in YAML. Instead, the host sends a `describe`
JSON-RPC call after spawning. The service scans its own Python packages for
`@tool`, `@hook`, `@orchestrator`, `@context_manager`, `@provider` decorated
classes and reports them back. This is the `scan_package()` function in the
protocol library.

Content (agents/, behaviors/, context/, recipes/) is discovered via `scan_content()`
which walks known directories for markdown/yaml files.

## Services

### Services with Runtime Code

| Service | Components |
|---------|-----------|
| `amplifier-foundation` | 1 orchestrator, 1 context manager, 12+ tools, 12 hooks, content |
| `amplifier-providers` | 8 providers (anthropic, openai, azure, gemini, ollama, vllm, github_copilot, mock) |
| `amplifier-modes` | 1 hook, 1 tool, content |
| `amplifier-skills` | 1 tool, content |
| `amplifier-routing-matrix` | 1 hook, routing data, content |

### Content-Only Services

These provide only `agents/`, `behaviors/`, and/or `context/` directories -- no
runtime code: `amplifier-core`, `amplifier-amplifier`, `amplifier-browser-tester`,
`amplifier-design-intelligence`, `amplifier-filesystem`, `amplifier-recipes`,
`amplifier-superpowers`.

## Future

- Consider making CLI interact with host via IPC rather than as a library.
- Provider streaming (`stream.provider.*` plumbing exists but providers may not emit yet).
- Hot-reload, health checks, metrics.
- Multi-language SDKs (only Python today).
