# Amplifier Start: Revised Opinions

> Revision of the original OPINIONS.md from amplifier-distro. This document
> captures what changed, what was clarified, and why — based on mapping
> each opinion to what the Amplifier ecosystem actually provides.
>
> Original: `planning/OPINIONS.md`

---

## The One Rule

**Minimize human attentional load.**

*Unchanged. This remains the governing principle.*

---

## 1. Project Identity

> **Original title**: "Workspace"
> **Changed**: Significantly reworked

### The Original Opinion

All projects live under a single root directory (`~/dev/`). A
`workspace_root` setting in `distro.yaml` tells every tool where to
find projects.

### What Was Wrong

The original conflated four distinct concepts:

| Concept | What It Is | How It's Solved |
|---------|-----------|----------------|
| **Project identity** | "Which project am I in?" | Derived from `Path(cwd).name` — already works, no config needed |
| **Project state** | "Where does Amplifier store data for this project?" | `~/.amplifier/projects/<slug>/` — already works, no config needed |
| **Code location** | "Where are my git repos on disk?" | User's choice — not Amplifier's concern |
| **Project enumeration** | "List all projects" | Scan `~/.amplifier/projects/` for projects with sessions |

`workspace_root` was trying to solve code location and project
enumeration. But project identity and project state already work
without it, and nothing in the current scope needs to enumerate
code directories.

### The Revised Opinion

Project identity is automatic. Amplifier derives the project slug
from the working directory name. All per-project state is stored
under `~/.amplifier/projects/<slug>/`.

We recommend organizing code repos under a single root (e.g.
`~/dev/`) as a personal convention, but Amplifier does not require
or configure this. If a future feature (multi-interface project
discovery, "list all my projects including ones without sessions")
genuinely needs to know where code lives, it should be added then
with a clear name like `code_root`.

### What This Means For Code

- No `workspace_root` in `settings.yaml`
- No workspace detection in `amplifier init`
- Project slug derivation unchanged (`Path(cwd).name`)

---

## 2. Identity

> **Changed**: Minor — config file references updated

### The Revised Opinion

Your GitHub handle is your identity. One handle, everywhere.
Detected automatically from `gh auth status` during `amplifier init`.

### What Changed

- Config lives in `~/.amplifier/settings.yaml` (not `distro.yaml`)
- Detected during `amplifier init` (not `amp distro init`)
- `identity.github_handle` saved to settings.yaml

### What This Means For Code

- `amplifier init` detects GitHub identity (implemented)
- Written to `settings.yaml` under `identity.github_handle`

---

## 3. Memory

> **Changed**: Acknowledged as aspirational

### The Original Opinion

One memory system, one location (`~/.amplifier/memory/`), YAML
format. Every tool reads and writes the same store.

### What's Actually True

**No memory system exists in Amplifier today.** There is no
`~/.amplifier/memory/` directory, no memory store, no read/write
API. The opinion is sound — a shared, filesystem-based memory store
in YAML is the right approach — but it's entirely unbuilt.

### The Revised Opinion

The opinion stands as a design target. When built, memory should be:

- One location: `~/.amplifier/memory/`
- YAML format (human-readable, grep-able, git-trackable)
- Shared across all interfaces and sessions
- No daemon, no database, no migration

**Status**: Not implemented. Not in scope for initial amplifier-start
bundle. The convention is documented so that if memory is built, all
implementations converge on the same location and format.

---

## 4. Sessions and Handoffs

> **Changed**: Significantly reworked — handoff storage model corrected

### The Original Opinion

Sessions are files at `~/.amplifier/projects/<slug>/<session-id>/`.
A `handoff.md` is auto-generated at session end and injected at
session start.

### What Was Wrong

The original showed `handoff.md` at the project level (one per
project). This is incorrect because:

1. **Parallel sessions**: Two sessions in the same project would
   clobber each other's handoff
2. **History loss**: Only the latest session's handoff survives.
   "What happened in my last 3 sessions?" is impossible.
3. **Selective resume**: Can't pick up from session A if session B
   wrote last

Also, the actual Amplifier session directory structure uses a
`sessions/` subdirectory and `metadata.json` (not `session-info.json`).

