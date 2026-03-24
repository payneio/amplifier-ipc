# Amplifier IPC: Architectural Comparison

This document compares the architecture of the original Amplifier system with Amplifier IPC, validated against both codebases. Each claim is backed by specific file references and line counts.

---

## Executive Summary

Amplifier IPC replaces ~33,750 lines of Python and ~21,700 lines of Rust (55,450 total) with ~15,750 lines of Python. The core orchestration layer (host + protocol) is 2,719 lines. All figures are from `cloc` — excluding blanks, comments, tests, and content files.

| | Old | New |
|--|-----|-----|
| Core (kernel + foundation / host + protocol) | 16,899 Python + 21,695 Rust | 2,719 Python |
| Services | — | 8,083 |
| CLI | 16,854 | 4,940 |
| **Total** | **55,448** | **15,742** |

This isn't a rewrite for its own sake; each reduction traces to a concrete architectural problem that was causing friction for the team.

---

## 1. No Kernel

### The Problem

The old kernel (`amplifier-core`) was an exec loop over modules with a custom runtime loader. `session.py` (259 lines) called `orchestrator.execute(prompt, context, providers, tools, hooks, coordinator)` — but supporting that simple call required:

- `loader.py` — 728 lines of module discovery, source resolution, and polyglot dispatch
- 3,392 lines of module validation code
- 28,330 lines of Rust engine (`crates/amplifier-core/`) providing the `ModuleCoordinator`, WASM runtime, and manifest system
- `_session_init.py` — 257 lines of initialization sequencing
- `hooks.py` — 348 lines of hook registration

All of this existed to load Python modules into a shared process at runtime — something Python's import system already does.

### What Changed

The host (`src/amplifier_ipc/host/host.py`, 971 lines) replaces the kernel, coordinator, loader, and validation system. It spawns services as subprocesses, sends a `describe` RPC to discover capabilities, and routes requests between them. Module loading is handled by Python's import system. Dependency management is handled by uv.

### Why It Matters

- **Static analysis works again.** The old runtime mounting bypassed Python's import system, so type checkers, linters, and IDE navigation couldn't follow the code. With standard imports, errors surface at load time instead of silently at runtime.
- **No coordinator or capability registry.** The old `ModuleCoordinator` (Rust, re-exported via PyO3) served as both a mount-point registry and an inversion-of-control container. Because session spawning lived in the CLI — not the core — modules couldn't import app-layer logic directly. Instead, the CLI registered functions like `session.spawn` into the coordinator at startup, and modules pulled them out at runtime via `coordinator.get_capability("session.spawn")`. This created a hidden dependency graph: modules depended on capabilities that might or might not be registered depending on which app layer was hosting them, with failures only surfacing at runtime when a module called `get_capability()` and got `None`. In IPC, spawning lives in the host, so there's no layer inversion to paper over. Services make explicit RPC calls (`request.session_spawn`) with well-defined request/response contracts — the dependency is visible in the protocol, not hidden behind a runtime lookup.
- **No mount plans.** The old system required explicit mount plan configuration specifying which modules go to which mount points, with a hardcoded type-to-mount-point mapping in the kernel. Adding a new component type meant changing the kernel. Misconfigured mount plans failed silently or with opaque errors at runtime. In IPC, services self-describe their capabilities via a `describe` RPC — the host discovers what's available automatically. There is no mount plan to misconfigure.

---

## 2. No Bundles

### The Problem

The fundamental issue with bundles was that **reading configuration triggered installation as a side effect.** The `Bundle` dataclass (`amplifier-foundation/bundle.py`, 1,390 lines) mixed what an agent should do (configuration) with how to make it runnable (installation) in a single abstraction.

A bundle markdown file declared both intent and sourcing together:

```yaml
# Old bundle.md — configuration and installation are inseparable
session:
  orchestrator:
    module: loop-streaming
    source: git+https://github.com/microsoft/amplifier-module-loop-streaming@main
  context:
    module: context-simple
    source: git+https://github.com/microsoft/amplifier-module-context-simple@main
tools:
  - module: tool-filesystem
    source: git+https://github.com/microsoft/amplifier-module-tool-filesystem@main
```

When this bundle was loaded, the system couldn't just read it — it had to act on it. `Bundle.prepare()` was an async method on what should have been a data structure, and it:

1. Downloaded modules from git/file/http URIs via `ModuleActivator`
2. Installed Python dependencies via `uv pip install --target`
3. Modified `sys.path` to make modules importable
4. Cached the results in a custom registry

This meant you couldn't inspect what an agent needed without triggering downloads. You couldn't test bundle composition without installing modules. You couldn't reason about dependencies statically. Configuration and installation were inseparable.

This conflation rippled outward into additional problems:

