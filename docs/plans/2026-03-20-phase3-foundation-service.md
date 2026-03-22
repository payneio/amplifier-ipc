# Phase 3: Port amplifier-foundation as IPC Service

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Port the `amplifier-foundation` package from amplifier-lite into a standalone IPC service at `amplifier-ipc/services/amplifier-foundation/`, making it discoverable and operable via the JSON-RPC 2.0 protocol defined in Phase 1.

**Architecture:** The existing Python component code (tools, hooks, context manager) is copied with minimal changes — primarily adding `@tool`, `@hook`, `@context_manager`, `@orchestrator` decorators from `amplifier_ipc_protocol` and removing `amplifier_lite` imports. The `StreamingOrchestrator` gets the biggest conversion: all direct object calls (`hooks.emit()`, `context.add_message()`, `provider.complete()`, `tools[name].execute()`) become `self.client.request("request.*", {...})` JSON-RPC calls through the host. Content files (agents, behaviors, context, recipes, sessions) are copied verbatim. The generic `Server` from Phase 1 handles discovery, describe, and dispatch automatically.

**Tech Stack:** Python 3.11+, Pydantic v2, amplifier-ipc-protocol (Phase 1), pytest + pytest-asyncio

---

## Important Context for the Implementer

### What already exists (DO NOT rebuild these)

1. **`amplifier-ipc-protocol`** at `amplifier-ipc/amplifier-ipc-protocol/` — provides:
   - `Server(package_name)` — generic JSON-RPC server that auto-discovers decorated classes via `scan_package()`, serves `describe`, `tool.execute`, `hook.emit`, `content.read`, `content.list`
   - `Client(reader, writer)` — sends JSON-RPC requests with `await client.request(method, params)` and notifications with `await client.send_notification(method, params)`
   - Decorators: `@tool`, `@hook(events=[...], priority=N)`, `@orchestrator`, `@context_manager`, `@provider`
   - Models: `ToolResult`, `HookResult`, `HookAction`, `Message`, `ChatRequest`, `ChatResponse`, `ToolSpec`, `ToolCall`, `TextBlock`, `ThinkingBlock`, `Usage`
   - Protocols: `ToolProtocol`, `HookProtocol`, `OrchestratorProtocol`, `ContextManagerProtocol`, `ProviderProtocol`
   - Discovery: `scan_package(pkg_name)` scans `tools/`, `hooks/`, `orchestrators/`, `context_managers/`, `providers/` for decorated classes. `scan_content(pkg_name)` scans `agents/`, `behaviors/`, `context/`, `recipes/`, `sessions/` for content files. **Important:** `scan_package` only scans `*.py` files directly inside each component directory — it does NOT recurse into subdirectories. Files in `tools/bash/`, `tools/filesystem/`, `hooks/approval/`, etc. will NOT be found by default.

2. **`amplifier-ipc-host`** at `amplifier-ipc/amplifier-ipc-host/` — spawns services, routes messages, fans out hooks. The host sends `orchestrator.execute` to the orchestrator service, then the orchestrator sends `request.*` messages back through the host to reach other services.

### What you're building (this plan)

A new package at `amplifier-ipc/services/amplifier-foundation/` that:
- Installs as `amplifier-foundation-serve` command
- Responds to `describe` with all its tools, hooks, orchestrator, context manager, and content
- Handles `tool.execute`, `hook.emit`, `content.read`, `content.list` via the generic Server
- Contains a converted `StreamingOrchestrator` that uses `Client` for all external communication

### Key discovery constraint

The protocol library's `scan_package()` only finds `*.py` files directly in `tools/`, `hooks/`, etc. — it does **not** recurse into subdirectories. The existing amplifier-foundation has many components in subdirectories:

- `tools/bash/__init__.py` (BashTool)
- `tools/filesystem/read.py`, `tools/filesystem/write.py`, `tools/filesystem/edit.py`
- `tools/search/grep.py`, `tools/search/glob.py`
- `hooks/approval/approval_hook.py`
- `hooks/routing/resolver.py`
- `hooks/shell/bridge.py`

**Solution:** For each subdirectory component, create a thin proxy file at the top level that imports and re-exports the decorated class. For example, `tools/bash_tool.py` imports `BashTool` from `tools/bash/` and applies `@tool`. This keeps the existing code structure intact while making components discoverable.

### Import conversion pattern

Every source file currently imports from `amplifier_lite`:
```python
from amplifier_lite.models import ToolResult, HookAction, HookResult, Message
from amplifier_lite.session import Session
from amplifier_lite.hooks import HookRegistry
```

These all become imports from `amplifier_ipc_protocol`:
```python
from amplifier_ipc_protocol import ToolResult, HookAction, HookResult, Message
```

The `Session` object and `HookRegistry` are **removed** — they don't exist in the IPC world. Tools that used `self.session` for state (like `TodoTool` using `self.session.state["todo_state"]`) need to use local instance state instead.

---

## Working Directory

All paths in this plan are relative to: `/data/labs/amplifier-lite/amplifier-ipc/services/amplifier-foundation/`

The source package to port FROM is at: `/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation/`

---

### Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `src/amplifier_foundation/__init__.py`
- Create: `src/amplifier_foundation/__main__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

**Step 1: Create pyproject.toml**

Create `pyproject.toml` with this exact content:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "amplifier-foundation"
version = "0.1.0"
description = "Amplifier Foundation IPC service — orchestrator, context manager, tools, hooks, content"
requires-python = ">=3.11"
dependencies = [
    "amplifier-ipc-protocol",
    "pydantic>=2.0",
    "pyyaml>=6.0",
    "rich>=13.0",
    "aiohttp>=3.9",
    "beautifulsoup4>=4.12",
    "duckduckgo-search>=4.0",
    "click>=8.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
]

[project.scripts]
amplifier-foundation-serve = "amplifier_foundation.__main__:main"

[tool.hatch.build.targets.wheel]
packages = ["src/amplifier_foundation"]

[tool.hatch.build.targets.wheel.shared-data]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["src"]

[tool.pyright]
pythonVersion = "3.11"
extraPaths = ["src"]

[tool.uv.sources]
amplifier-ipc-protocol = { path = "../../amplifier-ipc-protocol" }

[dependency-groups]
dev = [
    "pytest-asyncio>=1.3.0",
    "pytest-timeout>=2.4.0",
]
```

**Step 2: Create package init**

Create `src/amplifier_foundation/__init__.py`:

```python
"""Amplifier Foundation IPC service.

Provides: 1 orchestrator, 1 context manager, 12+ hooks, 14+ tools, and content files.
"""

__version__ = "0.1.0"
```

**Step 3: Create entry point**

Create `src/amplifier_foundation/__main__.py`:

```python
"""Entry point for amplifier-foundation-serve command."""

from amplifier_ipc_protocol import Server


def main() -> None:
    """Start the amplifier-foundation IPC service."""
    Server("amplifier_foundation").run()


if __name__ == "__main__":
    main()
```

**Step 4: Create test scaffolding**

Create `tests/__init__.py` (empty file):
```python
```

Create `tests/conftest.py`:
```python
from __future__ import annotations
```

**Step 5: Create directory structure**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-foundation
mkdir -p src/amplifier_foundation/orchestrators
mkdir -p src/amplifier_foundation/context_managers
mkdir -p src/amplifier_foundation/hooks/approval
mkdir -p src/amplifier_foundation/hooks/routing
mkdir -p src/amplifier_foundation/hooks/shell
mkdir -p src/amplifier_foundation/tools/bash
mkdir -p src/amplifier_foundation/tools/filesystem
mkdir -p src/amplifier_foundation/tools/search
mkdir -p src/amplifier_foundation/tools/mcp
mkdir -p src/amplifier_foundation/tools/recipes
mkdir -p src/amplifier_foundation/tools/apply_patch
mkdir -p src/amplifier_foundation/tools/bundle_python_dev
mkdir -p src/amplifier_foundation/tools/bundle_shadow
```

**Step 6: Install the package in dev mode**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-foundation
uv venv
uv pip install -e ".[dev]"
```
Expected: Install succeeds, `amplifier-foundation-serve` command is available.

**Step 7: Verify the package is importable**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-foundation
uv run python -c "import amplifier_foundation; print(amplifier_foundation.__version__)"
```
Expected: Prints `0.1.0`

**Step 8: Commit**
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-foundation
git init && git add -A && git commit -m "feat: project scaffolding for amplifier-foundation IPC service"
```

---

### Task 2: Copy Content Files

