# Task 9: Sub-Session Spawn Orchestration — Implementation Plan

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

> **QUALITY WARNING:** This plan was generated after the automated quality review
> loop exhausted 3 iterations without full approval. The final review verdict was
> "NEEDS CHANGES" on one important issue (silent behavioral inversion when
> `context_depth="recent"` and `context_turns=None`). That fix is **included in
> this plan as Task 3**. Human reviewer: please verify Task 3's guard and test
> during the approval gate.

**Goal:** Add `SpawnRequest` dataclass and `spawn_child_session` orchestration function to `spawner.py`, with 6 new tests covering context formatting edge cases, spawn orchestration, and input validation.

**Architecture:** `SpawnRequest` is a plain dataclass that captures all parameters the `delegate` tool passes when spawning a child session. `spawn_child_session` is a 7-step orchestration function that composes the existing pure helpers (`check_self_delegation_depth`, `generate_child_session_id`, `filter_tools`, `filter_hooks`, `format_parent_context`) and delegates to a `_run_child_session` placeholder (Phase 2). All code is pure — no I/O, no async.

**Tech Stack:** Python 3.11+, dataclasses, pytest, unittest.mock.patch

**Project Root:** `/data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-host/`

**Dependency:** Task 8 (spawner config) must be complete. The file `src/amplifier_ipc_host/spawner.py` must already contain: `generate_child_session_id`, `merge_configs`, `filter_tools`, `filter_hooks`, `check_self_delegation_depth`, `format_parent_context`, and the constants `_DEFAULT_EXCLUDE_TOOLS`, `_CONVERSATION_ROLES`.

**Test command (run from project root):**
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-host && python -m pytest tests/test_spawner.py -v
```

---

## Pre-existing Test Count

Task 8 left 12 passing tests in `tests/test_spawner.py`:

| Group | Count | Tests |
|-------|-------|-------|
| `generate_child_session_id` | 2 | format, unique |
| `merge_configs` | 2 | scalar_override, list_by_name |
| `filter_tools` | 3 | default_excludes_delegate, blocklist, allowlist |
| `filter_hooks` | 1 | no_default_excludes |
| `check_self_delegation_depth` | 3 | raises_at_limit, raises_beyond_limit, allows_below_limit |
| `format_parent_context` | 1 | depth_and_scope (omnibus) |

This plan adds **6 new tests** → **18 total** when complete.

---

## Final State

After all tasks, `spawner.py` will contain (in order):
1. `generate_child_session_id` (Task 8 — exists)
2. `merge_configs` + helpers (Task 8 — exists)
3. `filter_tools` (Task 8 — exists)
4. `filter_hooks` (Task 8 — exists)
5. `check_self_delegation_depth` (Task 8 — exists)
6. `format_parent_context` (Task 8 — exists)
7. **`SpawnRequest` dataclass** (Task 9 — new)
8. **`_run_child_session` placeholder** (Task 9 — new)
9. **`spawn_child_session` orchestrator** (Task 9 — new)

---

### Task 1: Add 3 focused `format_parent_context` tests

**Files:**
- Modify: `amplifier-ipc/amplifier-ipc-host/tests/test_spawner.py`

These three tests exercise `format_parent_context` at its boundary conditions — they complement the existing omnibus test (`test_format_parent_context_depth_and_scope`) with single-concern coverage for each `context_depth` mode.

**Step 1: Write the three failing tests**

Append these tests after the existing `test_format_parent_context_depth_and_scope` test (after line 218), inside a new section header:

```python
# ---------------------------------------------------------------------------
# format_parent_context — additional focused tests (3)
# ---------------------------------------------------------------------------


def test_format_parent_context_none_returns_empty() -> None:
    """depth='none' always returns empty string regardless of transcript content."""
    transcript = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there"},
    ]
    result = format_parent_context(transcript, "none", "conversation", 10)
    assert result == ""


def test_format_parent_context_recent_limits_turns() -> None:
    """depth='recent' returns only the last context_turns messages after scope filter."""
    transcript = [
        {"role": "user", "content": "msg1"},
        {"role": "assistant", "content": "msg2"},
        {"role": "user", "content": "msg3"},
        {"role": "assistant", "content": "msg4"},
        {"role": "user", "content": "msg5"},
    ]
    result = format_parent_context(transcript, "recent", "conversation", 2)
    assert "msg5" in result
    assert "msg4" in result
    assert "msg3" not in result
    assert "msg1" not in result


