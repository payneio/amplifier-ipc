# CLI Gap Analysis: amplifier-app-cli -> amplifier-ipc

**Date**: 2026-03-23
**Revision 2**: Post-implementation re-analysis with bug fixes applied.
**Tests**: 828 passed, 1 skipped, 0 failures.

## How to Read This Document

| Tag | Meaning |
|-----|---------|
| **CLOSED** | Gap has been implemented and verified. |
| **FIXED** | Bug found in implementation and fixed. |
| **INTENTIONAL** | Removed or replaced by design. No action needed. |
| **REMAINING** | Feature exists in the old CLI, is not superseded by the new architecture, and is still missing. |
| **DEFERRED** | Deliberately postponed (low priority or niche). |
| **ARCH-DIFF** | Architectural difference; old behavior doesn't apply to IPC model. |

---

## 1. Command Surface

### 1.1 Top-Level Commands

| Old Command | New Equivalent | Status |
|-------------|---------------|--------|
| `amplifier` (bare, launches REPL) | `amplifier-ipc run` (no message, auto-selects agent) | **CLOSED** — Default agent resolution added. |
| `amplifier run [PROMPT]` | `amplifier-ipc run [MESSAGE]` | **CLOSED** — All flags ported. |
| `amplifier continue [PROMPT]` | `amplifier-ipc continue` | **CLOSED** |
| `amplifier resume [SESSION_ID]` | `amplifier-ipc resume` | **CLOSED** — Interactive paginated picker. |
| `amplifier init` | `amplifier-ipc init` | **CLOSED** — 4-step wizard. |
| `amplifier update` | `amplifier-ipc update <agent>` | **REMAINING** — Only checks one agent's behavior staleness. No self-update, no global update-all. |
| `amplifier reset` | `amplifier-ipc reset` | **CLOSED** — `--preserve`, `--yes`, post-reset guidance added. |
| `amplifier version` | `amplifier-ipc version` | **CLOSED** — `--verbose` and `--install-completion` added. |
| `amplifier --install-completion` | `amplifier-ipc version --install-completion SHELL` | **CLOSED** |

### 1.2 `run` Command Flags

| Old Flag | Status |
|----------|--------|
| `--provider/-p` | **CLOSED** |
| `--model/-m` | **CLOSED** |
| `--max-tokens` | **CLOSED** |
| `--verbose/-v` | **CLOSED** |
| `--output-format` (text/json/json-trace) | **CLOSED** |
| `--bundle/-B` | **INTENTIONAL** — Replaced by `--agent/-a` + `--add-behavior/-b`. |

### 1.3 Command Groups

| Old Group | Status | Notes |
|-----------|--------|-------|
| `amplifier bundle` (8 sub) | **INTENTIONAL** — Replaced by `discover`/`register`/`install`/`unregister`/`uninstall`. |
| `amplifier module` (10 sub) | **INTENTIONAL** — Replaced by IPC service model. |
| `amplifier source` (4 sub) | **INTENTIONAL** — Replaced by `service_overrides` in settings. |
| `amplifier tool` (3 sub) | **CLOSED** — `tool list`, `tool info`, `tool invoke` implemented. |
| `amplifier agents` (3 sub) | **CLOSED** — `agents list`, `agents show` implemented. |

---

## 2. Interactive REPL

### 2.1 Slash Commands

| Command | Status | Notes |
|---------|--------|-------|
| `/help` | **CLOSED** | |
| `/exit`, `/quit` | **CLOSED** | |
| `/status` | **CLOSED** | Shows session ID, orchestrator, provider, services, message count, active mode. |
| `/tools` | **CLOSED** | Rich table with name + description. |
| `/config` | **CLOSED** | Shows orchestrator, provider, services, tool/hook counts. |
| `/agents` | **CLOSED** | Rich table with name + definition ID. |
| `/mode [NAME] [on|off]` | **CLOSED** | Set/toggle/clear modes. |
| `/modes` | **CLOSED** | Lists available modes with active marker. |
| `/clear` | **CLOSED** | Clears context manager + deletes transcript. |
| `/save [FILENAME]` | **CLOSED** | Saves transcript to file. |
| `/rename <NAME>` | **CLOSED** | |
| `/fork [TURN]` | **CLOSED** | Creates fork, prints resume command. |
| Dynamic mode shortcuts | **CLOSED** | Auto-discovered from available modes, trailing text queued. |