**Files:**
- Create: `src/amplifier_foundation/agents/*.md` (16 files)
- Create: `src/amplifier_foundation/behaviors/*.yaml` (12 files)
- Create: `src/amplifier_foundation/context/**/*.md` (~20 files)
- Create: `src/amplifier_foundation/recipes/*.yaml` (4 files)
- Create: `src/amplifier_foundation/sessions/*.yaml` (5 files)
- Test: `tests/test_content.py`

**Step 1: Write the failing test**

Create `tests/test_content.py`:

```python
"""Tests that content files are discoverable and readable."""

from __future__ import annotations

from amplifier_ipc_protocol.discovery import scan_content


def test_agents_content_discovered() -> None:
    """scan_content finds .md files in agents/ directory."""
    paths = scan_content("amplifier_foundation")
    agent_paths = [p for p in paths if p.startswith("agents/")]
    assert len(agent_paths) >= 10, f"Expected >=10 agent files, got {len(agent_paths)}: {agent_paths}"


def test_behaviors_content_discovered() -> None:
    """scan_content finds .yaml files in behaviors/ directory."""
    paths = scan_content("amplifier_foundation")
    behavior_paths = [p for p in paths if p.startswith("behaviors/")]
    assert len(behavior_paths) >= 5, f"Expected >=5 behavior files, got {len(behavior_paths)}"


def test_context_content_discovered() -> None:
    """scan_content finds .md files in context/ directory (including subdirectories)."""
    paths = scan_content("amplifier_foundation")
    context_paths = [p for p in paths if p.startswith("context/")]
    assert len(context_paths) >= 5, f"Expected >=5 context files, got {len(context_paths)}"


def test_recipes_content_discovered() -> None:
    """scan_content finds .yaml files in recipes/ directory."""
    paths = scan_content("amplifier_foundation")
    recipe_paths = [p for p in paths if p.startswith("recipes/")]
    assert len(recipe_paths) >= 3, f"Expected >=3 recipe files, got {len(recipe_paths)}"


def test_sessions_content_discovered() -> None:
    """scan_content finds .yaml files in sessions/ directory."""
    paths = scan_content("amplifier_foundation")
    session_paths = [p for p in paths if p.startswith("sessions/")]
    assert len(session_paths) >= 3, f"Expected >=3 session files, got {len(session_paths)}"
```

**Step 2: Run test to verify it fails**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-foundation
uv run pytest tests/test_content.py -v
```
Expected: FAIL — no content files exist yet.

**Step 3: Copy all content directories from the source package**

Run:
```bash
SRC=/data/labs/amplifier-lite/amplifier-lite/packages/amplifier-foundation/src/amplifier_foundation
DST=/data/labs/amplifier-lite/amplifier-ipc/services/amplifier-foundation/src/amplifier_foundation

cp -r "$SRC/agents" "$DST/agents"
cp -r "$SRC/behaviors" "$DST/behaviors"
cp -r "$SRC/context" "$DST/context"
cp -r "$SRC/recipes" "$DST/recipes"
cp -r "$SRC/sessions" "$DST/sessions"
```

**Step 4: Run test to verify it passes**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-foundation
uv run pytest tests/test_content.py -v
```
Expected: All 5 tests PASS.

**Step 5: Commit**
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-foundation
git add -A && git commit -m "feat: copy content files (agents, behaviors, context, recipes, sessions)"
```

---

### Task 3: Port TodoTool (Simple Tool — Pattern Establisher)

This task establishes the pattern for all tool ports. TodoTool is chosen because it's self-contained, has no external dependencies, and demonstrates the key conversion: removing `amplifier_lite` imports, removing `Session` dependency, adding `@tool` decorator, and using local instance state.

**Files:**
- Create: `src/amplifier_foundation/tools/todo.py`
- Test: `tests/test_tools_todo.py`

**Step 1: Write the failing test**

Create `tests/test_tools_todo.py`:

```python
"""Tests for TodoTool with @tool decorator and IPC-compatible interface."""

from __future__ import annotations

import pytest
from amplifier_ipc_protocol import ToolResult
from amplifier_ipc_protocol.discovery import scan_package


def test_todo_tool_discovered() -> None:
    """TodoTool is discovered by scan_package with @tool decorator."""
    components = scan_package("amplifier_foundation")
    tool_names = [getattr(t, "name", "") for t in components.get("tool", [])]
    assert "todo" in tool_names, f"'todo' not found in discovered tools: {tool_names}"


def test_todo_tool_has_required_attributes() -> None:
    """TodoTool has name, description, and input_schema attributes."""
    components = scan_package("amplifier_foundation")
    todo = None
    for t in components.get("tool", []):
        if getattr(t, "name", "") == "todo":
            todo = t
            break
    assert todo is not None, "TodoTool not found"
    assert todo.name == "todo"
    assert len(todo.description) > 20
    assert "action" in str(todo.input_schema)


@pytest.mark.asyncio
async def test_todo_tool_create() -> None:
    """TodoTool create action stores todos and returns them."""
    components = scan_package("amplifier_foundation")
    todo = next(t for t in components.get("tool", []) if getattr(t, "name", "") == "todo")

    result = await todo.execute({
        "action": "create",
        "todos": [
            {"content": "Run tests", "activeForm": "Running tests", "status": "pending"},
            {"content": "Write code", "activeForm": "Writing code", "status": "in_progress"},
        ],
    })
    assert isinstance(result, ToolResult)
    assert result.success is True
    assert result.output["count"] == 2


@pytest.mark.asyncio
async def test_todo_tool_list() -> None:
    """TodoTool list action returns current state."""
    components = scan_package("amplifier_foundation")
    todo = next(t for t in components.get("tool", []) if getattr(t, "name", "") == "todo")

    # Create first, then list
    await todo.execute({
        "action": "create",
        "todos": [{"content": "Test", "activeForm": "Testing", "status": "pending"}],
    })
    result = await todo.execute({"action": "list"})
    assert result.success is True
    assert result.output["count"] == 1
```

**Step 2: Run test to verify it fails**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-foundation
uv run pytest tests/test_tools_todo.py -v
```
Expected: FAIL — `todo.py` doesn't exist or has no `@tool` decorator.

**Step 3: Create the ported TodoTool**

Create `src/amplifier_foundation/tools/todo.py`:

```python
"""TodoTool — AI-managed todo list for self-accountability.

Ported from amplifier-lite. Changes:
- Removed amplifier_lite imports (Session, models)
- Uses amplifier_ipc_protocol imports instead
- Uses local instance state instead of session.state
- Added @tool decorator for IPC discovery
"""

from __future__ import annotations

import logging
from typing import Any

from amplifier_ipc_protocol import ToolResult, tool

logger = logging.getLogger(__name__)


@tool
class TodoTool:
    """AI-managed todo list for self-accountability through complex turns."""

    name = "todo"
    description = """Manage your todo list for tracking complex multi-step tasks.

Use this tool to:
- Create a todo list when starting complex multi-step work
- Update the list as you complete each step
- Stay accountable and focused through long turns

Todo items have:
- content: Imperative description (e.g., "Run tests", "Build project")
- activeForm: Present continuous (e.g., "Running tests", "Building project")
- status: "pending" | "in_progress" | "completed"

Recommended pattern:
1. Create list when you start complex multi-step work
2. Update after completing each step
3. Keep exactly ONE item as "in_progress" at a time
4. Mark items "completed" immediately after finishing"""

    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "update", "list"],
                "description": "Action to perform: create (replace all), update (replace all), list (read current)",
            },
            "todos": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "Imperative description: 'Run tests', 'Build project'",
                        },
                        "activeForm": {
                            "type": "string",
                            "description": "Present continuous: 'Running tests', 'Building project'",
                        },
                        "status": {
                            "type": "string",
                            "enum": ["pending", "in_progress", "completed"],
                            "description": "Current status of this todo item",
                        },
                    },
                    "required": ["content", "status", "activeForm"],
                },
                "description": "List of todos (required for create/update, ignored for list)",
            },
        },
        "required": ["action"],
    }

    def __init__(self) -> None:
        # Local instance state replaces session.state["todo_state"]
        self._todo_state: list[dict[str, Any]] = []

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """Execute todo operation."""
        action = input.get("action")

        if action == "create":
            return self._handle_create(input)

        if action == "update":
            return self._handle_update(input)

        if action == "list":
            return ToolResult(
                success=True,
                output={
                    "status": "listed",
                    "count": len(self._todo_state),
                    "todos": self._todo_state,
                },
            )

        return ToolResult(
            success=False,
            error={"message": f"Unknown action: {action}. Valid actions: create, update, list"},
        )

    def _handle_create(self, input: dict[str, Any]) -> ToolResult:
        todos = input.get("todos", [])
        error = self._validate_todos(todos)
        if error:
            return error
        self._todo_state = todos
        return ToolResult(
            success=True,
            output={"status": "created", "count": len(todos), "todos": todos},
        )

    def _handle_update(self, input: dict[str, Any]) -> ToolResult:
        todos = input.get("todos", [])
        error = self._validate_todos(todos)
        if error:
            return error
        self._todo_state = todos
        pending = sum(1 for t in todos if t["status"] == "pending")
        in_progress = sum(1 for t in todos if t["status"] == "in_progress")
        completed = sum(1 for t in todos if t["status"] == "completed")
        return ToolResult(
            success=True,
            output={
                "status": "updated",
                "count": len(todos),
                "pending": pending,
                "in_progress": in_progress,
                "completed": completed,
            },
        )

    def _validate_todos(self, todos: list[dict[str, Any]]) -> ToolResult | None:
        for i, todo in enumerate(todos):
            if not all(k in todo for k in ["content", "status", "activeForm"]):
                return ToolResult(
                    success=False,
                    error={"message": f"Todo {i} missing required fields (content, status, activeForm)"},
                )
            if todo["status"] not in ["pending", "in_progress", "completed"]:
                return ToolResult(
                    success=False,
                    error={"message": f"Todo {i} has invalid status: {todo['status']}"},
                )
        return None
```