def test_format_parent_context_all_includes_everything() -> None:
    """depth='all' includes all messages that pass the scope filter."""
    transcript = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "second"},
        {"role": "tool_result", "content": "third"},
    ]
    # scope=conversation filters out tool_result; depth=all keeps all that remain
    result = format_parent_context(transcript, "all", "conversation", 0)
    assert "first" in result
    assert "second" in result
    assert "third" not in result
```

**Step 2: Run tests to verify they pass**

These tests exercise existing code — they should pass immediately since `format_parent_context` already exists from Task 8.

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-host && python -m pytest tests/test_spawner.py::test_format_parent_context_none_returns_empty tests/test_spawner.py::test_format_parent_context_recent_limits_turns tests/test_spawner.py::test_format_parent_context_all_includes_everything -v
```
Expected: 3 PASSED

**Step 3: Commit**
```
test: add 3 focused format_parent_context tests

Cover each context_depth mode ('none', 'recent', 'all') with a
single-concern test. Complements the existing omnibus test.
```

---

### Task 2: Add `SpawnRequest` dataclass and `_run_child_session` placeholder

**Files:**
- Modify: `amplifier-ipc/amplifier-ipc-host/src/amplifier_ipc_host/spawner.py`

**Step 1: Write the failing test**

There is no separate test for `SpawnRequest` construction — it is exercised through `spawn_child_session` tests in Tasks 4–5. However, we verify it is importable. The import line in `test_spawner.py` already imports `SpawnRequest` (line 11). Adding `SpawnRequest` to the implementation will make the import valid.

Verify the existing import block in `test_spawner.py` already includes `SpawnRequest`:

```python
from amplifier_ipc_host.spawner import (
    SpawnRequest,             # <-- already here from Task 8's import block
    check_self_delegation_depth,
    filter_hooks,
    filter_tools,
    format_parent_context,
    generate_child_session_id,
    merge_configs,
    spawn_child_session,
)
```

If `SpawnRequest` and `spawn_child_session` are not yet in the import block, add them now.

**Step 2: Add `SpawnRequest` dataclass to `spawner.py`**

Append after the `format_parent_context` function (after line 253 in the current file), before the end of the module:

```python
# ---------------------------------------------------------------------------
# SpawnRequest dataclass
# ---------------------------------------------------------------------------


@dataclass
class SpawnRequest:
    """Parameters for spawning a child session.

    Attributes:
        agent:                Agent identifier to spawn (``'self'`` clones the
                              parent config; any other value is a named agent).
        instruction:          The instruction to pass to the child session.
        context_depth:        How much parent context to include: ``'none'``,
                              ``'recent'``, or ``'all'``.
        context_scope:        Which messages to include: ``'conversation'``
                              keeps only user/assistant turns; any other value
                              keeps all messages.
        context_turns:        Number of recent turns to include when
                              *context_depth* is ``'recent'``.
        exclude_tools:        Tool names to remove from the child config
                              (blocklist mode).
        inherit_tools:        Tool names to keep in the child config
                              (allowlist mode).
        exclude_hooks:        Hook names to remove from the child config.
        inherit_hooks:        Hook names to keep in the child config.
        agents:               Agent bundle(s) to make available in the child
                              session.
        provider_preferences: Ordered provider/model preference list.
        model_role:           Override the child agent's default model role.
    """

    agent: str
    instruction: str
    context_depth: str = "none"
    context_scope: str = "conversation"
    context_turns: int | None = None
    exclude_tools: list[str] | None = None
    inherit_tools: list[str] | None = None
    exclude_hooks: list[str] | None = None
    inherit_hooks: list[str] | None = None
    agents: str | list[str] | None = None
    provider_preferences: list[dict[str, Any]] | None = None
    model_role: str | None = None
```

**Step 3: Add `_run_child_session` placeholder**

Append immediately after `SpawnRequest`:

```python
# ---------------------------------------------------------------------------
# Child session execution (Phase 2 placeholder)
# ---------------------------------------------------------------------------


def _run_child_session(
    child_session_id: str,
    child_config: dict[str, Any],
    instruction: str,
    request: SpawnRequest,
) -> Any:
    """Execute a child session.

    .. note::
        This is a placeholder.  Full implementation is deferred to Phase 2.

    Raises:
        NotImplementedError: Always.
    """
    raise NotImplementedError("Full implementation deferred to Phase 2")
```

**Step 4: Verify existing tests still pass**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-host && python -m pytest tests/test_spawner.py -v
```
Expected: 15 PASSED (12 Task 8 + 3 Task 1)

**Step 5: Commit**
```
feat: add SpawnRequest dataclass and _run_child_session placeholder

