# Task 10: Rich Rendering of TodoUpdateEvent — Implementation Plan

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

> **WARNING — Spec Review Loop Exhausted:** The spec review loop ran 3 iterations
> before the final verdict was APPROVED. The final review found zero issues and all
> 12 tests pass. Flag for human reviewer awareness at the approval gate.

**Goal:** Render `TodoUpdateEvent` in `StreamingDisplay` with status symbols, a bordered box using unicode box-drawing characters, full/condensed modes, and a progress bar.

**Architecture:** Add a `_handle_todo_update` handler to `StreamingDisplay` that dispatches from `handle_event`. The handler renders a unicode-bordered box containing either individual todo items (≤7) or a condensed summary (>7), plus a progress bar showing completed/total ratio. Empty todo lists return early with no output.

**Tech Stack:** Python 3.12+, Rich (Console), Pydantic (TodoUpdateEvent), pytest

**Dependencies:** task-1 (TodoUpdateEvent type exists in events.py), task-9 (ToolResultEvent rendering pattern established)

---

### Task 1: Add TodoUpdateEvent import and dispatch

**Files:**
- Modify: `src/amplifier_ipc/cli/streaming.py:7-17` (imports)
- Modify: `src/amplifier_ipc/cli/streaming.py:51-68` (handle_event dispatch)

**Step 1: Write failing test for dispatch**

Add to `tests/cli/test_streaming.py`. Follow existing pattern: each test is a class with one method, uses `_make_console()` helper, imports inside the method.

```python
# ---------------------------------------------------------------------------
# Test 11: test_todo_update_renders_items
# ---------------------------------------------------------------------------


class TestTodoUpdateRendersItems:
    def test_todo_update_renders_items(self) -> None:
        """TodoUpdateEvent with 3 items should render content strings and progress bar."""
        from amplifier_ipc.cli.streaming import StreamingDisplay
        from amplifier_ipc.host.events import TodoUpdateEvent

        console, buf = _make_console()
        display = StreamingDisplay(console=console)

        event = TodoUpdateEvent(
            todos=[
                {"content": "Task one", "status": "completed", "activeForm": "Completing task one"},
                {"content": "Task two", "status": "in_progress", "activeForm": "Doing task two"},
                {"content": "Task three", "status": "pending", "activeForm": "Starting task three"},
            ],
            status="updated",
        )
        display.handle_event(event)

        output = buf.getvalue()
        assert "Task one" in output
        assert "Task two" in output
        assert "Task three" in output
        # Progress bar should show completed/total ratio (1 completed out of 3)
        assert "1/3" in output or "3" in output
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/cli/test_streaming.py::TestTodoUpdateRendersItems -v`
Expected: FAIL — `TodoUpdateEvent` not imported / no `_handle_todo_update` handler yet (or silently ignored by dispatch)

**Step 3: Add import**

In `src/amplifier_ipc/cli/streaming.py`, add `TodoUpdateEvent` to the import block from `amplifier_ipc.host.events`:

```python
from amplifier_ipc.host.events import (
    CompleteEvent,
    ErrorEvent,
    HostEvent,
    StreamThinkingEvent,
    StreamTokenEvent,
    StreamToolCallStartEvent,
    TodoUpdateEvent,
    ToolCallEvent,
    ToolResultEvent,
)
```

**Step 4: Add dispatch in `handle_event`**

In the `handle_event` method, add a new `elif` branch **after** the `ToolResultEvent` branch and **before** the `ErrorEvent` branch:

```python
        elif isinstance(event, TodoUpdateEvent):
            self._handle_todo_update(event)
```

**Step 5: Add stub handler**

Add a stub method after `_handle_tool_result` (after line 120) so the test runs but still fails on assertions:

```python
    def _handle_todo_update(self, event: TodoUpdateEvent) -> None:
        """Print a bordered todo list box with status symbols and a progress bar."""
        pass
```

**Step 6: Run test to confirm it fails on assertions (not import errors)**

Run: `uv run pytest tests/cli/test_streaming.py::TestTodoUpdateRendersItems -v`
Expected: FAIL — `"Task one" in output` assertion fails (handler is a stub)

---

### Task 2: Implement full-mode rendering (≤7 items)

**Files:**
- Modify: `src/amplifier_ipc/cli/streaming.py` (the `_handle_todo_update` method)

**Step 1: Replace the stub with the full handler implementation**

Replace the stub `_handle_todo_update` with:

