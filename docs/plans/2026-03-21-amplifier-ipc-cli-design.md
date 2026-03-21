# amplifier-ipc CLI Package Design

## Goal

Build `amplifier-ipc-cli/`, a new top-level package that provides the user-facing CLI for amplifier-ipc. It handles agent/behavior registration, discovery, installation, and interactive sessions. The CLI imports `amplifier-ipc-host` as a library (in-process), NOT as a subprocess. The IPC boundary is between the host and services, not between CLI and host.

First milestone: the registration/discovery/CLI layer working against `amplifier-ipc/services/amplifier-foundation`. Meaning `amplifier-ipc run --agent foundation` produces a working interactive session.

## Background

The amplifier-ipc architecture splits the monolithic `amplifier-lite` into three layers: a wire protocol library (`amplifier-ipc-protocol`), a host process (`amplifier-ipc-host`), and per-capability services that communicate over JSON-RPC stdin/stdout. The protocol and host packages exist. Services are being extracted. What's missing is the user-facing CLI that ties it all together — resolving agent definitions, managing a local registry of behaviors, spawning the host, and providing the interactive REPL.

The existing `amplifier-lite-cli` has a mature UI layer (Rich console rendering, prompt-toolkit REPL, streaming display, approval dialogs) but its execution backend is tightly coupled to `amplifier-lite`'s in-process session model. We need to replace that backend with the IPC host while keeping the UI.

## Approach

**Copy-and-gut from amplifier-lite-cli.** Copy `amplifier-lite-cli` wholesale into `amplifier-ipc-cli/`. Keep the UI layer intact (console, repl, streaming, approval, message rendering, settings, key_manager). Gut Layer 3 (session_runner, session_spawner, environments, all `amplifier_lite.*` imports). Build definition resolution + registry as the new Layer 3. Wire `run` to call `Host.run()` in-process. Add `discover`/`register`/`install` commands.

This preserves the battle-tested UI code and avoids rewriting display logic, key bindings, and terminal handling from scratch.

## Architecture

### Package Structure

`amplifier-ipc-cli/` is a new top-level package alongside `amplifier-ipc-protocol/` and `amplifier-ipc-host/`.

**Dependencies:** `amplifier-ipc-host` (which transitively brings `amplifier-ipc-protocol`), `click`, `prompt-toolkit`, `rich`, `pyyaml`.

**Entry point:** `amplifier-ipc = amplifier_ipc_cli.main:main`

### Module Inventory

```
amplifier-ipc-cli/
├── pyproject.toml
└── src/amplifier_ipc_cli/
    ├── __init__.py
    ├── __main__.py              # python -m entry
    ├── main.py                  # Click group + slash commands (from lite-cli)
    ├── definitions.py           # NEW: agent/behavior YAML resolution + remote URL fetching
    ├── registry.py              # NEW: $AMPLIFIER_HOME filesystem management
    ├── session_launcher.py      # NEW: resolve definitions → build SessionConfig → Host.run()
    ├── session_spawner.py       # FROM lite-cli (thinned — delegates heavy lifting to Host)
    ├── repl.py                  # FROM lite-cli (adapted for Host event stream)
    ├── streaming.py             # FROM lite-cli (adapted for Host events instead of HookRegistry)
    ├── approval_provider.py     # FROM lite-cli (adapted for Host approval events)
    ├── settings.py              # FROM lite-cli (path updates to $AMPLIFIER_HOME)
    ├── paths.py                 # FROM lite-cli (path updates)
    ├── key_manager.py           # FROM lite-cli (wholesale)
    ├── console.py               # FROM lite-cli (wholesale)
    ├── types.py                 # FROM lite-cli (adapted for IPC contracts)
    ├── ui/                      # FROM lite-cli (wholesale)
    │   ├── __init__.py
    │   ├── message_renderer.py
    │   ├── display.py
    │   └── error_display.py
    └── commands/
        ├── run.py               # REWRITTEN: definition resolution → Host
        ├── discover.py          # NEW
        ├── register.py          # NEW
        ├── install.py           # NEW
        ├── session.py           # FROM lite-cli (adapted, fork stays)
        ├── provider.py          # FROM lite-cli (path updates)
        ├── routing.py           # FROM lite-cli (path updates)
        ├── notify.py            # FROM lite-cli (wholesale)
        ├── allowed_dirs.py      # FROM lite-cli (wholesale)
        ├── denied_dirs.py       # FROM lite-cli (wholesale)
        ├── reset.py             # FROM lite-cli (path updates)
        └── version.py           # FROM lite-cli (trivial)
```