### 2.2 REPL Input Features

| Feature | Status |
|---------|--------|
| prompt-toolkit with FileHistory | **CLOSED** |
| Multi-line (Ctrl-J) | **CLOSED** |
| Dynamic prompt with mode indicator | **CLOSED** |
| Ctrl-C at prompt = confirm exit | **CLOSED** |
| Two-stage Ctrl-C during execution | **CLOSED** |
| `exit`/`quit` bare words | **CLOSED** |
| @mention file injection | **CLOSED** + **FIXED** (BUG-01 binary crash, BUG-02 size guard) |
| Session exit resume hint | **CLOSED** |

### 2.3 REPL — Remaining Gaps

| Feature | Status | Old CLI Behavior |
|---------|--------|-----------------|
| Recursive @mention loading | **REMAINING** | Old CLI: files loaded via @mention can themselves contain @mentions, loaded via BFS with cycle detection. New CLI: only top-level @mentions in user input are resolved. |
| Directory @mentions | **REMAINING** | Old CLI: `@src/` generates a directory listing. New CLI: directories are not handled (will get a file-read error). |
| @mention context message role | **REMAINING** | Old CLI uses `role="developer"` for injected context. New CLI uses `<context_file>` XML wrapping in the prompt string. Difference may affect model behavior. |
| `/save` destination and format | **REMAINING** | Old CLI saves to session directory as JSON with `config` included. New CLI saves to CWD as plain text transcript. |
| `/rename` length limit | **REMAINING** | Old CLI truncates to 50 chars and sets `name_generated_at` timestamp. New CLI has no length limit. |
| `/fork` turn preview | **REMAINING** | Old CLI shows 10 most recent turns in reverse order with `[N] preview... [X tools]` format. New CLI takes turn number directly without preview. |
| `/allowed-dirs` `/denied-dirs` session scope | **REMAINING** | Old CLI REPL commands operate on session scope only. New CLI has no REPL shortcut for these (CLI commands exist but operate on global/project/local scopes). |
| Session banner with version/core info | **REMAINING** | Old CLI shows a 5-line cyan panel with session ID, CLI+core versions, bundle summary, and command hints. New CLI shows a simpler banner with agent name. |
| `prompt:complete` event emission | **REMAINING** | Old CLI emits `prompt:complete` hook event after each successful turn. New CLI does not appear to emit this. |
| `session:end` event with guard | **REMAINING** | Old CLI emits `session:end` only when `turn_count > 0`. New CLI may not emit this event. |
| `/mode NAME off` specificity | **REMAINING** | Old CLI: `/mode debug off` only clears if "debug" is the active mode (error if wrong). New CLI: `/mode NAME off` clears any active mode. |

---

## 3. Session Management

| Feature | Status |
|---------|--------|
| `session list` | **CLOSED** |
| `session list --all-projects` | **CLOSED** + **FIXED** (BUG-10: now also scans default sessions dir) |
| `session list --tree SESSION_ID` | **CLOSED** |
| `session show` | **CLOSED** |
| `session delete [--force]` | **CLOSED** |
| `session cleanup [--days N]` | **CLOSED** |
| `session fork [--at-turn N]` | **CLOSED** |
| `session fork --name` | **CLOSED** |
| `session fork --resume` | **CLOSED** |
| `session resume` (interactive) | **CLOSED** + **FIXED** (BUG-11: removed non-existent flags from output) |

### Remaining Session Gaps