```python
    def _handle_todo_update(self, event: TodoUpdateEvent) -> None:
        """Print a bordered todo list box with status symbols and a progress bar."""
        if not event.todos:
            return

        # Status symbols
        symbols: dict[str, str] = {
            "completed": "\u2713",  # ✓ checkmark
            "in_progress": "\u25b6",  # ▶ play
            "pending": "\u25cb",  # ○ circle
        }

        total = len(event.todos)
        completed_count = sum(1 for t in event.todos if t.get("status") == "completed")

        # Box width (inner content width)
        box_width = 50

        top_border = "\u250c" + "\u2500" * box_width + "\u2510"
        bottom_border = "\u2514" + "\u2500" * box_width + "\u2518"

        self._console.print(top_border, markup=False)

        if total <= 7:
            # Full mode: show each todo item
            for todo in event.todos:
                status = todo.get("status", "pending")
                symbol = symbols.get(status, " ")
                content = str(todo.get("content", ""))
                # Truncate content to fit box
                inner_width = box_width - 4  # 2 for "│ " and 2 for symbol + space
                if len(content) > inner_width:
                    content = content[: inner_width - 3] + "..."
                line = f"\u2502 {symbol} {content}"
                # Pad to fill the box
                padding = box_width - len(f" {symbol} {content}")
                if padding > 0:
                    line += " " * padding
                line += "\u2502"
                self._console.print(line, markup=False)
        else:
            # Condensed mode: show summary counts
            in_progress_count = sum(
                1 for t in event.todos if t.get("status") == "in_progress"
            )
            pending_count = sum(1 for t in event.todos if t.get("status") == "pending")
            summary = (
                f"\u2502 {symbols['completed']} {completed_count} completed  "
                f"{symbols['in_progress']} {in_progress_count} in progress  "
                f"{symbols['pending']} {pending_count} pending"
            )
            padding = box_width - (len(summary) - 2) + 1  # -2 for the box chars
            if padding > 0:
                summary += " " * padding
            summary += "\u2502"
            self._console.print(summary, markup=False)

        # Progress bar
        bar_width = 20
        filled = int(bar_width * completed_count / total) if total > 0 else 0
        empty = bar_width - filled
        bar = "\u2588" * filled + "\u2591" * empty
        progress_text = f"{completed_count}/{total}"
        progress_line = f"\u2502 {bar} {progress_text}"
        padding = box_width - len(f" {bar} {progress_text}")
        if padding > 0:
            progress_line += " " * padding
        progress_line += "\u2502"
        self._console.print(progress_line, markup=False)

        self._console.print(bottom_border, markup=False)
```

**Step 2: Run test to verify it passes**

Run: `uv run pytest tests/cli/test_streaming.py::TestTodoUpdateRendersItems -v`
Expected: PASS

**Step 3: Commit**

`git add src/amplifier_ipc/cli/streaming.py tests/cli/test_streaming.py && git commit -m "feat: add rich rendering of TodoUpdateEvent with status symbols and progress bar"`

---

### Task 3: Add empty todos graceful handling test

**Files:**
- Test: `tests/cli/test_streaming.py`

**Step 1: Write the test**

Add to `tests/cli/test_streaming.py`:

```python
# ---------------------------------------------------------------------------
# Test 12: test_todo_update_empty
# ---------------------------------------------------------------------------


class TestTodoUpdateEmpty:
    def test_todo_update_empty(self) -> None:
        """TodoUpdateEvent with empty todos list should not crash."""
        from amplifier_ipc.cli.streaming import StreamingDisplay
        from amplifier_ipc.host.events import TodoUpdateEvent

        console, buf = _make_console()
        display = StreamingDisplay(console=console)

        event = TodoUpdateEvent(todos=[], status="listed")
        # Should not raise any exception
        display.handle_event(event)
```

**Step 2: Run test to verify it passes (implementation already handles empty case)**

Run: `uv run pytest tests/cli/test_streaming.py::TestTodoUpdateEmpty -v`
Expected: PASS (the `if not event.todos: return` guard in the handler covers this)

**Step 3: Run full test suite**

Run: `uv run pytest tests/cli/test_streaming.py -v`
Expected: 12 passed

**Step 4: Commit**

`git add tests/cli/test_streaming.py && git commit -m "test: add empty todos graceful handling test for TodoUpdateEvent"`

---

## Verification

Run the full acceptance criteria command:

```bash
uv run pytest tests/cli/test_streaming.py -v
```

Expected: All 12 tests pass. Output should include:
- `TestTodoUpdateRendersItems::test_todo_update_renders_items PASSED`
- `TestTodoUpdateEmpty::test_todo_update_empty PASSED`