**Deleted from lite-cli** (replaced by IPC architecture): `session_runner.py`, `commands/environment.py`, `commands/init.py`, `commands/update.py`.

### CLI ↔ Host Relationship

The Host is a pure event-emitting engine. Its `run()` method returns an async iterator of events. The CLI is the UI layer — it decides how to render events, prompt for approvals, and display errors. The Host does NOT know about terminals, Rich consoles, or any UI concerns.

```python
async for event in host.run(prompt):
    match event.type:
        case "stream.token":           live_render(event.text)
        case "stream.thinking":        render_thinking(event.text)
        case "stream.tool_call_start": show_tool_status(event.name)
        case "approval_request":       response = await approval_dialog(event)
                                       host.send_approval(response)
        case "complete":               render_final(event.response)
```

This is consistent with the existing architecture: the Host already relays `stream.*` notifications from the orchestrator. It should surface those to its caller the same way. The Host is a message bus, not a UI-aware application.

## Components

### Definition Resolution (`definitions.py`)

The core new logic. Takes an agent name, resolves it through `$AMPLIFIER_HOME`, walks the behavior tree (fetching remote definitions as needed), and produces the data the Host needs.

```python
async def resolve_agent(
    registry: Registry,
    agent_name: str,
    extra_behaviors: list[str] = None,
) -> ResolvedAgent

@dataclass
class ResolvedAgent:
    services: list[ServiceEntry]      # all services to spawn (deduplicated by UUID)
    orchestrator: str                  # e.g., "streaming"
    context_manager: str              # e.g., "simple"
    provider: str | None              # from agent def or settings
    component_config: dict            # per-component config overrides
```

**Resolution flow:**

1. Read `$AMPLIFIER_HOME/agents.yaml` → look up agent name → get definition ID.
2. Load `$AMPLIFIER_HOME/definitions/<ID>.yaml` → parse agent definition.
3. Extract singleton selections (orchestrator, context_manager, provider).
4. Walk the agent's `behaviors` list recursively. For each behavior:
   - If already registered locally (alias exists in `behaviors.yaml`): load from `definitions/`.
   - If a remote URL: fetch the YAML, cache it to `definitions/` with its UUID, add alias to `behaviors.yaml` (auto-register on first encounter).
   - Collect the behavior's `service` entry.
   - If the behavior declares nested behaviors, recurse.
5. Deduplicate services by UUID (same service referenced by multiple behaviors = spawn once).
6. Merge any `--add-behavior` additions.
7. Return `ResolvedAgent`.

The auto-register-on-fetch behavior means `discover`/`register` are explicit bulk operations, but the `run` command also works if you just have a hand-written agent YAML that references behavior URLs directly. First fetch is slow (HTTP); subsequent runs use the cached local copy.

**Caching strategy:** Fetch once and cache by UUID. Cache invalidation is manual (`amplifier-ipc update` or re-register). Simple and predictable — no implicit freshness checks.

### Registry (`registry.py`)

Owns the `$AMPLIFIER_HOME` filesystem layout and provides CRUD operations.

**Filesystem layout:**

```
$AMPLIFIER_HOME/
├── agents.yaml                    # alias → definition ID
├── behaviors.yaml                 # alias → definition ID
├── definitions/                   # cached definition files with _meta
│   ├── agent_foundation_3898a638.yaml
│   └── behavior_amplifier-dev_a6a2e2b5.yaml
└── environments/                  # per-service virtualenvs
    └── behavior_amplifier-dev_a6a2e2b5/
        └── bin/python
```

**API:**

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

`$AMPLIFIER_HOME` defaults to `~/.amplifier`, overridable via environment variable. Thin filesystem wrapper — no database, no lock files. Alias files are plain YAML dicts, hand-editable.

