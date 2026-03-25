# At-Mention Resolution Design

## Goal

Close 5 critical feature gaps in the IPC host's at-mention resolution pipeline to reach parity with the old Amplifier system.

## Background

The Amplifier IPC system has `resolve_mention()` and `assemble_system_prompt(mentions=[...])` implemented in `host/content.py`, but they are not wired up. The old system uses bundles with a full at-mention resolution pipeline (`@namespace:path` -> parse -> resolve -> load -> format -> inject). The new IPC system has 5 critical gaps that prevent feature parity:

1. **Dead code** — `assemble_system_prompt` is called without `mentions=` argument (`host.py:404`), so explicit mention resolution never runs
2. **Dead text** — No recursive `@mention` scanning in loaded content — 193 `@namespace:path` references across services are inert text
3. **No agent loading** — Agent markdown files (`agents/*.md`) are never loaded into the system prompt since they don't use the `context/` prefix
4. **No working directory content** — No `.amplifier/AGENTS.md` or working directory file scanning
5. **No tool-level resolution** — Filesystem service has no `@namespace:path` handling in tool inputs

## Approach

Introduce a new `host/mentions.py` module containing a composable resolver chain. This mirrors the old system's two-layer architecture (foundation `BaseMentionResolver` + CLI `AppMentionResolver`) but replaces the wrapper pattern with a chain-of-responsibility design. The host owns the chain and pre-processes all `@mention` references before they reach services — services never do resolution themselves.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│ Host Process                                            │
│                                                         │
│  MentionResolverChain                                   │
│  ┌─────────────────┐  ┌──────────────────┐              │
│  │WorkingDirResolver│→│NamespaceResolver  │→ None        │
│  │ (CLI prepends)   │  │ (default)        │              │
│  └─────────────────┘  └──────────────────┘              │
│         │                      │                        │
│         ▼                      ▼                        │
│   Local filesystem      content.read RPC                │
│   (~/.amplifier/,       (ServiceIndex lookup            │
│    .amplifier/,          → service → RPC)               │
│    @~/path)                                             │
│                                                         │
│  Integration points:                                    │
│  1. System prompt assembly (recursive, depth 3)         │
│  2. Agent spawn (recursive, depth 3)                    │
│  3. Working directory content (recursive, depth 3)      │
│  4. Tool input pre-processing (single-level)            │
└─────────────────────────────────────────────────────────┘
```

## Components

### `MentionResolver` Protocol

An async callable: `async (mention: str) -> str | None`. Returns resolved content or `None` to pass to the next resolver. This is the extension point — any async callable matching this signature can be a resolver.

### `NamespaceResolver`

The default resolver. Takes a `ServiceIndex` reference and a `services` dict. Handles `@namespace:path` by looking up the namespace in `get_content_services()` and calling `content.read` RPC. Extracted from the existing `resolve_mention()` in `content.py`.

### `WorkingDirResolver`

Handles local-path mentions:
- `@~/path` — Resolves relative to the user's home directory
- `@user:path` — Resolves to `~/.amplifier/{path}`
- `@project:path` — Resolves to `.amplifier/{path}` relative to the working directory

Direct filesystem reads, no RPC needed.

### `MentionResolverChain`

Holds an ordered list of `MentionResolver` instances. Tries each in order; first non-`None` result wins. Exposes `prepend()` and `append()` for registration.

The host constructs it with `NamespaceResolver` as the default. Embedders (like the CLI) customize via `prepend()` before calling `host.run()`.

### `parse_mentions(text) -> list[str]`

Regex extraction of `@namespace:path` tokens from text. Excludes matches inside code blocks, fenced blocks, and quoted strings — matching the old system's exclusion logic.

### `resolve_and_load(text, chain, max_depth=3) -> list[ResolvedContent]`

The recursive loader:
1. Parses mentions from text via `parse_mentions()`
2. Resolves each through the chain
3. Recursively scans resolved content for nested mentions up to `max_depth`
4. SHA-256 deduplication prevents loading the same content twice
5. Returns resolved content blocks ready for formatting

## Data Flow

```
Host.__init__()
  └─ Create MentionResolverChain with NamespaceResolver (default)

CLI (before host.run())
  └─ host.mention_resolver.prepend(WorkingDirResolver(cwd))

