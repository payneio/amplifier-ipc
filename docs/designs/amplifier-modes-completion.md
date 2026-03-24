# Amplifier Modes Service Completion Design

## Goal

Complete the `amplifier-modes` tool implementation by wiring the stubbed `ModeTool` to the already-functional `ModeHooks` instance, enabling set/clear/list/current operations end-to-end.

## Background

The `amplifier-modes` IPC service (`services/amplifier-modes/`) has a fully implemented hook (`hooks/mode.py`) but a completely stubbed tool (`tools/mode.py`). The hook owns all the runtime state (`_active_mode`, `_warned_tools`) and has correct enforcement logic for tool policies and context injection. The tool's four operations — `set`, `clear`, `list`, `current` — are all stubs returning hardcoded values or raising `NotImplementedError`.

The core gap is architectural: `ModeTool` and `ModeHooks` are separate instances created by the protocol `Server` with no cross-component references. The tool cannot reach the hook to read or write state.

## Approach

Use the hook instance as the single source of truth (it already owns the state). Give the tool a reference to the hook via a thin `Server` subclass in `__main__.py`.

This avoids introducing new files, singletons, or protocol changes. The wiring happens at startup in a single overridable method, keeping the coupling minimal and explicit.

## Architecture

```
┌──────────────────────────────────────────────────────┐
│  ModeServer (__main__.py)                            │
│                                                      │
│  _build_runtime_state():                             │
│    super()._build_runtime_state()                    │
│    mode_tool._mode_hooks = mode_hook  ← wiring step  │
│                                                      │
│  ┌──────────────┐       ┌──────────────────┐        │
│  │  ModeTool     │──────▶│  ModeHooks        │       │
│  │  (tools/)     │ ref   │  (hooks/)         │       │
│  │              │       │                    │       │
│  │  set()       │       │  _active_mode      │       │
│  │  clear()     │       │  _warned_tools     │       │
│  │  list()      │       │                    │       │
│  │  current()   │       │  handle()          │       │
│  └──────────────┘       │  _handle_tool_pre()│       │
│                          └──────────────────┘        │
└──────────────────────────────────────────────────────┘
```

The `ModeServer` subclass connects the two components at build time. The hook remains the authoritative owner of mode state. The tool delegates all state reads and writes to the hook via a direct reference.

## Components

### Change 1: `src/amplifier_modes/__main__.py` (~15 lines added)

Subclass `Server` as `ModeServer`. Override `_build_runtime_state()`:

- Call `super()._build_runtime_state()` (populates `self._tools` and `self._hook_instances`)
- Find the `ModeTool` instance in `self._tools` by name
- Find the `ModeHooks` instance in `self._hook_instances` by type
- Wire: `mode_tool._mode_hooks = mode_hook`

This works because:

- `_build_runtime_state()` is a plain overridable method called by both `handle_configure()` and `_ensure_instances()`
- It runs before any IPC requests are served
- Re-configure correctly re-wires (the method is called again)

### Change 2: `src/amplifier_modes/hooks/mode.py` (~10 lines added)

Add three public methods to `ModeHooks`:

```python
def set_active_mode(self, mode: ModeDefinition) -> None:
    self._active_mode = mode
    self._warned_tools.clear()

def clear_active_mode(self) -> None:
    self._active_mode = None
    self._warned_tools.clear()

def get_active_mode(self) -> ModeDefinition | None:
    return self._active_mode
```

No changes to existing hook logic. The hook's `handle()`, `_handle_provider_request()`, and `_handle_tool_pre()` continue reading `self._active_mode` as before.

### Change 3: `src/amplifier_modes/tools/mode.py` (~40 lines replacing stubs)

Add `_mode_hooks = None` class attribute as a safe default.

Implement the four operations:

**`set(name)`**
- Discover modes via `parse_mode_file()` from `hooks/mode.py` (scan `Path.cwd() / ".amplifier/modes/*.md"` and `Path.home() / ".amplifier/modes/*.md"`, project-level takes priority on name collision)
- Find the requested mode by name
- If not found, return error with list of available modes
- Call `self._mode_hooks.set_active_mode(mode_definition)`
- Return mode info

**`clear()`**
- Call `self._mode_hooks.clear_active_mode()`
- Return `{"status": "cleared"}`
- Idempotent — works even if no mode is active

**`current()`**
- Call `self._mode_hooks.get_active_mode()`
- Return mode name/description if active, or `{"active_mode": None}` if not

**`list()`**
- Discover modes (same scan as `set`)
- Return list of `{name, description, shortcut}` for each discovered mode
- Return `{"modes": []}` if no mode files found

## Data Flow

### Mode Discovery

1. Scan `Path.cwd() / ".amplifier" / "modes" / "*.md"` (project-level, takes priority)
2. Scan `Path.home() / ".amplifier" / "modes" / "*.md"` (user-level)
3. Missing directories are silently skipped
4. Malformed files are skipped with a warning to stderr
5. On name collision, project-level wins

### Set Mode Flow

```
User → tool.set("focus")
  → ModeTool discovers mode files
  → Finds matching ModeDefinition
  → Calls ModeHooks.set_active_mode(definition)
  → ModeHooks sets _active_mode, clears _warned_tools
  → Returns mode info to user

Subsequent tool calls:
  → ModeHooks._handle_tool_pre() reads _active_mode
  → Enforces tool policies, injects context as before
```

### Wiring Flow

```
Server startup / reconfigure
  → ModeServer._build_runtime_state()
  → super()._build_runtime_state()  (creates tool + hook instances)
  → Finds ModeTool in self._tools
  → Finds ModeHooks in self._hook_instances
  → Sets mode_tool._mode_hooks = mode_hook
  → Ready to serve requests
```

## Error Handling

| Scenario | Behavior |
|---|---|
| `set` with unknown mode | Re-run discovery (in case new files added mid-session), then return error with available modes list if still not found |
| `set` when mode already active | Replace it, reset warned tools |
| `clear` when no mode active | Return success (idempotent) |
| No mode files on disk | `list` returns empty, `set` returns error |
| Malformed `.md` file | Skip with stderr warning, don't break other modes |
| `_mode_hooks` is None (wiring failed) | Return `{"error": "Mode service not ready"}` |

## Testing Strategy

- **Tool operations**: set/clear/list/current with mock mode files (use `tmp_path`)
- **Wiring**: verify `ModeServer` subclass correctly wires tool to hook
- **Integration**: set mode via tool, verify hook reads it from state
- **Error cases**: unknown mode, no mode files, malformed files, clear when nothing active
- **Discovery**: project-level priority over user-level, missing dirs skipped

## Non-Goals

- Modifying the shared protocol `server.py`
- Creating a state singleton or new abstraction
- Adding a generic tool-to-hook injection mechanism
- Built-in/bundled mode definitions (modes come from filesystem only)

## What Stays the Same

- Hook logic (`_handle_provider_request`, `_handle_tool_pre`) — unchanged
- `HookAction.INJECT_CONTEXT` — already handled by `StreamingOrchestrator` in amplifier-foundation, works end-to-end
- `ModeDefinition` dataclass — unchanged
- `parse_mode_file()` — unchanged (may need to be importable from tools; import from hooks module)
- Protocol server (`server.py`) — zero changes
- No new files created
- CWD inherited from process spawn — no configure-time plumbing needed

## Scope Summary

Three files changed, all within `services/amplifier-modes/`:

| File | Change | Lines |
|---|---|---|
| `src/amplifier_modes/__main__.py` | Add `ModeServer` subclass with wiring override | ~15 |
| `src/amplifier_modes/hooks/mode.py` | Add 3 public accessor methods | ~10 |
| `src/amplifier_modes/tools/mode.py` | Replace stubs with real implementations | ~40 |