**Cached definition metadata:** When a definition is fetched from a remote URL, a `_meta` block is appended:

```yaml
_meta:
  source_url: https://raw.github.com/microsoft/amplifier-ipc/main/behaviors/amplifier-dev.yaml
  source_hash: sha256:a1b2c3d4...    # SHA-256 of raw fetched bytes
  fetched_at: 2026-03-21T04:00:00Z
```

This enables:
- `amplifier-ipc update <agent>` — re-fetch all behavior URLs in the agent's tree, compare `source_hash`, update only if different.
- `amplifier-ipc update --check` — dry-run, report which definitions have upstream changes.
- `amplifier-ipc run` does NOT check freshness — uses cached definitions as-is for speed.

Hash is SHA-256 of the raw YAML bytes before parsing. Simple, deterministic, no normalization needed.

### Session Launcher (`session_launcher.py`)

The glue between definitions and the host:

```python
async def launch_session(
    agent_name: str,
    extra_behaviors: list[str] = None,
    prompt: str = None,
    settings: Settings = None,
) -> None:
    # 1. Resolve agent definition → collect services, component selections
    registry = Registry()
    resolved = await resolve_agent(registry, agent_name, extra_behaviors)

    # 2. Ensure all services are installed (lazy install)
    for service in resolved.services:
        if not registry.is_installed(service.definition_id):
            await install_service(registry, service)

    # 3. Build SessionConfig (the host's internal format)
    session_config = build_session_config(resolved, settings)

    # 4. Create and run the Host (imported as library)
    from amplifier_ipc_host.host import Host
    host = Host(session_config)

    # 5. Run — iterate event stream
    if prompt:
        async for event in host.run(prompt):
            handle_event(event)
    else:
        await interactive_chat(host, ...)  # REPL loop
```

Key insight: `session_launcher.py` is thin. It resolves definitions, ensures installation, builds config, and hands off to the Host.

### REPL Integration (`repl.py`)

The REPL loop from `amplifier-lite-cli` stays structurally identical — `prompt-toolkit` with `FileHistory`, custom key bindings (Ctrl-J = newline, Enter = submit), mode indicator in the prompt. What changes is the execution backend.

**Current lite-cli pattern:**

```python
response = await session.run(prompt)
render_message(response)
```

**IPC pattern:**

```python
async for event in host.run(prompt):
    match event.type:
        case "stream.token":           live_render(event.text)
        case "stream.thinking":        render_thinking(event.text)
        case "stream.tool_call_start": show_tool_status(event.name)
        case "approval_request":       response = await approval_dialog(event)
                                       host.send_approval(response)
        case "complete":               render_final(event.response)
```

**Cancellation** adapts: instead of `CancellationToken.cancel()` on Ctrl+C, the CLI sends a cancellation signal to the Host, which propagates SIGTERM to services. Two-stage cancellation stays (first = graceful, second = immediate).

**Slash commands** like `/tools`, `/agents`, `/config` that previously inspected `session._tools` or `session.context` directly now query the Host's registry (in-process method call, not IPC).

**`streaming.py`** simplifies — instead of registering callbacks on a `HookRegistry`, it's just handler functions the REPL calls when it receives events. Display logic (Rich panels, token counts, tool status) stays the same.

### Session Spawning and Forking (`session_spawner.py`)

Much thinner than the lite-cli version (574 lines → ~150). The Host handles config merging and service orchestration. The CLI spawner's job is lifecycle management.

**Spawning a sub-session (agent delegation):**

When the orchestrator's `delegate` tool fires, it sends a `request.session_spawn` to the Host. The CLI intercepts and handles it:

1. Take the parent Host instance and the spawn request (agent name, instruction, context settings).
2. Resolve the child agent's definitions via `definitions.resolve_agent()` (same path as `run`).
3. Build a child `SessionConfig`, merging parent's settings with child overrides.
4. Create a new Host instance for the child session.
5. Wire streaming/approval to the same CLI handlers (with nesting depth for display indentation).
6. Run the child host, collect the response.
7. Return the response to the parent host's orchestrator.

**Resuming a sub-session:**

Load transcript/metadata from persistence, reconstruct the child Host from saved config, restore context messages, re-execute.