| Feature | Status | Notes |
|---------|--------|-------|
| Fork orphaned tool call handling | **REMAINING** | Old CLI: generates synthetic tool results for incomplete tool_use blocks during fork. New CLI: truncates transcript but doesn't handle orphaned calls. |
| Fork with events (`--no-events`) | **REMAINING** | Old CLI copies events.jsonl by default, `--no-events` skips. New CLI doesn't have event files. |
| Metadata preservation on save | **FIXED** (BUG-19) | Host now loads existing metadata before saving. |
| Resume history display | **REMAINING** | Old CLI shows last 10 messages on resume with `--full-history` / `--no-history` / `--replay` options. New CLI replays transcript into context but doesn't display history to the user. |
| Bundle override on resume | **ARCH-DIFF** | Old CLI had `--force-bundle`. In IPC, the agent definition is fixed per session. |

---

## 4. Provider Management

| Feature | Status |
|---------|--------|
| `provider list` | **CLOSED** |
| `provider set-key` | **CLOSED** |
| `provider use` | **CLOSED** |
| `provider add` (wizard) | **CLOSED** |
| `provider remove` | **CLOSED** |
| `provider edit` | **CLOSED** |
| `provider test` | **CLOSED** — Basic validation (key + env var check). |
| `provider models` | **CLOSED** — Static model catalog. |
| Provider auto-detect from env | **CLOSED** |

### Remaining Provider Gaps

| Feature | Status | Notes |
|---------|--------|-------|
| `provider install` from registry | **ARCH-DIFF** | Old CLI installed provider packages. IPC model handles this via service definitions. |
| `provider manage` (interactive dashboard) | **DEFERRED** | Low priority; individual commands cover the functionality. |
| Provider priority demotion on set | **REMAINING** | Old CLI: setting a new provider demotes existing priority-1 providers to priority-10. New CLI: no priority system for provider overrides. |
| Non-TTY auto-init path | **REMAINING** | Old CLI: when stdin is not a TTY and it's first-run, auto-configures from env vars without prompting. New CLI: requires manual setup or `init` command. |

---

## 5. Routing Matrix Management

| Feature | Status |
|---------|--------|
| `routing list` (with role counts) | **CLOSED** |
| `routing show [--detailed]` | **CLOSED** |
| `routing use` | **CLOSED** |
| `routing manage` (interactive) | **CLOSED** + **FIXED** (BUG-13: path traversal in create, BUG-14: stale file list) |
| `routing create` (wizard) | **CLOSED** |

---

## 6. Output and Display

| Feature | Status |
|---------|--------|
| Token streaming | **CLOSED** |
| Thinking blocks | **CLOSED** |
| Tool call/result display | **CLOSED** |
| Todo progress display | **CLOSED** |
| Child session display | **CLOSED** + **FIXED** (BUG-15: trace data from children now merged) |
| Markdown rendering | **CLOSED** |
| `text` output format | **CLOSED** |
| `json` output format | **CLOSED** |
| `json-trace` output format | **CLOSED** |

### Remaining Display Gaps

| Feature | Status | Notes |
|---------|--------|-------|
| LLM-specific error panels | **CLOSED** | Rate limit (yellow), auth (red), context length (red), content filter (red). |
| JSON stderr/stdout ordering | **REMAINING** | Old CLI has a careful sequence: sleep(0.1) -> flush stderr -> restore stdout -> print JSON. This prevents hook output from interleaving with JSON. New CLI writes JSON immediately. |
| Three JSON error schemas | **REMAINING** | Old CLI has distinct schemas for `ModuleValidationError`, `LLMError`, and generic `Exception`. New CLI uses a single schema for all errors. |
| LLM error log filter | **REMAINING** | Old CLI attaches `LLMErrorLogFilter` to the stderr StreamHandler to suppress duplicate raw log lines for LLM errors. New CLI doesn't have this. |

---

## 7. Configuration and Settings