SpawnRequest captures all delegate tool parameters as a plain dataclass.
_run_child_session is a NotImplementedError placeholder for Phase 2.
```

---

### Task 3: Add `spawn_child_session` orchestration function

**Files:**
- Modify: `amplifier-ipc/amplifier-ipc-host/src/amplifier_ipc_host/spawner.py`

**Step 1: Write the two failing tests**

Append to `test_spawner.py` after the last `format_parent_context` test:

```python
# ---------------------------------------------------------------------------
# spawn_child_session (2 tests)
# ---------------------------------------------------------------------------


def test_spawn_child_session_depth_limit_exceeded() -> None:
    """Raises ValueError when current_depth >= 3 (default max_depth)."""
    request = SpawnRequest(agent="self", instruction="Do something")
    with pytest.raises(ValueError):
        spawn_child_session(
            parent_session_id="parent-123",
            parent_config={"tools": []},
            transcript=[],
            request=request,
            current_depth=3,
        )


def test_spawn_child_session_self_delegation() -> None:
    """Self-delegation clones parent config, excludes delegate tool, calls _run_child_session."""
    parent_config = {
        "tools": [
            {"name": "bash"},
            {"name": "delegate"},
            {"name": "grep"},
        ],
        "hooks": [{"name": "pre-request"}],
    }
    request = SpawnRequest(agent="self", instruction="Do something")

    with patch("amplifier_ipc_host.spawner._run_child_session") as mock_run:
        mock_run.return_value = "result"
        spawn_child_session(
            parent_session_id="parent-123",
            parent_config=parent_config,
            transcript=[],
            request=request,
            current_depth=0,
        )

    assert mock_run.called
    # Extract child_config — second positional argument to _run_child_session
    positional_args = mock_run.call_args[0]
    child_config = positional_args[1]
    tool_names = [t["name"] for t in child_config.get("tools", [])]
    assert "delegate" not in tool_names
    assert "bash" in tool_names
    assert "grep" in tool_names
```

**Step 2: Run tests to verify they fail**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-host && python -m pytest tests/test_spawner.py::test_spawn_child_session_depth_limit_exceeded tests/test_spawner.py::test_spawn_child_session_self_delegation -v
```
Expected: FAIL — `spawn_child_session` is not yet defined (import error or `AttributeError`).

**Step 3: Implement `spawn_child_session`**

Append to `spawner.py` after `_run_child_session`:

```python
# ---------------------------------------------------------------------------
# spawn_child_session — orchestration entry point
# ---------------------------------------------------------------------------


def spawn_child_session(
    parent_session_id: str,
    parent_config: dict[str, Any],
    transcript: list[dict[str, Any]],
    request: SpawnRequest,
    current_depth: int = 0,
) -> Any:
    """Orchestrate spawning of a child session.

    Steps:
    1. Check self-delegation depth (raises :class:`ValueError` at the limit).
    2. Generate a unique child session ID.
    3. Build the child config: clone parent for ``agent='self'``, else a
       placeholder dict.
    4. Filter tools and hooks according to *request* settings.
    5. Format the parent conversation context.
    6. Build the final instruction with an optional context prefix.
    7. Delegate to :func:`_run_child_session`.

    Args:
        parent_session_id: Session ID of the spawning (parent) session.
        parent_config:     Parent session configuration (tools, hooks, …).
        transcript:        Parent conversation transcript for context
                           extraction.
        request:           Spawn parameters.
        current_depth:     Current self-delegation nesting depth (0-based).

    Returns:
        Whatever :func:`_run_child_session` returns.

    Raises:
        ValueError: When *current_depth* has reached the recursion limit.
        ValueError: When *context_depth* is ``'recent'`` but *context_turns*
                    is ``None``.
    """
    # 1. Enforce recursion depth limit
    check_self_delegation_depth(current_depth)

    # 2. Generate child session ID
    child_session_id = generate_child_session_id(parent_session_id, request.agent)

    # 3. Build child config
    if request.agent == "self":
        child_config: dict[str, Any] = dict(parent_config)
    else:
        child_config = {"agent": request.agent}

    # 4. Filter tools and hooks
    tools: list[dict[str, Any]] = child_config.get("tools", [])
    hooks: list[dict[str, Any]] = child_config.get("hooks", [])
    child_config["tools"] = filter_tools(
        tools, request.exclude_tools, request.inherit_tools
    )
    child_config["hooks"] = filter_hooks(
        hooks, request.exclude_hooks, request.inherit_hooks
    )

    # 5. Format parent context
    if request.context_depth == "recent" and request.context_turns is None:
        raise ValueError("context_turns must be set when context_depth='recent'")
    context_turns = request.context_turns if request.context_turns is not None else 0
    context_str = format_parent_context(
        transcript,
        request.context_depth,
        request.context_scope,
        context_turns,
    )

    # 6. Build instruction with optional context prefix
    if context_str:
        instruction = f"{context_str}\n\n{request.instruction}"
    else:
        instruction = request.instruction

    # 7. Execute child session (Phase 2 implementation)
    return _run_child_session(child_session_id, child_config, instruction, request)
```