**Forking (`/fork`):**

Snapshot the current session's transcript and config, create a new session ID, persist the snapshot, continue from there. Purely a persistence operation — the Host doesn't need to know about it.

**Key difference from lite-cli:** No `merge_spawn_configs()` with class-path deduplication, no `ModuleRef` juggling. Works with `ResolvedAgent` objects and `SessionConfig` dicts — service resolution handled by `definitions.py`.

## Data Flow

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

### Definition Resolution Flow

```
resolve_agent("foundation")
  1. agents.yaml lookup → "agent_foundation_3898a638"
  2. Load definitions/agent_foundation_3898a638.yaml
  3. Extract: orchestrator=foundation:streaming, context_manager=foundation:simple
  4. Walk behaviors list:
     - "agents: https://...agents.yaml"
       → fetch, auto-register, collect service
     - "amplifier-dev: https://...amplifier-dev.yaml"
       → fetch, auto-register, collect service
       → amplifier-dev has nested behavior "design-intelligence" → recurse, fetch, collect
     - ... (20+ behaviors)
  5. Deduplicate services by UUID
  6. Return ResolvedAgent with all collected services + selections
```

## Error Handling

- **Unknown agent name:** `Registry.resolve_agent()` raises a clear error — "Agent 'foo' not found. Run `amplifier-ipc discover` to register agents."
- **Remote URL fetch failure:** `definitions.py` catches HTTP errors, reports which behavior URL failed and which agent references it. Does not abort the whole resolution — skips the failed behavior and warns.
- **Service not installed:** Lazy install catches installation failures (missing dependencies, network errors). Reports which service failed. Session can still proceed if the failed service isn't critical.
- **Host events — service crashes:** The Host detects EOF on a service's stdout and surfaces this through the event stream as an error event. The CLI renders it as a Rich error panel.
- **Cancellation:** Ctrl+C → CLI signals Host → Host SIGTERMs services → graceful shutdown. Second Ctrl+C → immediate kill.

## Testing Strategy

### Unit Tests (pure logic, no I/O)

- **`definitions.py`** — Parse agent YAML, walk behavior trees, deduplicate services by UUID, merge `--add-behavior`. Feed YAML strings, assert `ResolvedAgent` output. Mock HTTP fetching with pre-canned responses.
- **`registry.py`** — Register definitions, resolve aliases, read/write `_meta` blocks, hash comparison. Uses a temp directory as `$AMPLIFIER_HOME`.
- **`session_launcher.py`** — Build `SessionConfig` from `ResolvedAgent`. Pure data transformation.

### Integration Tests (CLI → Host, in-process)

The critical path: register a foundation agent definition manually, call `launch_session("foundation")`, verify it resolves definitions → builds config → creates a Host → Host spawns the foundation service → orchestrator loop runs with mock provider → events stream back.

This exercises the full stack without real LLM calls. The foundation service already has a working mock provider.

### Command Tests (Click testing)

- **`run`** — Verify argument parsing, error cases (unknown agent, missing definition).
- **`discover`/`register`/`install`** — Verify they manipulate `$AMPLIFIER_HOME` correctly.
- **Copied commands** (notify, allowed-dirs, etc.) — Bring their existing tests along.

### What We Don't Test in the CLI Package

- Host internals (already tested in `amplifier-ipc-host`).
- Service behavior (already tested per-service).
- Wire protocol (already tested in `amplifier-ipc-protocol`).

The integration test is the most important one — it proves the CLI layer actually connects everything correctly.

## Open Questions

1. **CLI↔Host error propagation** — How exactly do service crashes surface through the Host event stream? Need to define the error event type and what data it carries.
2. **`Host.run()` as async iterator** — The current `Host.run()` is a batch method. It needs to be refactored to yield events. This is a change to `amplifier-ipc-host`, not just the CLI.
3. **Session persistence location** — Does the CLI own persistence (like lite-cli's `SessionStore`) or does the Host? The Host already has `persistence.py` but the CLI needs to manage session listing/deletion/forking.
4. **Lazy install UX** — First run of a newly registered agent may be slow (installing venvs). How to communicate progress? A spinner? Progress bar? Status messages?