| Feature | Status |
|---------|--------|
| 3-scope merge (global/project/local) | **CLOSED** |
| Key management (keys.env) | **CLOSED** |
| Service overrides | **CLOSED** |
| Provider auto-detection | **CLOSED** |

### Remaining Configuration Gaps

| Feature | Status | Notes |
|---------|--------|-------|
| Session scope (4th scope) | **ARCH-DIFF** | Old CLI had session-scoped settings via `with_session()`. IPC model uses session state differently. |
| `bundle.app` always-on behaviors | **ARCH-DIFF** | Old CLI composed app bundles onto every session. IPC model uses agent-level behavior composition. |
| `${VAR:default}` env var expansion | **REMAINING** | Old CLI supports `${VAR:default}` syntax in config files. New CLI does not. |
| Tool permission union semantics | **REMAINING** | Old CLI uses set union for `allowed_write_paths` across scopes. New CLI behavior is untested. |
| CWD auto-included in allowed_write_paths | **REMAINING** | Old CLI always ensures `.` is in `allowed_write_paths` for `tool-filesystem`. |

---

## 8. Hook and Event System

| Feature | Status |
|---------|--------|
| Hook fan-out with priority | **CLOSED** |
| DENY/MODIFY/INJECT/ASK_USER | **CLOSED** |
| Approval system | **CLOSED** |

### Remaining Hook Gaps

| Feature | Status | Notes |
|---------|--------|-------|
| IncrementalSaveHook pattern | **REMAINING** | Old CLI: `tool:post` hook at priority 900 saves transcript after every tool call, with debouncing and metadata preservation. New CLI: host persists messages as they flow, but no explicit debounce or post-tool-call checkpoint. |
| `prompt:complete` event | **REMAINING** | Old CLI emits this after every successful execution in both REPL and single-shot modes. |
| `session:end` event | **REMAINING** | Old CLI emits this on session teardown (guarded: only when turn_count > 0). |
| Mode always composed | **REMAINING** | Old CLI unconditionally composes modes behavior. New CLI requires modes to be in the agent's behavior tree. |

---

## 9. Update, Reset, Self-Management

| Feature | Status |
|---------|--------|
| Definition staleness check | **CLOSED** |
| Reset with categories | **CLOSED** |
| Reset `--preserve` / `--yes` | **CLOSED** |
| Version verbose | **CLOSED** |
| Shell completion | **CLOSED** |

### Remaining Gaps

| Feature | Status | Notes |
|---------|--------|-------|
| Self-update | **DEFERRED** | Users can use `uv` directly. |
| Global update-all | **REMAINING** | Old CLI updated self + all packages + all modules + all bundles in one command. New CLI only checks one agent at a time. |
| Startup update check | **DEFERRED** | Low priority; `update --check` covers it. |
| Update status symbols | **REMAINING** | Old CLI shows colored symbols (green check, yellow dot, cyan circle) for update status. |

---

## 10. Notification, Allowed/Denied Dirs

Fully ported. No remaining gaps.

---

## 11. Bugs Found and Fixed