**Step 4: Create __init__.py files for component directories**

Create empty `__init__.py` files in all component directories so Python can import them:

```bash
touch src/amplifier_foundation/tools/__init__.py
touch src/amplifier_foundation/hooks/__init__.py
touch src/amplifier_foundation/orchestrators/__init__.py
touch src/amplifier_foundation/context_managers/__init__.py
```

**Step 5: Run test to verify it passes**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-foundation
uv run pytest tests/test_tools_todo.py -v
```
Expected: All 4 tests PASS.

**Step 6: Commit**
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-foundation
git add -A && git commit -m "feat: port TodoTool with @tool decorator and local state"
```

---

### Task 4: Port Remaining Simple Tools (web, delegate, task stubs)

Port the tools that live in single files at the top level of `tools/`. For complex tools that depend heavily on `amplifier_lite.session` or `amplifier_lite.spawn_utils` (like `DelegateTool`, `TaskTool`), create **stub implementations** that are discoverable and have correct schemas but return "not yet implemented" for execution. The stubs will be filled in when the full IPC session spawning mechanism is built.

**Files:**
- Create: `src/amplifier_foundation/tools/web.py`
- Create: `src/amplifier_foundation/tools/delegate.py`
- Create: `src/amplifier_foundation/tools/task.py`
- Test: `tests/test_tools_simple.py`

**Step 1: Write the failing test**

Create `tests/test_tools_simple.py`:

```python
"""Tests for simple tools — discovery and basic execution."""

from __future__ import annotations

import pytest
from amplifier_ipc_protocol.discovery import scan_package


def test_web_search_tool_discovered() -> None:
    """WebSearchTool is discovered by scan_package."""
    components = scan_package("amplifier_foundation")
    tool_names = [getattr(t, "name", "") for t in components.get("tool", [])]
    assert "web_search" in tool_names, f"'web_search' not found: {tool_names}"


def test_web_fetch_tool_discovered() -> None:
    """WebFetchTool is discovered by scan_package."""
    components = scan_package("amplifier_foundation")
    tool_names = [getattr(t, "name", "") for t in components.get("tool", [])]
    assert "web_fetch" in tool_names, f"'web_fetch' not found: {tool_names}"


def test_delegate_tool_discovered() -> None:
    """DelegateTool stub is discovered by scan_package."""
    components = scan_package("amplifier_foundation")
    tool_names = [getattr(t, "name", "") for t in components.get("tool", [])]
    assert "delegate" in tool_names, f"'delegate' not found: {tool_names}"


def test_task_tool_discovered() -> None:
    """TaskTool stub is discovered by scan_package."""
    components = scan_package("amplifier_foundation")
    tool_names = [getattr(t, "name", "") for t in components.get("tool", [])]
    assert "task" in tool_names, f"'task' not found: {tool_names}"


@pytest.mark.asyncio
async def test_web_search_requires_query() -> None:
    """WebSearchTool returns error when query is missing."""
    components = scan_package("amplifier_foundation")
    ws = next(t for t in components.get("tool", []) if getattr(t, "name", "") == "web_search")
    result = await ws.execute({})
    assert result.success is False


@pytest.mark.asyncio
async def test_delegate_stub_returns_not_implemented() -> None:
    """DelegateTool stub returns not-implemented error."""
    components = scan_package("amplifier_foundation")
    d = next(t for t in components.get("tool", []) if getattr(t, "name", "") == "delegate")
    result = await d.execute({"agent": "test", "task": "hello"})
    assert result.success is False
    assert "not yet implemented" in str(result.error).lower() or "stub" in str(result.error).lower()
```

**Step 2: Run test to verify it fails**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-foundation
uv run pytest tests/test_tools_simple.py -v
```
Expected: FAIL

**Step 3: Port WebSearchTool and WebFetchTool**

Create `src/amplifier_foundation/tools/web.py` by copying from the source and making these changes:
- Replace `from amplifier_lite.models import ToolResult` with `from amplifier_ipc_protocol import ToolResult, tool`
- Remove `from amplifier_lite.session import Session`
- Add `@tool` decorator to both `WebSearchTool` and `WebFetchTool`
- Change `__init__` to take no args (remove `config`, `session`, `shared_session` params) — use sensible defaults
- Convert `name`, `description`, and `input_schema` from `@property` methods to class attributes where they are properties

The key changes in the `__init__`:
```python
@tool
class WebSearchTool:
    name = "web_search"
    description = "Search the web for information"
    input_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query to execute"}
        },
        "required": ["query"],
    }

    def __init__(self) -> None:
        self.max_results = 5
    # ... rest of execute method stays the same
```

Do the same for `WebFetchTool`. Keep all the actual execution logic intact.

**Step 4: Create DelegateTool stub**

Create `src/amplifier_foundation/tools/delegate.py`:

```python
"""DelegateTool stub — placeholder until IPC sub-session spawning is implemented."""

from __future__ import annotations

from typing import Any

from amplifier_ipc_protocol import ToolResult, tool


@tool
class DelegateTool:
    """Delegate tasks to specialized agents via sub-sessions (stub)."""

    name = "delegate"
    description = "Delegate tasks to specialized agents. Currently a stub in the IPC service."
    input_schema = {
        "type": "object",
        "properties": {
            "agent": {"type": "string", "description": "Agent name or path"},
            "task": {"type": "string", "description": "Task instruction"},
        },
        "required": ["task"],
    }

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        return ToolResult(
            success=False,
            error={"message": "DelegateTool stub: sub-session spawning not yet implemented in IPC service"},
        )
```

**Step 5: Create TaskTool stub**

Create `src/amplifier_foundation/tools/task.py`:

```python
"""TaskTool stub — placeholder until IPC sub-session spawning is implemented."""

from __future__ import annotations

from typing import Any

from amplifier_ipc_protocol import ToolResult, tool


@tool
class TaskTool:
    """Delegate tasks to specialized agents via sub-sessions (stub)."""

    name = "task"
    description = "Delegate tasks to specialized agents. Currently a stub in the IPC service."
    input_schema = {
        "type": "object",
        "properties": {
            "task": {"type": "string", "description": "Task instruction in 'agent: instruction' format"},
        },
        "required": ["task"],
    }

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        return ToolResult(
            success=False,
            error={"message": "TaskTool stub: sub-session spawning not yet implemented in IPC service"},
        )
```

**Step 6: Run test to verify it passes**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-foundation
uv run pytest tests/test_tools_simple.py -v
```
Expected: All 6 tests PASS.