- **Silent naming conflicts.** Agent names merged via `.update()` — a later bundle silently overwrote an earlier one's definition. Context keys had the same issue.
- **Inconsistent composition rules.** `session` used deep merge, `providers`/`tools`/`hooks` merged by module ID, `agents` used replace, `context` accumulated with namespace prefixing. These rules varied by field type and weren't documented in code.
- **Custom package management.** `activator.py` (487 lines), `install_state.py` (233 lines), and `registry.py` (1,301 lines) reimplemented what `uv sync` already does — URI resolution, dependency caching, install-state tracking — because bundles needed their own packaging layer.

### What Changed

In IPC, configuration is pure data with no side effects. The phases are cleanly separated:

```
1. Parse          →  Read agent/behavior YAML (pure function, no I/O)
2. Resolve        →  Walk behavior tree, collect service list (no installation)
3. Install        →  Explicitly install services if not already present
4. Spawn          →  Start service subprocesses
5. Discover       →  Call describe RPC on each service
```

Agent definitions are ~20-line YAML files. They declare intent without specifying how to install anything:

```yaml
# New agent definition — pure configuration, no installation side effects
agent:
  ref: foundation
  description: Full-featured Amplifier agent
  orchestrator: amplifier-foundation:streaming
  context_manager: amplifier-foundation:simple
  behaviors:
    - amplifier-foundation
    - amplifier-providers
    - amplifier-routing-matrix
  service:
    stack: uv
    source: ./services/amplifier-foundation
```

Packaging lives in each service's `pyproject.toml` — standard Python packaging, managed by `uv sync`. The definition parser (`definitions.py`) is a pure synchronous function that returns Pydantic models. `resolve_agent()` walks the behavior tree and returns a `ResolvedAgent` listing what services are needed — without downloading, installing, or modifying anything.

### Why It Matters

- **Configuration is data, not executable code.** You can parse, compose, validate, and test agent definitions without triggering any side effects. The old system made this impossible — reading a bundle was an action that modified the environment.
- **Dependency analysis before commitment.** `resolve_agent()` returns a complete list of needed services before anything is installed. You can inspect, filter, or reject before spending time on downloads. In the old system, you discovered what you needed by installing it.
- **No custom package management.** The ~2,000 lines of activator, install-state, and registry code are gone. Each service is a standard Python package with a `pyproject.toml`. `uv sync` handles everything.
- **Composition is explicit.** An agent lists its behaviors. Each behavior is a self-contained service. No merge rules, no silent overwrites, no namespace prefixing surprises.

---

## 3. Polyglot via Process Boundaries, Not Kernel Internals

### The Problem

The old kernel supported three integration methods for non-Python modules:

1. **Python native** — direct import
2. **gRPC** — `loader_grpc.py` (226 lines) wrapping remote services as Python tool objects
3. **WASM** — Rust-side instantiation with Python wrapper (~35 lines)

The Python-side code was modest (~300 lines), but the Rust engine backing it was 28,330 lines. Each integration method had different semantics, different error modes, and different debugging stories. All of this complexity existed to get modules from different languages into the same process.

### What Changed

IPC services communicate over newline-delimited JSON-RPC on stdin/stdout. The framing layer is 40 lines (`protocol/framing.py`). Any language that can read stdin and write stdout can be a service.

### Why It Matters

- **Polyglot is free.** There's no integration code per language. A Go service, a Rust service, and a Python service all look identical to the host — they respond to `describe` and handle requests.
- **No Rust engine dependency.** The 28K-line Rust codebase (with PyO3 bindings, WASM runtime, manifest system) is eliminated entirely. The protocol is pure Python.
- **One debugging model.** Every service interaction is a JSON message on a pipe. You can log, inspect, and replay any interaction without language-specific tooling.

---

## 4. Process Isolation

### The Problem

In the old system, all modules ran in the same Python process. A buggy tool could corrupt shared state, leak memory, or crash the entire session. All modules shared one virtual environment, so dependency conflicts between modules were a constant source of friction.

### What Changed

Each service runs as a separate subprocess (`lifecycle.py`, lines 49-57) with `start_new_session=True` for process group isolation. Each service has its own uv-managed virtual environment with independent dependencies declared in its own `pyproject.toml`.

### Why It Matters

- **Fault isolation.** A crashing tool service doesn't take down the session. The host detects the subprocess exit and reports the error while the rest of the system continues.
- **Dependency isolation.** Service A can use `pydantic==2.0` while Service B uses `pydantic==1.10`. No conflicts, no workarounds.
- **No stale state.** Services can be freshly spawned each turn. The host replays `transcript.jsonl` into the context manager, so conversation history survives across process restarts. This eliminates an entire class of bugs where long-running modules accumulate corrupted state.

---

## 5. Session State in the Right Place

### The Problem

Session state management lived in the CLI, not the core. The old CLI dedicated significant code to this:

- `session_store.py` — 526 lines (filesystem persistence)
- `session_runner.py` — 685 lines (execution loop, streaming, approval gates)
- `session_spawner.py` — 897 lines (sub-session forking)
- `main.py` — 2,004 lines (CLI entrypoint with session management woven throughout)

Total CLI codebase: ~27,901 lines. This meant any new client (web service, SDK, IDE plugin) would need to reimplement session management from scratch.

### What Changed

Session management lives in the host layer:

- `host.py` — 971 lines (session execution, orchestrator loop, event dispatch)
- `persistence.py` — 67 lines (transcript storage)
- `spawner.py` — 501 lines (child session handling)

The CLI (`src/amplifier_ipc/cli/`, ~2,800 lines) is a thin consumer of `Host.run()`, which yields an `AsyncIterator[HostEvent]`. Any client can consume this same iterator.

### Why It Matters

- **One implementation, many clients.** The CLI, a web service, and a Python SDK all use the same `Host` class. Session persistence, child spawning, and event routing don't need to be reimplemented per client.
- **Streaming is decoupled from transport.** `Host.run()` yields typed events (`StreamTokenEvent`, `ToolCallEvent`, `ApprovalRequestEvent`, etc.). The consumer decides how to render them — the host doesn't care whether it's a terminal, a WebSocket, or a test harness.

---

## 6. Inversion of Control: From Runtime Lookup to Protocol Contract

### The Problem

The old system used an IoC pattern via the coordinator's capability registry to work around a layering problem. Core functionality that modules needed — session spawning, mention resolution, working directory tracking, delegation depth limits — lived in the CLI, not the core. Since modules couldn't import from the app layer, the CLI registered functions and values into the coordinator at startup:

```python
# CLI (session_runner.py) — registers capabilities
session.coordinator.register_capability("session.spawn", spawn_capability)
session.coordinator.register_capability("session.resume", resume_capability)
session.coordinator.register_capability("mention_resolver", mention_resolver)
session.coordinator.register_capability("session.working_dir", working_dir)
session.coordinator.register_capability("self_delegation_depth", depth)
```

Modules then pulled these out at runtime:

```python
# Module (tool-delegate) — consumes capabilities
spawn_fn = coordinator.get_capability("session.spawn")
if spawn_fn:
    result = await spawn_fn(agent_name="zen-architect", task="analyze this")
else:
    raise ToolError("session.spawn capability not available")
```

This had several consequences:

- **Hidden dependency graph.** A module's dependencies weren't visible in its imports or configuration — they were string-keyed lookups that might return `None` depending on which app layer happened to be hosting the session. A module that worked in the CLI could silently break when embedded in a web service that didn't register the same capabilities.
- **No contract enforcement.** The capability names were strings, the values were untyped (`Any`). The coordinator couldn't verify that a registered function matched the contract a consumer expected. Mismatches surfaced as runtime errors deep in execution.
- **Capability propagation during spawning.** Every child session needed the CLI to manually re-register all capabilities into the child coordinator (`session_spawner.py`, 13 separate `register_capability` calls across spawn and resume paths). Missing a registration meant a child session silently lost functionality.

### What Changed

In IPC, the functionality that modules need lives in the host, not the CLI. There is no capability registry. Instead, services make explicit RPC calls through the protocol:

```python
# Service (orchestrator or tool) — explicit RPC call
result = await client.request("request.session_spawn", {
    "agent": "zen-architect",
    "instruction": "analyze this"
})
```

The host handles `request.session_spawn`, `request.state_get`, `request.state_set`, and all other cross-cutting concerns directly. These are defined methods in the protocol with typed request/response shapes.

### Why It Matters

- **Dependencies are visible in the protocol.** A service's dependencies are the RPC methods it calls — enumerable, documented, and testable. There's no hidden `get_capability()` that might return `None`.
- **Contract enforcement via JSON-RPC.** Every request has a defined method name, parameter schema, and response shape. A malformed request gets a `INVALID_PARAMS` error with a clear message, not a silent `None` or a runtime `AttributeError`.
- **No capability propagation.** Child sessions share the parent's host, which already handles all RPC methods. There's nothing to re-register — the 13 `register_capability` calls in the old spawner are gone entirely.
- **App layer independence.** A service works identically whether the host is driven by the CLI, a web server, or a test harness. The protocol is the contract, not the app layer's registration behavior.

---

## 7. Self-Describing Services

### The Problem

In the old system, the bundle had to declare all its components upfront in configuration. The kernel then validated these declarations against what it found at runtime. This required substantial validation code (3,392 lines) and meant that adding a new tool required changes in two places: the tool code and the bundle configuration.

### What Changed

Each service responds to a `describe` RPC call with its full capability manifest:

```json
{
  "name": "amplifier-foundation",
  "capabilities": {
    "tools": [{"name": "bash", "description": "...", "input_schema": {...}}],
    "hooks": [{"name": "approval", "events": ["tool:pre"], "priority": 5}],
    "orchestrators": [{"name": "streaming"}],
    "context_managers": [{"name": "simple"}],
    "providers": []
  }
}
```

The `CapabilityRegistry` (`registry.py`, 184 lines) builds the routing table dynamically from these responses.

### Why It Matters

- **Single source of truth.** A tool exists because it has a `@tool` decorator. There's no separate configuration file to keep in sync. The five decorator functions (`@tool`, `@hook`, `@orchestrator`, `@context_manager`, `@provider`) are each under 10 lines.
- **No validation layer.** The 3,392-line validation subsystem is gone. If a service reports a capability, it exists. If it doesn't implement it correctly, the error surfaces as a failed RPC call with a clear JSON-RPC error — not a validation failure at load time with an opaque message.

---

## 8. Bidirectional RPC

### The Problem

The old orchestrator received everything it might need as arguments to a single `execute()` call: prompt, context, providers, tools, hooks, and coordinator. This push model meant the orchestrator had to accept the full set upfront, even if it only needed a subset for a given turn.

### What Changed

The orchestrator is a service that can make requests back to the host during execution:

- `request.tool_execute` — run a specific tool
- `request.provider_complete` — call an LLM provider
- `request.hook_emit` — fire a hook event
- `request.context_get_messages` — retrieve conversation history
- `request.session_spawn` — create a child agent session
- `request.state_get` / `request.state_set` — read/write cross-turn state

The host's router (`router.py`, 297 lines) dispatches these to the appropriate service.

### Why It Matters

- **Pull model.** The orchestrator requests what it needs when it needs it. This enables lazy evaluation — a tool's service doesn't need to be spawned until the orchestrator actually calls it.
- **Orchestrator flexibility.** Different orchestrators can use completely different execution strategies (single-turn, multi-turn, parallel tool calls, human-in-the-loop approval) without the host needing to know about any of them. The protocol is the same.

---

## 9. Shared Services Across Child Sessions

### The Problem

The old system's sub-session spawning (`session_spawner.py`, 897 lines) forked the parent's entire session configuration and re-initialized all modules. This was expensive and could lead to redundant service instances.

### What Changed

`spawner.py` (501 lines) creates child sessions that reuse the parent's already-running service processes via a `shared_services` mechanism. The child gets its own orchestrator loop and filtered capability set, but tools, hooks, and providers are shared.

### Why It Matters

- **Sub-agent spawning is cheap.** No redundant service startup. A child session adds one orchestrator call, not N service spawns.
- **Consistent state.** Shared services mean a tool's state (if any) is consistent across parent and child sessions within a turn.

---

## Size Comparison

All figures from `cloc` (excludes blanks, comments, tests, and content files).

| Component | Old (LOC) | New (LOC) | Notes |
|-----------|-----------|-----------|-------|
| Core (kernel/host + protocol) | 6,790 Python + 21,695 Rust | 2,719 Python | Rust engine eliminated entirely |
| Foundation / Services | 10,109 | 8,083 | Independent service packages |
| CLI | 16,854 | 4,940 | Thin consumer of Host API |
| **Total** | **33,753 Python + 21,695 Rust** | **15,742 Python** | |

---

## Summary of Architectural Wins

| Win | Old Approach | New Approach | Impact |
|-----|-------------|-------------|--------|
| Standard packaging | Custom bundle loading, activation, caching | `uv sync` + `pyproject.toml` | Eliminates ~2K LOC of reimplemented package management |
| Standard imports | Runtime module mounting via coordinator | Python `import` | Static analysis, type checking, and IDE navigation work |
| Process isolation | Shared process, shared venv | Subprocess per service, venv per service | Fault isolation, dependency isolation, no stale state |
| Polyglot | Three integration methods in kernel | stdin/stdout JSON-RPC | Any language works, 40 lines of framing code |
| Self-describing services | Bundle config + kernel validation | `describe` RPC + decorators | Single source of truth, no sync issues |
| Bidirectional RPC | Push all dependencies to orchestrator | Orchestrator pulls what it needs | Lazy evaluation, flexible execution strategies |
| Session state in host | Reimplemented per client (CLI) | `Host.run()` yields typed events | One implementation serves CLI, web, SDK |
| Explicit composition | Deep merge / replace / accumulate rules | Agent YAML lists behaviors | No silent overwrites, predictable behavior |
| Shared child services | Full re-initialization per sub-session | Reuse parent service processes | Cheap sub-agent spawning |
| Transcript replay | Long-lived in-process state | Replay `transcript.jsonl` per turn | Eliminates stale state bugs |