host.run(prompt)
  │
  ├─ 1. Spawn services, call describe, populate ServiceIndex
  │     (NamespaceResolver can now resolve @namespace:path)
  │
  ├─ 2. Assemble system prompt
  │     ├─ Collect all context/ files from services via content.read RPC
  │     ├─ For each collected file:
  │     │   └─ resolve_and_load(content, chain, depth=3)
  │     │       ├─ parse_mentions(content) → ["@foundation:context/foo.md", ...]
  │     │       ├─ chain.resolve(each mention) → content string
  │     │       ├─ Deduplicate by SHA-256
  │     │       └─ Recurse into resolved content (depth - 1)
  │     └─ Format as <context_file> blocks
  │
  ├─ 3. Load working directory content
  │     ├─ Scan for AGENTS.md, .amplifier/AGENTS.md, .amplifier/*.md
  │     ├─ Read from local filesystem
  │     ├─ resolve_and_load(content, chain, depth=3)
  │     └─ Append to system prompt
  │
  ├─ 4. Enter orchestrator loop
  │     │
  │     └─ On tool call:
  │         ├─ Scan string arguments for @namespace:path
  │         ├─ chain.resolve(each mention) → resolved path or content
  │         └─ Forward resolved arguments to service
  │
  └─ 5. On agent spawn:
        ├─ Read AgentDefinition.base via content.read RPC
        ├─ resolve_and_load(content, chain, depth=3)
        └─ Build child session system prompt with resolved agent instructions
```

**Key ordering constraint:** Service spawning (step 1) must complete before any resolution (steps 2-5), because `NamespaceResolver` needs `ServiceIndex` populated. `WorkingDirResolver` has no such constraint.

## Changes to Existing Code

### `host/content.py`

Simplified. The existing `resolve_mention()` function gets extracted into `NamespaceResolver` in the new `mentions.py`. `assemble_system_prompt()` changes to accept a `MentionResolverChain` parameter instead of having its own inline resolution. New signature:

```python
async def assemble_system_prompt(
    registry, services, *, resolver_chain: MentionResolverChain
) -> str
```

### `host/host.py`

Four changes:

1. `__init__` creates a `MentionResolverChain` with `NamespaceResolver` as default, stored as `self.mention_resolver`
2. The `assemble_system_prompt` call passes `resolver_chain=self.mention_resolver`
3. After system prompt assembly, working directory content is scanned and appended (new code block)
4. Tool dispatch path gets a pre-processing step that resolves `@namespace:path` in string arguments before forwarding to services

### `host/definitions.py`

`AgentDefinition` gets a `base: str | None = None` field. This is the `namespace:path` string pointing to the agent's markdown file (e.g., `foundation:agents/explorer.md`). No `@` prefix since it is structured data, not inline text.

### `host/service_index.py`

No changes. Already has everything needed via `get_content_services()`.

### CLI (`amplifier-ipc-cli`)

Before calling `host.run()`, the CLI prepends `WorkingDirResolver(cwd)` to `host.mention_resolver`. This is the only CLI-side change.

## Error Handling

### Resolution Failures

When a `@namespace:path` mention can't be resolved (unknown namespace, file not found, RPC error):
- Log a warning with the unresolved mention string
- Skip it and continue processing remaining mentions
- Do not crash or abort system prompt assembly

A missing context file should not prevent a session from starting. The content simply won't be present.

### Circular References

The recursive loader has two layers of protection:
- **SHA-256 dedup** — If `@a:foo.md` references `@b:bar.md` which references `@a:foo.md`, the second encounter of `foo.md` is recognized by hash and skipped
- **Depth limit** — `max_depth=3` is an additional safeguard against unbounded recursion

### RPC Timeouts

`content.read` calls to services could hang if a service is unhealthy. The resolver uses the existing RPC timeout behavior — if a read times out, treat it as a resolution failure (log and skip).

### Tool Input Resolution Failures

If an `@namespace:path` in a tool argument can't be resolved, the system still attempts the tool call with the unresolved `@` string intact. The tool may produce a meaningful error on its own. A warning is logged but the tool call is not blocked.

## Testing Strategy

- **Unit tests for `parse_mentions()`** — Verify regex extraction, code block exclusion, fenced block exclusion, quoted string exclusion
- **Unit tests for `resolve_and_load()`** — Test recursive resolution, depth limiting, SHA-256 dedup, cycle handling
- **Unit tests for each resolver** — `NamespaceResolver` with mocked RPC, `WorkingDirResolver` with temp directories
- **Integration tests for `MentionResolverChain`** — Verify ordering, first-wins semantics, `prepend()`/`append()` behavior
- **Integration tests for host wiring** — Verify all 4 integration points resolve mentions correctly end-to-end

## Extensibility

The `MentionResolverChain` is the extension seam. The host creates it with `NamespaceResolver` as default. Embedders customize via `prepend()`/`append()` before calling `host.run()`:

```python
host = Host(config, ...)
host.mention_resolver.prepend(WorkingDirResolver(cwd))
host.mention_resolver.prepend(UserPathResolver("~/.amplifier"))
await host.run(prompt)
```

The chain lives entirely in the host process and crosses no process boundaries. Services never do `@mention` resolution — the host pre-processes everything before it reaches services.

## Relationship to Old System

The old system's at-mention resolution lives in two layers:
- **Foundation** (`amplifier_foundation/mentions/`): `BaseMentionResolver`, `parse_mentions()`, `load_mentions()`, `ContentDeduplicator` — clean, generic mechanism
- **CLI app** (`amplifier_app_cli/lib/mention_loading/`): `AppMentionResolver` wrapping foundation resolver with `@user:`, `@project:`, `@~/` shortcuts

The new design mirrors this split:
- `NamespaceResolver` = foundation equivalent
- `WorkingDirResolver` = CLI-shortcut equivalent
- `MentionResolverChain` = composable replacement for the wrapper pattern

## Open Questions

None — all sections validated during design review.