**Step 7: Commit**
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-foundation
git add -A && git commit -m "feat: port web tools and create delegate/task stubs"
```

---

### Task 5: Port Subdirectory Tools (bash, filesystem, search) with Proxy Pattern

Port tools that live in subdirectories. The subdirectory code is copied with import fixes. Then a proxy `.py` file at the `tools/` top level re-exports the decorated class so `scan_package()` finds it.

**Files:**
- Create: `src/amplifier_foundation/tools/bash/__init__.py` (ported BashTool)
- Create: `src/amplifier_foundation/tools/bash/safety.py` (copied)
- Create: `src/amplifier_foundation/tools/bash_tool.py` (proxy for discovery)
- Create: `src/amplifier_foundation/tools/filesystem/*.py` (ported)
- Create: `src/amplifier_foundation/tools/filesystem_tools.py` (proxy)
- Create: `src/amplifier_foundation/tools/search/*.py` (ported)
- Create: `src/amplifier_foundation/tools/search_tools.py` (proxy)
- Test: `tests/test_tools_subdir.py`

**Step 1: Write the failing test**

Create `tests/test_tools_subdir.py`:

```python
"""Tests for subdirectory tools — discovery via proxy pattern."""

from __future__ import annotations

import pytest
from amplifier_ipc_protocol.discovery import scan_package


def test_bash_tool_discovered() -> None:
    """BashTool is discovered via proxy file."""
    components = scan_package("amplifier_foundation")
    tool_names = [getattr(t, "name", "") for t in components.get("tool", [])]
    assert "bash" in tool_names, f"'bash' not found: {tool_names}"


def test_read_file_tool_discovered() -> None:
    """ReadTool is discovered via proxy file."""
    components = scan_package("amplifier_foundation")
    tool_names = [getattr(t, "name", "") for t in components.get("tool", [])]
    assert "read_file" in tool_names, f"'read_file' not found: {tool_names}"


def test_write_file_tool_discovered() -> None:
    """WriteTool is discovered via proxy file."""
    components = scan_package("amplifier_foundation")
    tool_names = [getattr(t, "name", "") for t in components.get("tool", [])]
    assert "write_file" in tool_names, f"'write_file' not found: {tool_names}"


def test_edit_file_tool_discovered() -> None:
    """EditTool is discovered via proxy file."""
    components = scan_package("amplifier_foundation")
    tool_names = [getattr(t, "name", "") for t in components.get("tool", [])]
    assert "edit_file" in tool_names, f"'edit_file' not found: {tool_names}"


def test_grep_tool_discovered() -> None:
    """GrepTool is discovered via proxy file."""
    components = scan_package("amplifier_foundation")
    tool_names = [getattr(t, "name", "") for t in components.get("tool", [])]
    assert "grep" in tool_names, f"'grep' not found: {tool_names}"


def test_glob_tool_discovered() -> None:
    """GlobTool is discovered via proxy file."""
    components = scan_package("amplifier_foundation")
    tool_names = [getattr(t, "name", "") for t in components.get("tool", [])]
    assert "glob" in tool_names, f"'glob' not found: {tool_names}"


@pytest.mark.asyncio
async def test_bash_tool_rejects_empty_command() -> None:
    """BashTool returns error when command is missing."""
    components = scan_package("amplifier_foundation")
    bash = next(t for t in components.get("tool", []) if getattr(t, "name", "") == "bash")
    result = await bash.execute({})
    assert result.success is False
```

**Step 2: Run test to verify it fails**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-foundation
uv run pytest tests/test_tools_subdir.py -v
```
Expected: FAIL

**Step 3: Port BashTool**

Copy `bash/safety.py` from source, fixing imports (remove any `amplifier_lite` imports). This file is mostly self-contained.

Copy `bash/__init__.py` from source. Key changes:
- Replace `from amplifier_lite.models import ToolResult` → `from amplifier_ipc_protocol import ToolResult`
- Remove `from amplifier_lite.session import Session`
- Remove `session` parameter from `__init__`, use `config=None` default
- Add `@tool` is NOT applied here (it goes on the proxy) — OR apply `@tool` directly to `BashTool` and import it in the proxy. **Preferred approach:** Apply `@tool` directly in `bash/__init__.py` on `BashTool`. The proxy file just re-imports it so `scan_package` can find it.
- Change `__init__` to `def __init__(self) -> None:` with defaults for all config values

Create proxy `src/amplifier_foundation/tools/bash_tool.py`:
```python
"""Proxy for BashTool discovery — scan_package only checks top-level .py files."""

from amplifier_foundation.tools.bash import BashTool  # noqa: F401

__all__ = ["BashTool"]
```

**Step 4: Port filesystem tools**

Copy `filesystem/read.py`, `filesystem/write.py`, `filesystem/edit.py`, `filesystem/path_validation.py`, `filesystem/__init__.py` from source. Apply the same import conversion pattern. Add `@tool` decorator to `ReadTool`, `WriteTool`, `EditTool`.

Create proxy `src/amplifier_foundation/tools/filesystem_tools.py`:
```python
"""Proxy for filesystem tool discovery."""

from amplifier_foundation.tools.filesystem.read import ReadTool  # noqa: F401
from amplifier_foundation.tools.filesystem.write import WriteTool  # noqa: F401
from amplifier_foundation.tools.filesystem.edit import EditTool  # noqa: F401

__all__ = ["ReadTool", "WriteTool", "EditTool"]
```

**Step 5: Port search tools**

Copy `search/grep.py`, `search/glob.py`, `search/__init__.py` from source. Apply import conversion. Add `@tool` decorator to `GrepTool`, `GlobTool`.

Create proxy `src/amplifier_foundation/tools/search_tools.py`:
```python
"""Proxy for search tool discovery."""

from amplifier_foundation.tools.search.grep import GrepTool  # noqa: F401
from amplifier_foundation.tools.search.glob import GlobTool  # noqa: F401

__all__ = ["GrepTool", "GlobTool"]
```

**Step 6: Run test to verify it passes**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-foundation
uv run pytest tests/test_tools_subdir.py -v
```
Expected: All 7 tests PASS.

**Step 7: Commit**
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-foundation
git add -A && git commit -m "feat: port bash, filesystem, search tools with proxy discovery"
```

---

### Task 6: Port Remaining Tool Stubs (mcp, recipes, apply_patch, bundle_python_dev, bundle_shadow)

These tools have heavy dependencies on amplifier-lite internals (`Session`, `spawn_utils`, MCP SDK). Create stubs with correct names, descriptions, and schemas but return "not implemented" for execution. This ensures `describe` reports them all correctly.

**Files:**
- Create: `src/amplifier_foundation/tools/mcp_tool.py`
- Create: `src/amplifier_foundation/tools/recipes_tool.py`
- Create: `src/amplifier_foundation/tools/apply_patch_tool.py`
- Create: `src/amplifier_foundation/tools/python_dev_tool.py`
- Create: `src/amplifier_foundation/tools/shadow_tool.py`
- Test: `tests/test_tools_stubs.py`

**Step 1: Write the failing test**

Create `tests/test_tools_stubs.py`:

```python
"""Tests for stub tools — all discovered with correct names."""

from __future__ import annotations

from amplifier_ipc_protocol.discovery import scan_package

EXPECTED_STUB_TOOLS = ["mcp", "recipes", "apply_patch", "python_check", "shadow"]


def test_all_stub_tools_discovered() -> None:
    """All stub tools are discovered by scan_package."""
    components = scan_package("amplifier_foundation")
    tool_names = {getattr(t, "name", "") for t in components.get("tool", [])}
    for expected in EXPECTED_STUB_TOOLS:
        assert expected in tool_names, f"'{expected}' not found in discovered tools: {sorted(tool_names)}"


def test_all_stub_tools_have_description() -> None:
    """All stub tools have non-empty descriptions."""
    components = scan_package("amplifier_foundation")
    for t in components.get("tool", []):
        name = getattr(t, "name", "")
        if name in EXPECTED_STUB_TOOLS:
            desc = getattr(t, "description", "")
            assert len(desc) > 10, f"Tool '{name}' has empty or short description"
```

**Step 2: Run test to verify it fails**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-foundation
uv run pytest tests/test_tools_stubs.py -v
```
Expected: FAIL

**Step 3: Create all stub tool files**

Create each stub file following the same pattern as DelegateTool/TaskTool from Task 4. Each file gets `@tool` decorator, `name`, `description`, `input_schema` class attributes, and an `execute` method that returns `ToolResult(success=False, error={"message": "... not yet implemented in IPC service"})`.

For the tool names, look at the source to get the exact names:
- `mcp_tool.py`: `name = "mcp"` (MCPToolWrapper in source)
- `recipes_tool.py`: `name = "recipes"` (RecipesTool in source)
- `apply_patch_tool.py`: `name = "apply_patch"` (ApplyPatchTool in source)
- `python_dev_tool.py`: `name = "python_check"` (PythonDevTool in source)
- `shadow_tool.py`: `name = "shadow"` (ShadowTool in source)

Each gets a minimal but accurate `input_schema` from the source code.

**Step 4: Run test to verify it passes**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-foundation
uv run pytest tests/test_tools_stubs.py -v
```
Expected: All tests PASS.

**Step 5: Commit**
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-foundation
git add -A && git commit -m "feat: create stub tools (mcp, recipes, apply_patch, python_dev, shadow)"
```

---

### Task 7: Port Simple Hooks (deprecation, progress_monitor, redaction, todo_display, todo_reminder)

Port hooks that live in single files. The key conversion:
- Replace `from amplifier_lite.models import HookAction, HookResult` → `from amplifier_ipc_protocol import HookAction, HookResult, hook`
- Remove `Session` dependency
- Remove `register(self, hooks)` method pattern — replaced by `@hook(events=[...], priority=N)` decorator
- Add/keep a `handle(self, event, data) -> HookResult` method that dispatches internally if the hook handles multiple events

**Files:**
- Create: `src/amplifier_foundation/hooks/deprecation.py`
- Create: `src/amplifier_foundation/hooks/progress_monitor.py`
- Create: `src/amplifier_foundation/hooks/redaction.py`
- Create: `src/amplifier_foundation/hooks/todo_display.py`
- Create: `src/amplifier_foundation/hooks/todo_reminder.py`
- Test: `tests/test_hooks_simple.py`

**Step 1: Write the failing test**

Create `tests/test_hooks_simple.py`:

```python
"""Tests for simple hooks — discovery and interface compliance."""

from __future__ import annotations

import pytest
from amplifier_ipc_protocol import HookAction, HookResult
from amplifier_ipc_protocol.discovery import scan_package

EXPECTED_HOOKS = ["deprecation", "progress_monitor", "redaction", "todo_display", "todo_reminder"]


def test_simple_hooks_discovered() -> None:
    """All simple hooks are discovered by scan_package."""
    components = scan_package("amplifier_foundation")
    hook_names = {getattr(h, "name", "") for h in components.get("hook", [])}
    for expected in EXPECTED_HOOKS:
        assert expected in hook_names, f"'{expected}' not found in discovered hooks: {sorted(hook_names)}"


def test_hooks_have_events_attribute() -> None:
    """All discovered hooks have events attribute (from decorator or instance)."""
    components = scan_package("amplifier_foundation")
    for h in components.get("hook", []):
        name = getattr(h, "name", "")
        if name in EXPECTED_HOOKS:
            events = getattr(h, "events", getattr(h, "__amplifier_hook_events__", None))
            assert events is not None, f"Hook '{name}' has no events attribute"
            assert len(events) > 0, f"Hook '{name}' has empty events list"


@pytest.mark.asyncio
async def test_todo_reminder_handle_returns_hook_result() -> None:
    """TodoReminderHook.handle() returns a HookResult."""
    components = scan_package("amplifier_foundation")
    hook = next(h for h in components.get("hook", []) if getattr(h, "name", "") == "todo_reminder")
    result = await hook.handle("provider:request", {})
    assert isinstance(result, HookResult)
    assert result.action in [a.value for a in HookAction] or isinstance(result.action, HookAction)
```

**Step 2: Run test to verify it fails**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-foundation
uv run pytest tests/test_hooks_simple.py -v
```
Expected: FAIL

**Step 3: Port each hook**

For each hook, the conversion pattern is:

**Original pattern (amplifier-lite):**
```python
class TodoReminderHook:
    def __init__(self, config=None, session=None):
        ...
    def register(self, hooks):
        hooks.register("tool:post", self.on_tool_post, priority=10, name="...")
        hooks.register("provider:request", self.on_provider_request, priority=10, name="...")
    async def on_tool_post(self, event, data) -> HookResult: ...
    async def on_provider_request(self, event, data) -> HookResult: ...
```

**IPC pattern:**
```python
@hook(events=["tool:post", "provider:request"], priority=10)
class TodoReminderHook:
    name = "todo_reminder"
    events = ["tool:post", "provider:request"]
    priority = 10

    def __init__(self) -> None:
        ...

    async def handle(self, event: str, data: dict) -> HookResult:
        if event == "tool:post":
            return await self._on_tool_post(data)
        if event == "provider:request":
            return await self._on_provider_request(data)
        return HookResult(action=HookAction.CONTINUE)

    async def _on_tool_post(self, data: dict) -> HookResult: ...
    async def _on_provider_request(self, data: dict) -> HookResult: ...
```

Apply this pattern to all 5 hooks. The internal logic of each handler stays the same — only the wiring changes.

**Important notes per hook:**
- **deprecation.py**: The `DeprecationHook` calls `self.hooks.emit()` internally for `deprecation:warning` events. In IPC, this becomes a no-op for now (hooks can't emit other events through the host from within a handle call). Just log instead.
- **progress_monitor.py**: Uses `ProgressMonitorConfig` dataclass and `ProgressState` — keep these, they're self-contained.
- **redaction.py**: Mostly stateless functions with `SECRET_PATTERNS` and `PII_PATTERNS` — keep all the regex logic.
- **todo_display.py** and **todo_reminder.py**: Used `self.session` to access `todo_state`. In IPC, they won't have access to the todo tool's state. For now, make `handle()` return `HookResult(action=HookAction.CONTINUE)` — the hooks will need a shared state mechanism later.

**Step 4: Run test to verify it passes**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-foundation
uv run pytest tests/test_hooks_simple.py -v
```
Expected: All tests PASS.

**Step 5: Commit**
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-foundation
git add -A && git commit -m "feat: port simple hooks (deprecation, progress_monitor, redaction, todo_display, todo_reminder)"
```

---

### Task 8: Port Remaining Hooks (approval, logging, routing, session_naming, shell, status_context, streaming_ui)

Port the remaining hooks. Complex multi-file hooks (approval, routing, shell) use the same proxy pattern as subdirectory tools. Some hooks with heavy session dependencies get stub implementations.

**Files:**
- Create: `src/amplifier_foundation/hooks/approval/*.py` + `src/amplifier_foundation/hooks/approval_hook.py` (proxy)
- Create: `src/amplifier_foundation/hooks/logging.py`
- Create: `src/amplifier_foundation/hooks/routing/*.py` + `src/amplifier_foundation/hooks/routing_hook.py` (proxy)
- Create: `src/amplifier_foundation/hooks/session_naming.py`
- Create: `src/amplifier_foundation/hooks/shell/*.py` + `src/amplifier_foundation/hooks/shell_hook.py` (proxy)
- Create: `src/amplifier_foundation/hooks/status_context.py`
- Create: `src/amplifier_foundation/hooks/streaming_ui.py`
- Test: `tests/test_hooks_remaining.py`

**Step 1: Write the failing test**

Create `tests/test_hooks_remaining.py`:

```python
"""Tests for remaining hooks — discovery."""

from __future__ import annotations

from amplifier_ipc_protocol.discovery import scan_package

EXPECTED_HOOKS = [
    "approval",
    "logging",
    "routing",
    "session_naming",
    "shell",
    "status_context",
    "streaming_ui",
]


def test_all_remaining_hooks_discovered() -> None:
    """All remaining hooks are discovered by scan_package."""
    components = scan_package("amplifier_foundation")
    hook_names = {getattr(h, "name", "") for h in components.get("hook", [])}
    for expected in EXPECTED_HOOKS:
        assert expected in hook_names, f"'{expected}' not found in discovered hooks: {sorted(hook_names)}"


def test_all_hooks_have_handle_method() -> None:
    """All hooks have a handle(event, data) method."""
    components = scan_package("amplifier_foundation")
    for h in components.get("hook", []):
        name = getattr(h, "name", "")
        if name in EXPECTED_HOOKS:
            assert hasattr(h, "handle"), f"Hook '{name}' missing handle() method"
            assert callable(h.handle), f"Hook '{name}' handle is not callable"
```

**Step 2: Run test to verify it fails**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-foundation
uv run pytest tests/test_hooks_remaining.py -v
```
Expected: FAIL

**Step 3: Port or stub each hook**

Apply the same conversion pattern from Task 7. For multi-file hooks:

**Approval hook** (`hooks/approval/`):
- Copy `approval_hook.py`, `audit.py`, `config.py`. Fix imports.
- `ApprovalHook` has `handle_tool_pre` — rename to internal `_handle_tool_pre`, add `handle()` dispatcher
- It uses `self.hooks` to emit `APPROVAL_REQUIRED`, `APPROVAL_GRANTED`, `APPROVAL_DENIED` — remove these internal emit calls, just log them
- It uses `ApprovalProvider` from `amplifier_lite.models` — either stub this or make approval always auto-approve in IPC mode for now
- Create proxy: `hooks/approval_hook.py` that imports and re-exports

**Routing hook** (`hooks/routing/`):
- Copy `resolver.py`, `matrix_loader.py`. Fix imports.
- Create the `@hook` decorated class. Create proxy.

**Shell hook** (`hooks/shell/`):
- Copy `bridge.py`, `executor.py`, `loader.py`, `matcher.py`, `translator.py`. Fix imports.
- Create proxy.

**Simple file hooks** (logging, session_naming, status_context, streaming_ui):
- These use `rich.console`, datetime, pathlib — mostly self-contained
- `session_naming.py` makes LLM calls via provider — stub this to return CONTINUE for now
- `streaming_ui.py` uses `rich.console` — port with handle() dispatcher, but note it renders to local console which won't work over IPC. Stub the actual rendering.
- `logging.py` writes to files — port the logic, remove session dependency
- `status_context.py` reads git/system info — port fully, it's self-contained

**Step 4: Run test to verify it passes**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-foundation
uv run pytest tests/test_hooks_remaining.py -v
```
Expected: All tests PASS.

**Step 5: Commit**
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-foundation
git add -A && git commit -m "feat: port remaining hooks (approval, logging, routing, session_naming, shell, status_context, streaming_ui)"
```

---

### Task 9: Port SimpleContextManager

Port the context manager. This is straightforward — the context manager is mostly self-contained. The main change is removing Session dependency and adding the `@context_manager` decorator.

**Files:**
- Create: `src/amplifier_foundation/context_managers/simple.py`
- Test: `tests/test_context_manager.py`

**Step 1: Write the failing test**

Create `tests/test_context_manager.py`:

```python
"""Tests for SimpleContextManager with @context_manager decorator."""

from __future__ import annotations

import pytest
from amplifier_ipc_protocol import Message
from amplifier_ipc_protocol.discovery import scan_package


def test_context_manager_discovered() -> None:
    """SimpleContextManager is discovered by scan_package."""
    components = scan_package("amplifier_foundation")
    cm_names = [getattr(c, "name", "") for c in components.get("context_manager", [])]
    assert "simple" in cm_names, f"'simple' not found in context managers: {cm_names}"


@pytest.mark.asyncio
async def test_add_and_get_messages() -> None:
    """Context manager stores and retrieves messages."""
    components = scan_package("amplifier_foundation")
    cm = next(c for c in components.get("context_manager", []) if getattr(c, "name", "") == "simple")

    await cm.add_message(Message(role="user", content="Hello"))
    await cm.add_message(Message(role="assistant", content="Hi there"))

    messages = await cm.get_messages({})
    assert len(messages) >= 2
    roles = [m.role for m in messages]
    assert "user" in roles
    assert "assistant" in roles


@pytest.mark.asyncio
async def test_clear_messages() -> None:
    """Context manager clears all messages."""
    components = scan_package("amplifier_foundation")
    cm = next(c for c in components.get("context_manager", []) if getattr(c, "name", "") == "simple")

    await cm.add_message(Message(role="user", content="Hello"))
    await cm.clear()

    messages = await cm.get_messages({})
    assert len(messages) == 0
```

**Step 2: Run test to verify it fails**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-foundation
uv run pytest tests/test_context_manager.py -v
```
Expected: FAIL

**Step 3: Port SimpleContextManager**

Copy `context_managers/simple.py` from source and make these changes:

- Replace `from amplifier_lite.models import Message, ToolCall` → `from amplifier_ipc_protocol import Message, ToolCall, context_manager`
- Remove `from amplifier_lite.session import Session`
- Add `@context_manager` decorator to `SimpleContextManager`
- Add `name = "simple"` class attribute
- Change `__init__` to `def __init__(self) -> None:` with sensible defaults (no config/session params)
- Rename `get_messages_for_request` to `get_messages` to match the `ContextManagerProtocol`:
  ```python
  async def get_messages(self, provider_info: dict) -> list[Message]:
      """Get messages for LLM request. Maps to ContextManagerProtocol.get_messages."""
      # provider_info can carry provider details for budget calculation
      provider = provider_info.get("provider") if provider_info else None
      return await self._get_messages_for_request(provider=provider)
  ```
- Keep all the ephemeral compaction logic intact — it's self-contained and doesn't depend on external services
- Remove `_system_prompt_factory` support (the host handles system prompt assembly now)
- Remove the `_hooks` field (hooks are emitted through the orchestrator, not the context manager)

**Step 4: Run test to verify it passes**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-foundation
uv run pytest tests/test_context_manager.py -v
```
Expected: All 3 tests PASS.

**Step 5: Commit**
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-foundation
git add -A && git commit -m "feat: port SimpleContextManager with @context_manager decorator"
```

---

### Task 10: Port StreamingOrchestrator (IPC Conversion)

**This is the biggest task.** The StreamingOrchestrator is ~1300 lines. The conversion is mechanical but extensive: every direct object call becomes a JSON-RPC request through `self.client`.

**Files:**
- Create: `src/amplifier_foundation/orchestrators/streaming.py`
- Test: `tests/test_orchestrator.py`

**Step 1: Write the failing test**

Create `tests/test_orchestrator.py`:

```python
"""Tests for StreamingOrchestrator IPC conversion.

Uses a MockClient that records requests and returns canned responses,
simulating what the host would do.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock

import pytest
from amplifier_ipc_protocol import HookAction, HookResult, Message, ChatResponse
from amplifier_ipc_protocol.discovery import scan_package


def test_orchestrator_discovered() -> None:
    """StreamingOrchestrator is discovered by scan_package."""
    components = scan_package("amplifier_foundation")
    orch_names = [getattr(o, "name", "") for o in components.get("orchestrator", [])]
    assert "streaming" in orch_names, f"'streaming' not in orchestrators: {orch_names}"


class MockClient:
    """Mock Client that records requests and returns canned responses."""

    def __init__(self, responses: dict[str, Any] | None = None) -> None:
        self.requests: list[tuple[str, Any]] = []
        self.notifications: list[tuple[str, Any]] = []
        self._responses = responses or {}
        self._default_hook_result = {
            "action": "CONTINUE",
        }
        self._call_count: dict[str, int] = {}

    async def request(self, method: str, params: Any = None) -> Any:
        self.requests.append((method, params))
        self._call_count[method] = self._call_count.get(method, 0) + 1

        if method in self._responses:
            resp = self._responses[method]
            if callable(resp):
                return resp(params)
            return resp

        # Default responses by method
        if method == "request.hook_emit":
            return self._default_hook_result
        if method == "request.context_add_message":
            return {"ok": True}
        if method == "request.context_get_messages":
            return {"messages": [
                {"role": "user", "content": "test prompt"},
            ]}
        if method == "request.provider_complete":
            return {
                "content": "Test response from LLM",
                "tool_calls": None,
                "text": "Test response from LLM",
            }
        if method == "request.context_clear":
            return {"ok": True}

        return {"ok": True}

    async def send_notification(self, method: str, params: Any = None) -> None:
        self.notifications.append((method, params))


@pytest.mark.asyncio
async def test_orchestrator_execute_simple_response() -> None:
    """Orchestrator makes correct IPC calls for a simple (no tool calls) response."""
    components = scan_package("amplifier_foundation")
    orch = next(o for o in components.get("orchestrator", []) if getattr(o, "name", "") == "streaming")

    client = MockClient()
    result = await orch.execute(
        prompt="Hello",
        config={"max_iterations": 5},
        client=client,
    )

    # Should have made hook_emit calls (prompt:submit, execution:start, provider:request, etc.)
    hook_calls = [r for r in client.requests if r[0] == "request.hook_emit"]
    assert len(hook_calls) > 0, "Expected at least one hook_emit call"

    # Should have added user message to context
    add_msg_calls = [r for r in client.requests if r[0] == "request.context_add_message"]
    assert len(add_msg_calls) >= 1, "Expected at least one context_add_message call"

    # Should have called provider_complete
    provider_calls = [r for r in client.requests if r[0] == "request.provider_complete"]
    assert len(provider_calls) >= 1, "Expected at least one provider_complete call"

    # Result should be the response text
    assert isinstance(result, str)
    assert len(result) > 0


@pytest.mark.asyncio
async def test_orchestrator_handles_tool_calls() -> None:
    """Orchestrator correctly dispatches tool calls via IPC."""
    call_count = {"provider": 0}

    def mock_provider_complete(params: Any) -> dict:
        call_count["provider"] += 1
        if call_count["provider"] == 1:
            # First call: return tool call
            return {
                "content": "",
                "text": "",
                "tool_calls": [
                    {"id": "tc_1", "tool": "todo", "arguments": {"action": "list"}},
                ],
            }
        # Second call: final response (no tools)
        return {
            "content": "Done!",
            "text": "Done!",
            "tool_calls": None,
        }

    client = MockClient(responses={
        "request.provider_complete": mock_provider_complete,
    })

    components = scan_package("amplifier_foundation")
    orch = next(o for o in components.get("orchestrator", []) if getattr(o, "name", "") == "streaming")

    result = await orch.execute(
        prompt="List todos",
        config={"max_iterations": 5},
        client=client,
    )

    # Should have made a tool_execute call
    tool_calls = [r for r in client.requests if r[0] == "request.tool_execute"]
    assert len(tool_calls) >= 1, "Expected at least one tool_execute call"

    # The tool_execute should have the right tool name
    assert tool_calls[0][1]["name"] == "todo"


@pytest.mark.asyncio
async def test_orchestrator_hook_deny_stops_execution() -> None:
    """When prompt:submit hook returns DENY, orchestrator stops."""
    client = MockClient(responses={
        "request.hook_emit": lambda params: (
            {"action": "DENY", "reason": "Blocked by test"}
            if params.get("event") == "prompt:submit"
            else {"action": "CONTINUE"}
        ),
    })

    components = scan_package("amplifier_foundation")
    orch = next(o for o in components.get("orchestrator", []) if getattr(o, "name", "") == "streaming")

    result = await orch.execute(
        prompt="blocked prompt",
        config={},
        client=client,
    )

    assert "denied" in result.lower() or "blocked" in result.lower()

    # Should NOT have called provider_complete
    provider_calls = [r for r in client.requests if r[0] == "request.provider_complete"]
    assert len(provider_calls) == 0, "Should not call provider when prompt is denied"
```

**Step 2: Run test to verify it fails**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-foundation
uv run pytest tests/test_orchestrator.py -v
```
Expected: FAIL

**Step 3: Create the converted StreamingOrchestrator**

Create `src/amplifier_foundation/orchestrators/streaming.py`. This is the biggest file. Start from the source and apply these systematic conversions:

**Import changes:**
```python
# OLD:
from amplifier_lite.hooks import HookRegistry
from amplifier_lite.models import HookAction, ToolCall, ToolResult
from amplifier_lite.events import PROMPT_SUBMIT, PROVIDER_REQUEST, TOOL_PRE, TOOL_POST, ...
from amplifier_lite.models import ChatRequest, Message, ToolSpec, LLMError
from amplifier_lite.session import Session

# NEW:
from amplifier_ipc_protocol import (
    orchestrator, HookAction, HookResult, ToolCall, ToolResult,
    ChatRequest, ChatResponse, Message, ToolSpec,
)
```

**Event constants** — define them locally (they were imported from `amplifier_lite.events`):
```python
PROMPT_SUBMIT = "prompt:submit"
PROMPT_COMPLETE = "prompt:complete"
PROVIDER_REQUEST = "provider:request"
PROVIDER_ERROR = "provider:error"
TOOL_PRE = "tool:pre"
TOOL_POST = "tool:post"
TOOL_ERROR = "tool:error"
ORCHESTRATOR_COMPLETE = "orchestrator:complete"
CONTENT_BLOCK_START = "content_block:start"
CONTENT_BLOCK_END = "content_block:end"
```

**Class signature:**
```python
@orchestrator
class StreamingOrchestrator:
    name = "streaming"

    def __init__(self) -> None:
        self.max_iterations = -1  # -1 means unlimited
        self.stream_delay = 0.01
        self._pending_ephemeral_injections: list[dict[str, Any]] = []
        self._last_provider_call_end: float | None = None
```

**Execute signature** — matches `OrchestratorProtocol`:
```python
async def execute(self, prompt: str, config: dict[str, Any], client: Any) -> str:
    """Execute the agent loop using IPC client for all external calls."""
    # Apply config
    self.max_iterations = config.get("max_iterations", -1)
    self.stream_delay = config.get("stream_delay", 0.01)
    self.client = client  # Store for use in helper methods
    # ... rest of execute logic
```

**Systematic call conversions** — every call changes like this:

| Old call | New call |
|----------|----------|
| `await hooks.emit(EVENT, data)` | `result = await self.client.request("request.hook_emit", {"event": EVENT, "data": data})` then `HookResult(**result)` to parse |
| `await context.add_message(msg)` | `await self.client.request("request.context_add_message", {"message": msg.model_dump(mode="json")})` |
| `await context.get_messages_for_request(provider=p)` | `resp = await self.client.request("request.context_get_messages", {"provider_info": {}})` then `[Message(**m) for m in resp["messages"]]` |
| `await provider.complete(request)` | `resp = await self.client.request("request.provider_complete", {"request": request.model_dump(mode="json")})` then `ChatResponse(**resp)` |
| `await tool.execute(args)` | `resp = await self.client.request("request.tool_execute", {"name": tool_name, "input": args})` then `ToolResult(**resp)` |
| `tools_list = [ToolSpec(...) for t in tools.values()]` | The tools are passed as part of the orchestrator.execute params from the host. Access `config.get("tools", [])` for ToolSpec data. |
| `yield (token, iteration)` | `await self.client.send_notification("stream.token", {"text": token})` |

**Key logic to preserve:**
1. **DENY checking** — After each `hook_emit`, parse the response. If `action == "DENY"`, stop.
2. **Ephemeral injection** — After `hook_emit` for `prompt:submit` and `tool:post`, check for `INJECT_CONTEXT` action and store in `_pending_ephemeral_injections`.
3. **MODIFY detection** — After `tool:post` hook, check if the returned data's `result` field is different from what was sent.
4. **Parallel tool dispatch** — Keep `asyncio.gather` for parallel tool execution. Each tool call goes through `request.tool_execute`.
5. **Max iterations** — Keep the max iterations loop with the system reminder injection.
6. **Rate limiting** — Keep `_apply_rate_limit_delay`.

**What to remove:**
- All `self.session` references and `Session` type
- `session.cancellation.is_cancelled` checks (cancellation will be handled differently in IPC)
- `session.process_hook_result()` calls (hook results are processed inline)
- `_select_provider()` (provider selection is done by the host)
- `provider.parse_tool_calls()` (tool calls come in the ChatResponse from the provider service)
- `provider.stream()` / `_stream_from_provider()` (streaming will be notification-based in IPC — simplify to non-streaming for now)
- `_tokenize_stream()` (artificial streaming delay)

**Simplified flow for the IPC version:**
```
1. emit prompt:submit hook → check DENY
2. add user message to context
3. Loop:
   a. emit provider:request hook → check DENY
   b. get messages from context
   c. apply ephemeral injections
   d. build ChatRequest
   e. call provider.complete → get ChatResponse
   f. emit stream.token notifications for the response text
   g. add assistant message to context
   h. if no tool_calls → break
   i. for each tool_call (parallel):
      - emit tool:pre hook → check DENY
      - call tool.execute
      - emit tool:post hook → check MODIFY
      - add tool result message to context
4. emit orchestrator:complete
5. return full_response
```

**Step 4: Run test to verify it passes**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-foundation
uv run pytest tests/test_orchestrator.py -v
```
Expected: All 4 tests PASS.

**Step 5: Commit**
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-foundation
git add -A && git commit -m "feat: port StreamingOrchestrator with IPC client conversion"
```

---

### Task 11: Service Describe Verification

Verify the full service starts, responds to `describe`, and reports all components correctly.

**Files:**
- Test: `tests/test_describe.py`

**Step 1: Write the failing test**

Create `tests/test_describe.py`:

```python
"""Tests that the full service describe response is correct."""

from __future__ import annotations

import asyncio
import json

from amplifier_ipc_protocol.server import Server


class _MockWriter:
    """Collects bytes written via write()/drain()."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def write(self, data: bytes) -> None:
        self._buf.extend(data)

    async def drain(self) -> None:
        pass

    @property
    def messages(self) -> list[dict]:
        result = []
        for line in self._buf.split(b"\n"):
            stripped = line.strip()
            if stripped:
                result.append(json.loads(stripped))
        return result


async def _send_describe() -> dict:
    """Start a Server, send describe, return the result."""
    server = Server("amplifier_foundation")
    reader = asyncio.StreamReader()
    writer = _MockWriter()

    msg = {"jsonrpc": "2.0", "id": 1, "method": "describe"}
    reader.feed_data((json.dumps(msg) + "\n").encode())
    reader.feed_eof()

    await server.handle_stream(reader, writer)
    responses = writer.messages
    assert len(responses) == 1
    return responses[0]["result"]


async def test_describe_has_orchestrator() -> None:
    """Describe reports the streaming orchestrator."""
    result = await _send_describe()
    caps = result["capabilities"]
    orch_names = [o["name"] for o in caps["orchestrators"]]
    assert "streaming" in orch_names


async def test_describe_has_context_manager() -> None:
    """Describe reports the simple context manager."""
    result = await _send_describe()
    caps = result["capabilities"]
    cm_names = [c["name"] for c in caps["context_managers"]]
    assert "simple" in cm_names


async def test_describe_has_tools() -> None:
    """Describe reports at least 10 tools."""
    result = await _send_describe()
    caps = result["capabilities"]
    tools = caps["tools"]
    assert len(tools) >= 10, f"Expected >=10 tools, got {len(tools)}: {[t['name'] for t in tools]}"

    # Check key tools are present
    tool_names = {t["name"] for t in tools}
    for expected in ["bash", "todo", "read_file", "write_file", "edit_file", "grep", "glob", "web_search", "web_fetch"]:
        assert expected in tool_names, f"'{expected}' not in tools: {sorted(tool_names)}"


async def test_describe_has_hooks() -> None:
    """Describe reports at least 10 hooks."""
    result = await _send_describe()
    caps = result["capabilities"]
    hooks = caps["hooks"]
    assert len(hooks) >= 10, f"Expected >=10 hooks, got {len(hooks)}: {[h['name'] for h in hooks]}"


async def test_describe_has_content() -> None:
    """Describe reports content files."""
    result = await _send_describe()
    caps = result["capabilities"]
    content_paths = caps["content"]["paths"]
    assert len(content_paths) >= 20, f"Expected >=20 content paths, got {len(content_paths)}"

    # Check key content categories
    agents = [p for p in content_paths if p.startswith("agents/")]
    behaviors = [p for p in content_paths if p.startswith("behaviors/")]
    context = [p for p in content_paths if p.startswith("context/")]
    assert len(agents) >= 5
    assert len(behaviors) >= 5
    assert len(context) >= 5
```

**Step 2: Run test**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-foundation
uv run pytest tests/test_describe.py -v
```
Expected: All 5 tests PASS (if all previous tasks completed correctly).

If any fail, debug and fix. Common issues:
- Missing `__init__.py` in component directories
- Tool/hook classes not decorated
- Import errors in ported files

**Step 3: Commit**
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-foundation
git add -A && git commit -m "test: verify full service describe response"
```

---

### Task 12: Integration Test — Tool Execute and Content Read

Test the full service handling actual JSON-RPC requests for tool execution and content reading.

**Files:**
- Test: `tests/test_integration.py`

**Step 1: Write the test**

Create `tests/test_integration.py`:

```python
"""Integration tests — full Server handling tool.execute and content.read."""

from __future__ import annotations

import asyncio
import json

import pytest
from amplifier_ipc_protocol.server import Server


class _MockWriter:
    def __init__(self) -> None:
        self._buf = bytearray()

    def write(self, data: bytes) -> None:
        self._buf.extend(data)

    async def drain(self) -> None:
        pass

    @property
    def messages(self) -> list[dict]:
        result = []
        for line in self._buf.split(b"\n"):
            stripped = line.strip()
            if stripped:
                result.append(json.loads(stripped))
        return result


async def _send_messages(messages: list[dict]) -> list[dict]:
    """Send messages to a Server and return responses."""
    server = Server("amplifier_foundation")
    reader = asyncio.StreamReader()
    writer = _MockWriter()

    for msg in messages:
        reader.feed_data((json.dumps(msg) + "\n").encode())
    reader.feed_eof()

    await server.handle_stream(reader, writer)
    return writer.messages


async def test_tool_execute_todo_create() -> None:
    """tool.execute dispatches to TodoTool and returns ToolResult."""
    responses = await _send_messages([
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tool.execute",
            "params": {
                "name": "todo",
                "input": {
                    "action": "create",
                    "todos": [
                        {"content": "Test", "activeForm": "Testing", "status": "pending"},
                    ],
                },
            },
        }
    ])

    assert len(responses) == 1
    result = responses[0]["result"]
    assert result["success"] is True
    assert result["output"]["count"] == 1


async def test_tool_execute_unknown_tool() -> None:
    """tool.execute for unknown tool returns JSON-RPC error."""
    responses = await _send_messages([
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tool.execute",
            "params": {"name": "nonexistent_tool", "input": {}},
        }
    ])

    assert len(responses) == 1
    assert "error" in responses[0]


async def test_content_read_agent_file() -> None:
    """content.read returns content of an agent .md file."""
    responses = await _send_messages([
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "content.read",
            "params": {"path": "agents/explorer.md"},
        }
    ])

    assert len(responses) == 1
    result = responses[0]["result"]
    assert "content" in result
    assert len(result["content"]) > 0


async def test_content_list_agents() -> None:
    """content.list returns agent file paths."""
    responses = await _send_messages([
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "content.list",
            "params": {"prefix": "agents/"},
        }
    ])

    assert len(responses) == 1
    result = responses[0]["result"]
    assert "paths" in result
    assert len(result["paths"]) >= 5


async def test_hook_emit_returns_hook_result() -> None:
    """hook.emit returns a HookResult dict."""
    responses = await _send_messages([
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "hook.emit",
            "params": {"event": "provider:request", "data": {"provider": "test"}},
        }
    ])

    assert len(responses) == 1
    result = responses[0]["result"]
    assert "action" in result


async def test_multiple_requests_in_sequence() -> None:
    """Server handles multiple requests in a single session."""
    responses = await _send_messages([
        {"jsonrpc": "2.0", "id": 1, "method": "describe"},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tool.execute",
            "params": {"name": "todo", "input": {"action": "list"}},
        },
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "content.list",
            "params": {},
        },
    ])

    assert len(responses) == 3
    # Describe
    assert "capabilities" in responses[0]["result"]
    # Tool execute
    assert responses[1]["result"]["success"] is True
    # Content list
    assert "paths" in responses[2]["result"]
```

**Step 2: Run test**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-foundation
uv run pytest tests/test_integration.py -v
```
Expected: All 6 tests PASS.

**Step 3: Commit**
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-foundation
git add -A && git commit -m "test: integration tests for tool.execute, content.read, hook.emit"
```

---

### Task 13: Run All Tests and Final Cleanup

Run the complete test suite, fix any issues, ensure the package is clean.

**Step 1: Run all tests**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-foundation
uv run pytest tests/ -v --tb=short
```
Expected: All tests PASS.

**Step 2: Verify the entry point works**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-foundation
echo '{"jsonrpc":"2.0","id":1,"method":"describe"}' | timeout 5 uv run amplifier-foundation-serve 2>/dev/null || true
```
Expected: Outputs a JSON-RPC response with the full describe result (tools, hooks, orchestrator, context_manager, content).

**Step 3: Count discovered components**

Run:
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-foundation
uv run python -c "
from amplifier_ipc_protocol.discovery import scan_package, scan_content
components = scan_package('amplifier_foundation')
content = scan_content('amplifier_foundation')
for ctype, instances in sorted(components.items()):
    print(f'{ctype}: {len(instances)} - {[getattr(i, \"name\", i.__class__.__name__) for i in instances]}')
print(f'content: {len(content)} files')
"
```
Expected output similar to:
```
context_manager: 1 - ['simple']
hook: 12 - ['approval', 'deprecation', 'logging', 'progress_monitor', 'redaction', 'routing', 'session_naming', 'shell', 'status_context', 'streaming_ui', 'todo_display', 'todo_reminder']
orchestrator: 1 - ['streaming']
tool: 14+ - ['bash', 'todo', 'web_search', 'web_fetch', 'read_file', 'write_file', 'edit_file', 'grep', 'glob', 'delegate', 'task', 'mcp', 'recipes', 'apply_patch', ...]
content: 50+ files
```

**Step 4: Final commit**
```bash
cd /data/labs/amplifier-lite/amplifier-ipc/services/amplifier-foundation
git add -A && git commit -m "feat: amplifier-foundation IPC service complete (Phase 3)"
```

---

## Summary

| Task | What it builds | Estimated effort |
|------|---------------|-----------------|
| 1 | Project scaffolding (pyproject.toml, dirs, venv) | 2 min |
| 2 | Content files (agents, behaviors, context, recipes, sessions) | 2 min |
| 3 | TodoTool (pattern establisher for all tools) | 3 min |
| 4 | Simple tools (web, delegate stub, task stub) | 4 min |
| 5 | Subdirectory tools (bash, filesystem, search) with proxy pattern | 5 min |
| 6 | Remaining tool stubs (mcp, recipes, apply_patch, python_dev, shadow) | 3 min |
| 7 | Simple hooks (deprecation, progress_monitor, redaction, todo_display, todo_reminder) | 5 min |
| 8 | Remaining hooks (approval, logging, routing, session_naming, shell, status_context, streaming_ui) | 5 min |
| 9 | SimpleContextManager | 4 min |
| 10 | StreamingOrchestrator (THE BIG ONE — full IPC conversion) | 10 min |
| 11 | Service describe verification | 2 min |
| 12 | Integration tests (tool.execute, content.read, hook.emit) | 3 min |
| 13 | Run all tests, final cleanup | 2 min |

**Total: 13 tasks, ~50 minutes of implementation time**