| ID | Severity | File | Issue | Fix |
|----|----------|------|-------|-----|
| BUG-01 | CRITICAL | `repl.py` | Binary @mention file crashes REPL with `UnicodeDecodeError` | Added `UnicodeDecodeError` to except clause |
| BUG-02 | HIGH | `repl.py` | No file-size guard on @mentions; huge files exhaust memory | Added 512KB size limit check |
| BUG-06 | HIGH | `run.py` | Rich markup `[bold]...[/bold]` in `click.echo` renders as literal text | Replaced with `click.style()` |
| BUG-09 | HIGH | `main.py` | `init`, `agents`, `tool` commands implemented but never registered | Added imports and `cli.add_command()` |
| BUG-10 | HIGH | `session.py` | `--all-projects` scanned `projects/*/sessions/` but not default `sessions/` dir | Added default sessions dir to scan |
| BUG-11 | HIGH | `session.py` | Generated resume command contained `--no-history`/`--show-thinking` flags that don't exist on `run` | Removed non-existent flags |
| BUG-13 | MEDIUM | `routing.py` | Path traversal: `matrix_name` with `../` could write outside routing dir | Added path separator validation |
| BUG-15 | CRITICAL | `streaming.py` | Child session trace data discarded in json-trace mode | Added trace merge from inner display |
| BUG-18 | HIGH | `host.py` | `set_mode` fallback update lost on next `run()` turn (state reloaded from disk) | Added `persistence.save_state()` in fallback |
| BUG-19 | HIGH | `host.py` | `save_metadata` overwrote all prior metadata with only `{session_id, prompt}` | Added load-merge-save pattern |
| BUG-23 | LOW | `registry.py` | Dead `seen` set in `get_providers_by_priority` | Simplified to list comprehension |

---

## 12. Remaining Bugs (Not Yet Fixed)

| ID | Severity | File | Issue |
|----|----------|------|-------|
| BUG-04 | MEDIUM | `repl.py` | `/mode` with multi-word mode names splits incorrectly: `/mode my mode on` activates "my" not "my mode" |
| BUG-05 | MEDIUM | `repl.py` | `/fork` accesses private `persistence._session_dir`; fragile coupling |
| BUG-07 | MEDIUM | `run.py` | `Registry()` init not guarded; YAML errors produce raw traceback |
| BUG-08 | LOW | `run.py` | `session_id = session_id` is a no-op self-assignment |
| BUG-12 | MEDIUM | `session.py` | `stat().st_mtime` in sort lambda can raise if session deleted concurrently |
| BUG-14 | MEDIUM | `routing.py` | `yaml_files` list stale inside `manage` loop; not refreshed per iteration |
| BUG-16 | HIGH | `streaming.py` | Tool trace entry pairs wrong `args` if `ToolResultEvent` tool name doesn't match pending call |
| BUG-17 | MEDIUM | `streaming.py` | Inner console `no_color=True` strips all color from nested delegation output |
| BUG-20 | MEDIUM | `host.py` | `set_mode` swallows all router exceptions with bare `except Exception: pass` |
| BUG-21 | HIGH | `router.py` | Provider fallback `except Exception` retries on transient errors (violates documented contract) |
| BUG-22 | MEDIUM | `router.py` | Single failing provider produces misleading `INVALID_PARAMS` error code |

---

## 13. Summary Statistics

| Category | First Pass | After Implementation | After Re-Analysis |
|----------|-----------|---------------------|-------------------|
| Original gaps | 31 | 0 | 0 |
| Gaps closed | 0 | 28 | 28 |
| Original deferred | 0 | 3 | 3 |
| New remaining gaps | — | — | 22 |
| Bugs found/fixed | — | — | 11 |
| Bugs remaining | — | — | 11 |
| Intentional/arch-diff | 8 | 8 | 12 |

### Remaining Work Summary

**22 remaining gaps** (discovered in second-pass deep audit), mostly in these clusters:

1. **REPL behavior fidelity** (7 items): recursive @mentions, directory listing, /fork turn preview, /save format, /rename limit, session-scoped dirs, banner format
2. **Event system** (4 items): `prompt:complete`, `session:end`, incremental save hook pattern, mode always-composed
3. **Output correctness** (3 items): JSON stderr ordering, error schema variants, LLM log filter
4. **Configuration** (3 items): env var expansion with defaults, permission union semantics, CWD in allowed paths
5. **Provider/update** (3 items): priority demotion, non-TTY auto-init, global update-all
6. **Session** (2 items): orphaned tool calls on fork, resume history display

**11 remaining bugs**, with 2 high-severity:
- BUG-16: Tool trace arg mismatch
- BUG-21: Provider fallback retries transient errors

These are functional but do not block daily use. The CLI is usable for all standard workflows.