### The Revised Opinion

Sessions are files. Handoffs are per-session, stored alongside
session data:

```
~/.amplifier/projects/
  <project-slug>/
    sessions/
      <session-id>/
        transcript.jsonl
        events.jsonl
        metadata.json
        handoff.md          # This session's handoff summary
```

**Handoff lifecycle**:
- **Write**: At session end, a hook generates `handoff.md` inside
  that session's directory
- **Read**: At session start, find the most recent session's
  `handoff.md` (by timestamp) and inject as system context
- **History**: All handoffs survive. Agents can survey multiple
  sessions' handoffs for morning briefs, friction reports, etc.

### What This Means For Code

- `hooks-handoff` writes to `projects/<slug>/sessions/<session-id>/handoff.md`
  (not `projects/<slug>/handoff.md`)
- `handoff.py` reader scans `projects/<slug>/sessions/*/handoff.md`
  and picks the most recent
- `DIRECTORY_CONTRACT.md` shows `handoff.md` at session level
- `start-conventions.md` updated to match

---

## 5. Bundle Configuration

> **Changed**: Minor — config file and command references updated

### The Revised Opinion

One bundle per user. Validated before every session. Errors are
loud, not silent.

### What Changed

- Config in `~/.amplifier/settings.yaml` (not `distro.yaml`)
- Setup via `amplifier init` (not `amp distro init`)
- Strict bundle validation already exists in amplifier-foundation
  (`BundleValidator(strict=True)`, `BundleRegistry(strict=True)`)
- Pre-flight checks implemented as `hooks-preflight` module

### What Already Exists

Foundation already has: `BundleValidator`, strict mode, completeness
checks, validation recipes. The start bundle adds pre-flight as a
hook that runs automatically, rather than requiring manual validation.

---

## 6. Interfaces

> **Changed**: Aspirational content acknowledged, Interface Adapter removed

### The Original Opinion

Interfaces are viewports into the same system. They share state,
sessions, memory, and configuration via an "Interface Adapter".

### What's Actually True

The principle is correct — interfaces should share state. But:

- **No Interface Adapter exists.** This was a distro abstraction
  that was never built.
- **Interfaces already share state** through the filesystem
  conventions: same session paths, same settings.yaml, same
  `AMPLIFIER_HOME`. No adapter needed.
- **Multi-interface is not in scope** for amplifier-start. CLI is
  the reference implementation. TUI, voice, etc. are separate
  concerns.

### The Revised Opinion

Interfaces are viewports into the same system. They interoperate by
conforming to the directory contract (`DIRECTORY_CONTRACT.md`):

- Same `AMPLIFIER_HOME` (`~/.amplifier/`)
- Same session storage paths
- Same settings.yaml for configuration
- Same event lifecycle (SESSION_START, SESSION_END)

No "Interface Adapter" abstraction needed. The filesystem IS the
shared state.

---

## 7. Providers

> **Changed**: Minimal — already how Amplifier works

### The Revised Opinion

API keys in environment variables. Provider config in your bundle.
Pre-flight verifies keys are set and non-empty.

*This opinion maps directly to how Amplifier already works. No
changes needed beyond framing.*

---

## 8. Updates and Cache

> **Changed**: Config references updated, TTL added to foundation

### The Revised Opinion

Git-based updates. TTL-based cache. Auto-refresh on error. You
never manually clear cache.

### What Changed

- Config in `settings.yaml` (not `distro.yaml`)
- TTL support added to `amplifier-foundation` `DiskCache`
  (`ttl_seconds` parameter, `is_stale()`, `refresh()`)
- The cache subsystem now writes `.meta.json` metadata for TTL tracking

### What Already Existed

Foundation already had: `DiskCache`, `SimpleCache`, reactive stale
cache clearing on load failure. What was added: proactive TTL
checking and metadata tracking.

---

## 9. Health and Diagnostics

> **Changed**: Command references updated, implemented as CLI + hook

### The Revised Opinion

The system monitors itself. Problems are surfaced before they waste
human attention.

### What Changed