**Important — the `context_turns` guard on line 5:** When `context_depth="recent"` and `context_turns` is `None`, the function raises `ValueError` immediately. Without this guard, `context_turns` would default to `0`, and Python's `messages[-0:]` evaluates to `messages[0:]` — returning **all** messages instead of none. This is a silent behavioral inversion caught during quality review.

**Step 4: Run tests to verify they pass**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-host && python -m pytest tests/test_spawner.py -v
```
Expected: 17 PASSED (15 previous + 2 new spawn tests)

**Step 5: Commit**
```
feat: add spawn_child_session orchestration function

7-step orchestration: depth check → ID generation → config build →
tool/hook filter → context format → instruction build → delegate.
Includes guard against context_depth='recent' without context_turns.
```

---

### Task 4: Add `context_turns` validation guard test

**Files:**
- Modify: `amplifier-ipc/amplifier-ipc-host/tests/test_spawner.py`

This test exercises the guard added in Task 3, step 3 (the `ValueError` when `context_depth="recent"` but `context_turns` is `None`). This was the **important issue** flagged by the quality reviewer.

**Step 1: Write the test**

Append after `test_spawn_child_session_self_delegation`:

```python
def test_spawn_child_session_recent_depth_requires_context_turns() -> None:
    """Raises ValueError when context_depth='recent' but context_turns is not set."""
    request = SpawnRequest(
        agent="self",
        instruction="Do something",
        context_depth="recent",
        context_turns=None,  # not set — should be caught
    )
    with pytest.raises(ValueError, match="context_turns"):
        spawn_child_session(
            parent_session_id="parent-123",
            parent_config={"tools": []},
            transcript=[{"role": "user", "content": "hi"}],
            request=request,
            current_depth=0,
        )
```

**Step 2: Run test to verify it passes**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-host && python -m pytest tests/test_spawner.py::test_spawn_child_session_recent_depth_requires_context_turns -v
```
Expected: PASS (the guard was implemented in Task 3)

**Step 3: Run full suite**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/amplifier-ipc-host && python -m pytest tests/test_spawner.py -v
```
Expected: **18 PASSED** (12 Task 8 + 3 focused context tests + 2 spawn tests + 1 guard test)

**Step 4: Commit**
```
test: add context_turns validation guard test for spawn_child_session

Exercises the ValueError raised when context_depth='recent' but
context_turns is None — prevents silent messages[-0:] inversion.
```

---

## Acceptance Criteria Checklist

| Criterion | Verified by |
|-----------|-------------|
| All spawner tests pass (18 total) | `pytest tests/test_spawner.py -v` → 18 passed |
| `SpawnRequest` is importable | `from amplifier_ipc_host.spawner import SpawnRequest` in test imports |
| `spawn_child_session` self-delegation clones parent config | `test_spawn_child_session_self_delegation` |
| `spawn_child_session` self-delegation excludes delegate tool | `test_spawn_child_session_self_delegation` asserts `"delegate" not in tool_names` |
| `spawn_child_session` calls `_run_child_session` | `test_spawn_child_session_self_delegation` asserts `mock_run.called` |
| Depth limit test: `ValueError` at depth 3 | `test_spawn_child_session_depth_limit_exceeded` |
| Context `'none'` returns empty | `test_format_parent_context_none_returns_empty` |
| Context `'recent'` limits turns | `test_format_parent_context_recent_limits_turns` |
| Context `'all'` includes everything | `test_format_parent_context_all_includes_everything` |
| `context_depth='recent'` + `context_turns=None` raises | `test_spawn_child_session_recent_depth_requires_context_turns` |

## Quality Review Notes

The automated quality review loop exhausted 3 iterations. The final review
identified one **important** issue — a silent behavioral inversion where
`context_depth="recent"` with `context_turns=None` would default to `0`,
causing `messages[-0:]` to return all messages instead of none. This plan
includes the fix (Task 3 step 3, guard before `format_parent_context`) and
a dedicated test (Task 4). The fix is straightforward but was flagged
because the review loop couldn't converge — human reviewer should verify
the guard exists and the test covers it.

**Suggestion from review (not blocking):** The magic literal `8` in
`generate_child_session_id` (`uuid4().hex[:8]`) could be extracted to a
named constant `_CHILD_SPAN_LENGTH = 8`. Low priority — defer to a future
cleanup pass.