- `amp distro status` → `amplifier doctor` (9 diagnostic checks, `--fix`, `--json-output`)
- Pre-flight implemented as `hooks-preflight` hook module
- `session:preflight` event added to CLI for hook point
- Health-checker agent provides in-session diagnostics

### What Exists Now

| Capability | Implementation |
|-----------|---------------|
| On-demand diagnostics | `amplifier doctor` CLI command |
| Automatic pre-flight | `hooks-preflight` hook on `session:start` |
| In-session health checks | `start:health-checker` agent |
| Friction detection | `start:friction-detector` agent + recipe |

---

## 10. Setup

> **Changed**: Descoped from website to documentation

### The Original Opinion

A static page at `amplifier.dev/distro/setup` that any agent can
read. Machine-parseable setup instructions.

### What's Actually True

No website exists. The principle is sound (machine-readable setup
instructions that an agent can follow), but the execution should
be simpler.

### The Revised Opinion

Setup instructions live in the bundle repo as documentation that
agents can read. The README and any setup guide should be structured
so an agent can extract steps programmatically (fenced code blocks,
labeled prerequisites, success criteria).

A dedicated website is future work — and may not be needed if the
repo documentation is good enough for both humans and agents.

---

## 11. Credentials

> **Changed**: Significantly simplified

### The Original Opinion

Two files: `keys.yaml` for all secrets, `distro.yaml` for all
config. Per-integration setup pages on the distro server.

### What Was Wrong

- `keys.yaml` is a second secret store alongside environment
  variables. Amplifier already uses env vars for provider keys.
  Adding a parallel system creates confusion about which is
  authoritative.
- `distro.yaml` was a distro-specific config file. We use
  `settings.yaml`.
- Per-integration setup pages required the FastAPI server we're
  not building.

### The Revised Opinion

All secrets in environment variables. All configuration in
`~/.amplifier/settings.yaml`. One pattern for everything.

- Provider keys: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, etc.
- Integration keys: `SLACK_BOT_TOKEN`, etc. (same pattern)
- Integration config: in `settings.yaml` alongside everything else
- No `keys.yaml`. No separate secret store. Env vars are the
  standard.

---

## Summary of Changes

| Opinion | Original Title | Revised Title | Change Level |
|---------|---------------|---------------|-------------|
| 1 | Workspace | Project Identity | **Major** — removed workspace_root, reframed around existing cwd-based identity |
| 2 | Identity | Identity | Minor — config file refs |
| 3 | Memory | Memory | Acknowledged as unbuilt |
| 4 | Sessions | Sessions and Handoffs | **Major** — handoffs per-session not per-project, corrected directory structure |
| 5 | Bundle Configuration | Bundle Configuration | Minor — config file and command refs |
| 6 | Interfaces | Interfaces | Moderate — removed Interface Adapter, clarified filesystem as shared state |
| 7 | Providers | Providers | Minimal |
| 8 | Updates and Cache | Updates and Cache | Minor — implemented TTL in foundation |
| 9 | Health and Diagnostics | Health and Diagnostics | Minor — implemented as doctor + hooks |
| 10 | The Setup Website | Setup | Moderate — descoped from website to repo docs |
| 11 | Integration Credentials | Credentials | **Major** — eliminated keys.yaml, env vars for everything |

## Cross-Cutting Changes

| Original | Revised | Why |
|----------|---------|-----|
| `distro.yaml` | `settings.yaml` | One config file, ecosystem-native |
| `keys.yaml` | Environment variables | No second secret store |
| `amp distro <cmd>` | `amplifier <cmd>` | Standard CLI commands |
| "distro" framing | "start" or just "Amplifier" | Bundle, not a distribution |
| Interface Adapter | Filesystem conventions | The directory contract IS the shared state |
| One handoff per project | One handoff per session | Parallel sessions, history preservation |

## What Needs Updating In Code

Based on this revision, the following code changes are needed:

1. **hooks-handoff**: Write `handoff.md` to session directory, not project directory
2. **handoff.py**: Scan session directories for most recent handoff
3. **DIRECTORY_CONTRACT.md**: Move handoff.md to session level
4. **start-conventions.md**: Reflect revised opinions 1 and 4
5. **session-handoff agent**: Update paths to session-level handoffs
