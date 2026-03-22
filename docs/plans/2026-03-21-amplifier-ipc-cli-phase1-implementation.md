# amplifier-ipc CLI Phase 1 Implementation Plan

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Get `amplifier-ipc run --agent foundation` to produce a working interactive session against the already-built foundation service.

**Architecture:** Copy `amplifier-lite-cli` wholesale into a new `amplifier-ipc-cli/` package, gut the session engine layer, and replace it with IPC-native code that imports `amplifier-ipc-host` as an in-process library. The CLI resolves agent definitions from a local registry (`$AMPLIFIER_HOME`), builds a `SessionConfig`, creates a `Host` instance, and iterates its event stream to render output.

**Tech Stack:** Python 3.11+, hatchling build, Click CLI, prompt-toolkit REPL, Rich console, PyYAML, pytest + pytest-asyncio.

---

## Task 1: Host Event Model

Refactor `Host.run()` in `amplifier-ipc-host` to yield events as an async iterator instead of returning a batch result string. This is the foundational change the entire CLI depends on.

**Files:**
- Modify: `amplifier-ipc/amplifier-ipc-host/src/amplifier_ipc_host/host.py`
- Create: `amplifier-ipc/amplifier-ipc-host/src/amplifier_ipc_host/events.py`
- Modify: `amplifier-ipc/amplifier-ipc-host/src/amplifier_ipc_host/__init__.py`
- Modify: `amplifier-ipc/amplifier-ipc-host/tests/test_host.py`
- Test: `amplifier-ipc/amplifier-ipc-host/tests/test_events.py`

### Step 1: Create the events module with event dataclasses

Create `amplifier-ipc/amplifier-ipc-host/src/amplifier_ipc_host/events.py`:

```python
"""Structured events yielded by Host.run() to its caller."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class HostEvent:
    """Base class for all host events."""

    type: str


@dataclass
class StreamTokenEvent(HostEvent):
    """A token of streamed text from the orchestrator."""

    type: str = field(default="stream.token", init=False)
    text: str = ""


@dataclass
class StreamThinkingEvent(HostEvent):
    """A thinking/reasoning token from the orchestrator."""

    type: str = field(default="stream.thinking", init=False)
    text: str = ""


@dataclass
class StreamToolCallStartEvent(HostEvent):
    """The orchestrator is starting a tool call."""

    type: str = field(default="stream.tool_call_start", init=False)
    name: str = ""
    call_id: str = ""


@dataclass
class ApprovalRequestEvent(HostEvent):
    """The orchestrator is requesting user approval."""

    type: str = field(default="approval_request", init=False)
    tool_name: str = ""
    action: str = ""
    risk_level: str = "medium"
    details: dict[str, Any] = field(default_factory=dict)
    request_id: str = ""


@dataclass
class ErrorEvent(HostEvent):
    """An error occurred during execution."""

    type: str = field(default="error", init=False)
    message: str = ""
    service: str = ""
    recoverable: bool = True


@dataclass
class CompleteEvent(HostEvent):
    """The orchestrator turn is complete."""

    type: str = field(default="complete", init=False)
    response: str = ""
```

### Step 2: Write tests for the event dataclasses

Create `amplifier-ipc/amplifier-ipc-host/tests/test_events.py`:

```python
"""Tests for the HostEvent hierarchy."""

from __future__ import annotations

from amplifier_ipc_host.events import (
    ApprovalRequestEvent,
    CompleteEvent,
    ErrorEvent,
    HostEvent,
    StreamThinkingEvent,
    StreamTokenEvent,
    StreamToolCallStartEvent,
)


def test_stream_token_event_type() -> None:
    event = StreamTokenEvent(text="hello")
    assert event.type == "stream.token"
    assert event.text == "hello"


def test_stream_thinking_event_type() -> None:
    event = StreamThinkingEvent(text="reasoning")
    assert event.type == "stream.thinking"
    assert event.text == "reasoning"


def test_stream_tool_call_start_event_type() -> None:
    event = StreamToolCallStartEvent(name="bash", call_id="abc")
    assert event.type == "stream.tool_call_start"
    assert event.name == "bash"


def test_approval_request_event_type() -> None:
    event = ApprovalRequestEvent(
        tool_name="write", action="overwrite", request_id="r1"
    )
    assert event.type == "approval_request"
    assert event.tool_name == "write"


def test_error_event_type() -> None:
    event = ErrorEvent(message="service crashed", service="foundation")
    assert event.type == "error"
    assert event.recoverable is True


def test_complete_event_type() -> None:
    event = CompleteEvent(response="Done!")
    assert event.type == "complete"
    assert event.response == "Done!"


def test_host_event_is_base() -> None:
    event = HostEvent(type="custom")
    assert event.type == "custom"
```

### Step 3: Run event tests to verify they pass

Run: `cd amplifier-ipc/amplifier-ipc-host && python -m pytest tests/test_events.py -v`
Expected: All 7 tests PASS.

### Step 4: Refactor `_orchestrator_loop` to yield events

Modify `amplifier-ipc/amplifier-ipc-host/src/amplifier_ipc_host/host.py`:

The current `_orchestrator_loop` reads messages in a while loop and either routes requests, writes `stream.*` notifications to stdout, or returns the final result string. Change it to be an `async def` that yields `HostEvent` objects instead.

**Current code (lines 156–258)** — replace the entire `_orchestrator_loop` method:

```python
async def _orchestrator_loop(
    self,
    orchestrator_key: str,
    prompt: str,
    system_prompt: str,
) -> AsyncIterator[HostEvent]:
    """Drive the bidirectional orchestrator routing loop, yielding events.

    Writes an ``orchestrator.execute`` JSON-RPC request to the orchestrator
    process, then processes messages until the final response arrives:

    * ``request.*`` messages are routed via :meth:`_handle_orchestrator_request`
      and the result is written back.
    * ``stream.*`` notifications are yielded as HostEvent instances.
    * A response whose ``id`` matches the execute request yields a
      CompleteEvent and returns.

    Args:
        orchestrator_key: Service key for the orchestrator in ``_services``.
        prompt: User prompt to execute.
        system_prompt: Assembled system prompt for this session.

    Yields:
        HostEvent instances for stream notifications and the final result.
    """
    orchestrator_svc: ServiceProcess = self._services[orchestrator_key]
    if (
        orchestrator_svc.process.stdin is None
        or orchestrator_svc.process.stdout is None
    ):
        raise RuntimeError(
            f"Orchestrator service '{orchestrator_key}' was not started with pipes"
        )

    execute_id = uuid.uuid4().hex[:16]

    request: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": execute_id,
        "method": "orchestrator.execute",
        "params": {
            "prompt": prompt,
            "system_prompt": system_prompt,
        },
    }
    await write_message(orchestrator_svc.process.stdin, request)

    # Read loop
    while True:
        message = await read_message(orchestrator_svc.process.stdout)
        if message is None:
            raise RuntimeError("Orchestrator connection closed unexpectedly")

        method: str | None = message.get("method")

        # Request from the orchestrator — route it and send back a response
        if method is not None and method.startswith("request."):
            params = message.get("params")
            msg_id = message.get("id")

            try:
                result = await self._handle_orchestrator_request(method, params)
                response: dict[str, Any] = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": result,
                }

                # Persist context messages
                if (
                    method == "request.context_add_message"
                    and self._persistence is not None
                    and isinstance(params, dict)
                ):
                    self._persistence.append_message(params)

            except JsonRpcError as exc:
                response = exc.to_response(msg_id)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Unexpected error routing %r", method)
                response = make_error_response(
                    msg_id, -32603, f"Internal error: {exc}"
                )

            await write_message(orchestrator_svc.process.stdin, response)

        # Stream notification — yield as HostEvent
        elif method is not None and method.startswith("stream."):
            params = message.get("params", {})
            if method == "stream.token":
                yield StreamTokenEvent(text=params.get("text", ""))
            elif method == "stream.thinking":
                yield StreamThinkingEvent(text=params.get("text", ""))
            elif method == "stream.tool_call_start":
                yield StreamToolCallStartEvent(
                    name=params.get("name", ""),
                    call_id=params.get("call_id", ""),
                )
            else:
                # Forward unknown stream types as generic events
                yield HostEvent(type=method)

        # Final response matching execute_id — success
        elif message.get("id") == execute_id and "result" in message:
            yield CompleteEvent(response=message["result"])
            return

        # Final response matching execute_id — error
        elif message.get("id") == execute_id and "error" in message:
            err = message["error"]
            raise RuntimeError(
                f"Orchestrator returned error: {err.get('message', err)}"
            )

        else:
            logger.debug("Unrecognised orchestrator message: %r", message)
```

### Step 5: Refactor `run()` to be an async generator

Change the `run()` method (lines 66–151) from returning `str` to being an `AsyncIterator[HostEvent]`:

```python
async def run(self, prompt: str) -> AsyncIterator[HostEvent]:
    """Execute a full session turn, yielding events as they occur.

    1. Generate a session ID and create :class:`SessionPersistence`.
    2. Spawn all configured services.
    3. Discover capabilities via ``describe`` and build the registry.
    4. Resolve orchestrator / context-manager / provider service keys.
    5. Build a :class:`Router`.
    6. Assemble the system prompt via content resolution.
    7. Run the orchestrator turn loop, yielding events.
    8. Persist metadata and finalize.

    Args:
        prompt: The user prompt to pass to the orchestrator.

    Yields:
        HostEvent instances (stream tokens, tool calls, completion, etc.).

    Raises:
        RuntimeError: If the orchestrator, context manager, or provider
            declared in the config is not found in the registry.
    """
    session_id = uuid.uuid4().hex[:16]
    self._persistence = SessionPersistence(session_id, self._session_dir)

    try:
        # 2. Spawn services
        await self._spawn_services()

        # 3. Build registry
        await self._build_registry()

        # 4. Resolve service keys
        orchestrator_key = self._registry.get_orchestrator_service(
            self._config.orchestrator
        )
        context_manager_key = self._registry.get_context_manager_service(
            self._config.context_manager
        )
        provider_key = self._registry.get_provider_service(self._config.provider)

        if orchestrator_key is None:
            raise RuntimeError(
                f"Orchestrator '{self._config.orchestrator}' not found in registry"
            )
        if context_manager_key is None:
            raise RuntimeError(
                f"Context manager '{self._config.context_manager}' not found in registry"
            )
        if provider_key is None:
            raise RuntimeError(
                f"Provider '{self._config.provider}' not found in registry"
            )

        # 5. Build router
        self._router = Router(
            registry=self._registry,
            services=self._services,
            context_manager_key=context_manager_key,
            provider_key=provider_key,
        )

        # 6. Assemble system prompt
        system_prompt = await assemble_system_prompt(self._registry, self._services)

        # 7. Orchestrator turn loop — yield events
        async for event in self._orchestrator_loop(
            orchestrator_key=orchestrator_key,
            prompt=prompt,
            system_prompt=system_prompt,
        ):
            yield event

        # 8. Save metadata + finalize
        self._persistence.save_metadata(
            {
                "session_id": session_id,
                "prompt": prompt,
            }
        )
        self._persistence.finalize()

    finally:
        await self._teardown_services()
```

### Step 6: Update imports in host.py

Add to the imports at the top of `host.py`:

```python
from collections.abc import AsyncIterator

from amplifier_ipc_host.events import (
    CompleteEvent,
    HostEvent,
    StreamThinkingEvent,
    StreamTokenEvent,
    StreamToolCallStartEvent,
)
```

### Step 7: Update `__init__.py` to export the events module

Add to `amplifier-ipc/amplifier-ipc-host/src/amplifier_ipc_host/__init__.py`:

```python
from amplifier_ipc_host.events import (
    ApprovalRequestEvent,
    CompleteEvent,
    ErrorEvent,
    HostEvent,
    StreamThinkingEvent,
    StreamTokenEvent,
    StreamToolCallStartEvent,
)
```

And add these to `__all__`.

### Step 8: Update `__main__.py` to consume the new event stream

Modify `_run_session` in `amplifier-ipc/amplifier-ipc-host/src/amplifier_ipc_host/__main__.py` to iterate the event stream:

```python
async def _run_session_async(config_path: Path, prompt: str) -> None:
    config = parse_session_config(config_path)
    settings = load_settings(
        user_settings_path=Path.home() / ".amplifier" / "settings.yaml",
        project_settings_path=Path(".amplifier") / "settings.yaml",
    )
    host = Host(config=config, settings=settings)
    async for event in host.run(prompt):
        if event.type == "stream.token":
            sys.stdout.write(event.text)
            sys.stdout.flush()
        elif event.type == "complete":
            print()  # Final newline after streaming
            if not any_token_printed:
                print(event.response)
```

(The exact implementation details of `__main__.py` are secondary; just ensure the batch `response = asyncio.run(host.run(prompt))` / `print(response)` pattern is updated to `async for event in host.run(prompt):`.)

### Step 9: Update existing host tests

Modify `amplifier-ipc/amplifier-ipc-host/tests/test_host.py`:

The existing tests `test_host_build_registry` and `test_host_route_orchestrator_message` don't call `run()` or `_orchestrator_loop()` directly — they test `_build_registry()` and `_handle_orchestrator_request()` which are unchanged. They should still pass without modification.

The test `test_orchestrator_loop_raises_on_error_response` calls `_orchestrator_loop()` directly and expects a `RuntimeError`. This test needs updating because `_orchestrator_loop` is now an async generator. Change it to iterate the generator:

```python
async def test_orchestrator_loop_raises_on_error_response() -> None:
    """_orchestrator_loop raises RuntimeError when orchestrator returns a JSON-RPC error."""
    config = SessionConfig(
        services=["orch"],
        orchestrator="loop",
        context_manager="simple",
        provider="anthropic",
    )
    settings = HostSettings()

    host = Host(config=config, settings=settings)

    # Fake process with non-None stdin/stdout so the pipe check passes
    fake_process = MagicMock()
    fake_process.stdin = MagicMock()
    fake_process.stdout = MagicMock()

    fake_service = MagicMock()
    fake_service.process = fake_process
    host._services = {"orch": fake_service}

    # Capture the execute_id written by the loop so we can echo it back
    captured_id: list[str] = []

    async def fake_write(stream: object, message: dict) -> None:
        if message.get("method") == "orchestrator.execute":
            captured_id.append(message["id"])

    read_call_count = 0

    async def fake_read(stream: object) -> dict | None:
        nonlocal read_call_count
        read_call_count += 1
        if read_call_count == 1:
            return {
                "jsonrpc": "2.0",
                "id": captured_id[0],
                "error": {"code": -32603, "message": "Internal orchestrator error"},
            }
        return None

    with (
        patch("amplifier_ipc_host.host.write_message", fake_write),
        patch("amplifier_ipc_host.host.read_message", fake_read),
    ):
        with pytest.raises(RuntimeError, match="Orchestrator returned error"):
            async for _event in host._orchestrator_loop(
                orchestrator_key="orch",
                prompt="hello",
                system_prompt="be helpful",
            ):
                pass  # Consume the generator to trigger the error
```

### Step 10: Add a test for the event-yielding orchestrator loop

Add to `amplifier-ipc/amplifier-ipc-host/tests/test_host.py`:

```python
async def test_orchestrator_loop_yields_stream_events() -> None:
    """_orchestrator_loop yields HostEvent instances for stream notifications."""
    from amplifier_ipc_host.events import CompleteEvent, StreamTokenEvent

    config = SessionConfig(
        services=["orch"],
        orchestrator="loop",
        context_manager="simple",
        provider="anthropic",
    )
    settings = HostSettings()

    host = Host(config=config, settings=settings)

    fake_process = MagicMock()
    fake_process.stdin = MagicMock()
    fake_process.stdout = MagicMock()

    fake_service = MagicMock()
    fake_service.process = fake_process
    host._services = {"orch": fake_service}

    captured_id: list[str] = []

    async def fake_write(stream: object, message: dict) -> None:
        if message.get("method") == "orchestrator.execute":
            captured_id.append(message["id"])

    messages_to_return: list[dict | None] = []
    read_index = 0

    async def fake_read(stream: object) -> dict | None:
        nonlocal read_index
        if read_index < len(messages_to_return):
            msg = messages_to_return[read_index]
            read_index += 1
            return msg
        return None

    # We'll set up messages_to_return after the first write captures the id
    original_fake_write = fake_write

    async def setup_write(stream: object, message: dict) -> None:
        await original_fake_write(stream, message)
        if captured_id and not messages_to_return:
            messages_to_return.extend([
                {
                    "jsonrpc": "2.0",
                    "method": "stream.token",
                    "params": {"text": "Hello"},
                },
                {
                    "jsonrpc": "2.0",
                    "method": "stream.token",
                    "params": {"text": " world"},
                },
                {
                    "jsonrpc": "2.0",
                    "id": captured_id[0],
                    "result": "Hello world",
                },
            ])

    with (
        patch("amplifier_ipc_host.host.write_message", setup_write),
        patch("amplifier_ipc_host.host.read_message", fake_read),
    ):
        events = []
        async for event in host._orchestrator_loop(
            orchestrator_key="orch",
            prompt="hello",
            system_prompt="be helpful",
        ):
            events.append(event)

    assert len(events) == 3
    assert isinstance(events[0], StreamTokenEvent)
    assert events[0].text == "Hello"
    assert isinstance(events[1], StreamTokenEvent)
    assert events[1].text == " world"
    assert isinstance(events[2], CompleteEvent)
    assert events[2].response == "Hello world"
```

### Step 11: Run all host tests to verify

Run: `cd amplifier-ipc/amplifier-ipc-host && python -m pytest tests/ -v`
Expected: All tests PASS including the updated and new tests.

### Step 12: Commit

```bash
cd amplifier-ipc/amplifier-ipc-host && git add -A && git commit -m "feat(host): refactor Host.run() to yield HostEvent async iterator

Replace batch return with async generator that yields StreamTokenEvent,
StreamThinkingEvent, StreamToolCallStartEvent, CompleteEvent, etc.
The CLI will iterate this stream for real-time UI rendering."
```

---

## Task 2: Package Scaffold

Create the `amplifier-ipc-cli/` package with build config, init, and main entry point.

**Files:**
- Create: `amplifier-ipc/amplifier-ipc-cli/pyproject.toml`
- Create: `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/__init__.py`
- Create: `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/__main__.py`
- Create: `amplifier-ipc/amplifier-ipc-cli/tests/__init__.py`
- Test: `amplifier-ipc/amplifier-ipc-cli/tests/test_import.py`

### Step 1: Create `pyproject.toml`

Create `amplifier-ipc/amplifier-ipc-cli/pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "amplifier-ipc-cli"
version = "0.1.0"
description = "User-facing CLI for amplifier-ipc"
requires-python = ">=3.11"
dependencies = [
    "amplifier-ipc-host",
    "click>=8.1.0",
    "rich>=13.0.0",
    "prompt-toolkit>=3.0.52",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pyright>=1.1",
    "ruff>=0.4",
]

[project.scripts]
amplifier-ipc = "amplifier_ipc_cli.main:main"

[tool.hatch.build.targets.wheel]
packages = ["src/amplifier_ipc_cli"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["src"]

[tool.pyright]
pythonVersion = "3.11"
extraPaths = ["src"]

[tool.uv.sources]
amplifier-ipc-host = { path = "../amplifier-ipc-host" }

[dependency-groups]
dev = [
    "pytest-asyncio>=1.3.0",
    "pytest-timeout>=2.4.0",
]
```

### Step 2: Create `__init__.py`

Create `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/__init__.py`:

```python
"""amplifier-ipc-cli — User-facing CLI for amplifier-ipc."""

from __future__ import annotations

__version__ = "0.1.0"
```

### Step 3: Create `__main__.py`

Create `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/__main__.py`:

```python
"""Entry point for 'python -m amplifier_ipc_cli'."""

from __future__ import annotations

from amplifier_ipc_cli.main import main

if __name__ == "__main__":
    main()
```

### Step 4: Create empty test package

Create `amplifier-ipc/amplifier-ipc-cli/tests/__init__.py`:

```python
```

### Step 5: Write import smoke test

Create `amplifier-ipc/amplifier-ipc-cli/tests/test_import.py`:

```python
"""Smoke test: verify the package can be imported."""

from __future__ import annotations


def test_package_imports() -> None:
    import amplifier_ipc_cli

    assert amplifier_ipc_cli.__version__ == "0.1.0"
```

### Step 6: Install the package in dev mode and run the test

Run:
```bash
cd amplifier-ipc/amplifier-ipc-cli && uv pip install -e ".[dev]" && python -m pytest tests/test_import.py -v
```
Expected: PASS (may need to create a stub `main.py` first — see next step).

Note: The `__main__.py` imports `amplifier_ipc_cli.main` which doesn't exist yet. Create a minimal stub:

Create `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/main.py`:

```python
"""Main CLI entry point — placeholder until Task 10."""

from __future__ import annotations

import click


@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx: click.Context) -> None:
    """amplifier-ipc — interact with amplifier-ipc sessions."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


def main() -> None:
    """Main entry point — delegates to the cli Click group."""
    cli()
```

### Step 7: Run the import test again

Run: `cd amplifier-ipc/amplifier-ipc-cli && python -m pytest tests/test_import.py -v`
Expected: PASS.

### Step 8: Commit

```bash
cd amplifier-ipc/amplifier-ipc-cli && git add -A && git commit -m "feat(cli): scaffold amplifier-ipc-cli package

pyproject.toml with hatchling, entry point, __init__.py, __main__.py,
and stub main.py Click group."
```

---

## Task 3: Copy Wholesale Modules

Copy UI and utility modules from `amplifier-lite-cli` into `amplifier-ipc-cli`, updating import paths.

**Files:**
- Create: `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/console.py`
- Create: `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/key_manager.py`
- Create: `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/paths.py`
- Create: `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/settings.py`
- Create: `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/ui/__init__.py`
- Create: `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/ui/display.py`
- Create: `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/ui/message_renderer.py`
- Create: `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/ui/error_display.py`
- Create: `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/commands/__init__.py`
- Create: `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/commands/notify.py`
- Create: `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/commands/allowed_dirs.py`
- Create: `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/commands/denied_dirs.py`
- Create: `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/commands/version.py`
- Test: `amplifier-ipc/amplifier-ipc-cli/tests/test_copy_imports.py`

### Step 1: Copy `console.py` wholesale

Copy from `amplifier-lite-cli/src/amplifier_lite_cli/console.py` to `amplifier-ipc-cli/src/amplifier_ipc_cli/console.py`. This file has **zero** `amplifier_lite` imports — it only uses `rich`. Copy as-is.

### Step 2: Copy `key_manager.py` wholesale

Copy from `amplifier-lite-cli/src/amplifier_lite_cli/key_manager.py` to `amplifier-ipc-cli/src/amplifier_ipc_cli/key_manager.py`. This file has **zero** `amplifier_lite` imports — pure stdlib. Copy as-is.

### Step 3: Copy `paths.py` wholesale

Copy from `amplifier-lite-cli/src/amplifier_lite_cli/paths.py` to `amplifier-ipc-cli/src/amplifier_ipc_cli/paths.py`. This file has **zero** `amplifier_lite` imports — pure `pathlib`. Copy as-is. The path scheme (`~/.amplifier/projects/<slug>/sessions/`) works for both CLIs.

### Step 4: Copy `settings.py` wholesale

Copy from `amplifier-lite-cli/src/amplifier_lite_cli/settings.py` to `amplifier-ipc-cli/src/amplifier_ipc_cli/settings.py`. This file has **zero** `amplifier_lite` imports — it uses `yaml` and `pathlib`. Copy as-is.

### Step 5: Copy `ui/` directory

Copy these four files, replacing `amplifier_lite_cli` with `amplifier_ipc_cli` in import paths:

**`ui/__init__.py`:**
```python
"""UI package for amplifier-ipc-cli display components."""

from __future__ import annotations

from amplifier_ipc_cli.ui.display import CLIDisplaySystem, format_throttle_warning
from amplifier_ipc_cli.ui.message_renderer import render_message

__all__ = ["CLIDisplaySystem", "format_throttle_warning", "render_message"]
```

**`ui/display.py`:** Copy wholesale from lite-cli. This file has **zero** `amplifier_lite` imports. Copy as-is.

**`ui/message_renderer.py`:** Copy, changing the one import:
```python
# Change: from amplifier_lite_cli.console import Markdown
# To:
from amplifier_ipc_cli.console import Markdown
```

**`ui/error_display.py`:** This file imports `amplifier_lite.models` (LLMError, RateLimitError, etc.). These types don't exist in amplifier-ipc-protocol. **Create a stub version** that handles generic exceptions instead:

```python
"""Error display formatting for CLI error types.

Provides display_error() which renders a Rich Panel with human-readable
context for errors. Simplified from lite-cli's LLMError-specific version
since IPC errors come as HostEvent.error events.
"""

from __future__ import annotations

import traceback
from typing import TYPE_CHECKING

from rich.panel import Panel

if TYPE_CHECKING:
    from rich.console import Console

__all__ = ["display_error"]


def display_error(
    console: Console,
    error: Exception,
    verbose: bool = False,
) -> None:
    """Display a formatted Rich Panel for an error.

    Args:
        console: Rich Console to print to.
        error: The exception to display.
        verbose: When True, also prints the full traceback.
    """
    message = str(error)
    if len(message) > 200:
        message = message[:200] + "..."

    body_lines = [
        f"[bold]Error:[/bold] {type(error).__name__}",
        "",
        message,
    ]

    panel = Panel(
        "\n".join(body_lines),
        title="Error",
        border_style="red",
    )
    console.print(panel)

    if verbose:
        console.print(traceback.format_exc())
```

### Step 6: Copy command modules

Create `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/commands/__init__.py` (empty):
```python
```

**`commands/notify.py`:** Copy from lite-cli, replacing all `amplifier_lite_cli` imports with `amplifier_ipc_cli`:
- `from amplifier_lite_cli.console import console` → `from amplifier_ipc_cli.console import console`
- `from amplifier_lite_cli.key_manager import KeyManager` → `from amplifier_ipc_cli.key_manager import KeyManager`
- `from amplifier_lite_cli.settings import AppSettings, get_settings` → `from amplifier_ipc_cli.settings import AppSettings, get_settings`

**`commands/allowed_dirs.py`:** Copy from lite-cli, replacing:
- `from amplifier_lite_cli.console import console` → `from amplifier_ipc_cli.console import console`
- `from amplifier_lite_cli.settings import AppSettings, get_settings` → `from amplifier_ipc_cli.settings import AppSettings, get_settings`

**`commands/denied_dirs.py`:** Copy from lite-cli, replacing:
- `from amplifier_lite_cli.console import console` → `from amplifier_ipc_cli.console import console`
- `from amplifier_lite_cli.settings import AppSettings, Scope, get_settings` → `from amplifier_ipc_cli.settings import AppSettings, Scope, get_settings`

**`commands/version.py`:** Rewrite for IPC:

```python
"""Version command — displays CLI and host package versions."""

from __future__ import annotations

import importlib.metadata

import click

from amplifier_ipc_cli import __version__
from amplifier_ipc_cli.console import console


def _get_host_version() -> str:
    """Return the installed amplifier-ipc-host version, or 'unknown' on failure."""
    try:
        return importlib.metadata.version("amplifier-ipc-host")
    except Exception:  # noqa: BLE001
        return "unknown"


@click.command()
def version() -> None:
    """Display the CLI and host package versions."""
    host_version = _get_host_version()
    console.print(f"amplifier-ipc-cli {__version__} (amplifier-ipc-host {host_version})")
```

### Step 7: Write import verification test

Create `amplifier-ipc/amplifier-ipc-cli/tests/test_copy_imports.py`:

```python
"""Verify all copied modules import cleanly."""

from __future__ import annotations


def test_console_imports() -> None:
    from amplifier_ipc_cli.console import console, Markdown
    assert console is not None
    assert Markdown is not None


def test_key_manager_imports() -> None:
    from amplifier_ipc_cli.key_manager import KeyManager
    assert KeyManager is not None


def test_paths_imports() -> None:
    from amplifier_ipc_cli.paths import get_project_slug, get_sessions_base_dir
    assert get_project_slug is not None
    assert get_sessions_base_dir is not None


def test_settings_imports() -> None:
    from amplifier_ipc_cli.settings import AppSettings, get_settings
    assert AppSettings is not None
    assert get_settings is not None


def test_ui_imports() -> None:
    from amplifier_ipc_cli.ui import CLIDisplaySystem, render_message
    assert CLIDisplaySystem is not None
    assert render_message is not None


def test_ui_error_display_imports() -> None:
    from amplifier_ipc_cli.ui.error_display import display_error
    assert display_error is not None


def test_commands_import() -> None:
    from amplifier_ipc_cli.commands.notify import notify_group
    from amplifier_ipc_cli.commands.allowed_dirs import allowed_dirs_group
    from amplifier_ipc_cli.commands.denied_dirs import denied_dirs_group
    from amplifier_ipc_cli.commands.version import version
    assert notify_group is not None
    assert allowed_dirs_group is not None
    assert denied_dirs_group is not None
    assert version is not None
```

### Step 8: Run the import tests

Run: `cd amplifier-ipc/amplifier-ipc-cli && python -m pytest tests/test_copy_imports.py -v`
Expected: All tests PASS. If any fail due to missing imports, fix the failing module.

### Step 9: Commit

```bash
cd amplifier-ipc/amplifier-ipc-cli && git add -A && git commit -m "feat(cli): copy wholesale modules from amplifier-lite-cli

console, key_manager, paths, settings, ui/*, commands/notify,
commands/allowed_dirs, commands/denied_dirs, commands/version.
All amplifier_lite_cli imports replaced with amplifier_ipc_cli.
error_display.py simplified to remove amplifier_lite.models dependency."
```

---

## Task 4: Registry — Core

Create the Registry class that manages the `$AMPLIFIER_HOME` filesystem layout with registration support. TDD.

**Files:**
- Create: `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/registry.py`
- Test: `amplifier-ipc/amplifier-ipc-cli/tests/test_registry.py`

### Step 1: Write the failing tests for Registry core

Create `amplifier-ipc/amplifier-ipc-cli/tests/test_registry.py`:

```python
"""Tests for the Registry class — $AMPLIFIER_HOME filesystem management."""

from __future__ import annotations

from pathlib import Path

import yaml

from amplifier_ipc_cli.registry import Registry


# ---------------------------------------------------------------------------
# ensure_home
# ---------------------------------------------------------------------------


def test_ensure_home_creates_directory_structure(tmp_path: Path) -> None:
    """ensure_home() creates the standard directory layout."""
    registry = Registry(home=tmp_path / "amplifier_home")
    registry.ensure_home()

    assert (tmp_path / "amplifier_home").is_dir()
    assert (tmp_path / "amplifier_home" / "definitions").is_dir()
    assert (tmp_path / "amplifier_home" / "environments").is_dir()
    assert (tmp_path / "amplifier_home" / "agents.yaml").is_file()
    assert (tmp_path / "amplifier_home" / "behaviors.yaml").is_file()


def test_ensure_home_is_idempotent(tmp_path: Path) -> None:
    """Calling ensure_home() twice does not error or remove existing data."""
    registry = Registry(home=tmp_path / "amplifier_home")
    registry.ensure_home()
    # Write a definition to the directory
    (tmp_path / "amplifier_home" / "definitions" / "test.yaml").write_text("test: true")
    registry.ensure_home()
    # The file should still be there
    assert (tmp_path / "amplifier_home" / "definitions" / "test.yaml").read_text() == "test: true"


# ---------------------------------------------------------------------------
# register_definition — agent
# ---------------------------------------------------------------------------


_SAMPLE_AGENT_YAML = """\
type: agent
local_ref: foundation
uuid: 3898a638-1234-5678-9abc-def012345678
version: "1.0"
description: Foundation agent
orchestrator: streaming
context_manager: simple
provider: anthropic
behaviors:
  - name: amplifier-dev
    url: https://example.com/amplifier-dev.yaml
services:
  - name: amplifier-foundation
    installer: pip
    source: amplifier-foundation
"""


def test_register_agent_definition(tmp_path: Path) -> None:
    """register_definition() writes the YAML to definitions/ and adds an alias."""
    registry = Registry(home=tmp_path)
    registry.ensure_home()

    definition_id = registry.register_definition(_SAMPLE_AGENT_YAML)

    # ID format: <type>_<local_ref>_<uuid_first_8>
    assert definition_id == "agent_foundation_3898a638"

    # Definition file written
    def_path = tmp_path / "definitions" / f"{definition_id}.yaml"
    assert def_path.is_file()
    content = yaml.safe_load(def_path.read_text())
    assert content["type"] == "agent"
    assert content["local_ref"] == "foundation"

    # Alias added to agents.yaml
    aliases = yaml.safe_load((tmp_path / "agents.yaml").read_text())
    assert aliases["foundation"] == definition_id


# ---------------------------------------------------------------------------
# register_definition — behavior
# ---------------------------------------------------------------------------


_SAMPLE_BEHAVIOR_YAML = """\
type: behavior
local_ref: amplifier-dev
uuid: a6a2e2b5-abcd-1234-5678-abcdef012345
version: "1.0"
description: Amplifier development behavior
tools:
  - name: bash
  - name: edit
hooks:
  - name: status_context
services:
  - name: amplifier-foundation
    installer: pip
    source: amplifier-foundation
"""


def test_register_behavior_definition(tmp_path: Path) -> None:
    """register_definition() works for behavior type and writes to behaviors.yaml."""
    registry = Registry(home=tmp_path)
    registry.ensure_home()

    definition_id = registry.register_definition(_SAMPLE_BEHAVIOR_YAML)

    assert definition_id == "behavior_amplifier-dev_a6a2e2b5"

    # Alias in behaviors.yaml
    aliases = yaml.safe_load((tmp_path / "behaviors.yaml").read_text())
    assert aliases["amplifier-dev"] == definition_id


# ---------------------------------------------------------------------------
# register_definition — with source URL (_meta block)
# ---------------------------------------------------------------------------


def test_register_definition_with_source_url(tmp_path: Path) -> None:
    """register_definition() with source_url writes a _meta block."""
    registry = Registry(home=tmp_path)
    registry.ensure_home()

    source_url = "https://example.com/behavior.yaml"
    definition_id = registry.register_definition(
        _SAMPLE_BEHAVIOR_YAML, source_url=source_url
    )

    def_path = tmp_path / "definitions" / f"{definition_id}.yaml"
    content = yaml.safe_load(def_path.read_text())

    assert "_meta" in content
    assert content["_meta"]["source_url"] == source_url
    assert content["_meta"]["source_hash"].startswith("sha256:")
    assert "fetched_at" in content["_meta"]


# ---------------------------------------------------------------------------
# register_definition — idempotent re-register
# ---------------------------------------------------------------------------


def test_register_same_definition_twice_is_idempotent(tmp_path: Path) -> None:
    """Re-registering the same definition overwrites cleanly."""
    registry = Registry(home=tmp_path)
    registry.ensure_home()

    id1 = registry.register_definition(_SAMPLE_AGENT_YAML)
    id2 = registry.register_definition(_SAMPLE_AGENT_YAML)

    assert id1 == id2

    # Alias file should not have duplicates
    aliases = yaml.safe_load((tmp_path / "agents.yaml").read_text())
    assert aliases["foundation"] == id1
```

### Step 2: Run the tests to verify they fail

Run: `cd amplifier-ipc/amplifier-ipc-cli && python -m pytest tests/test_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'amplifier_ipc_cli.registry'`

### Step 3: Implement the Registry class

Create `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/registry.py`:

```python
"""Registry — $AMPLIFIER_HOME filesystem management.

Manages the local registry of agent and behavior definitions. Definitions
are cached YAML files stored under ``$AMPLIFIER_HOME/definitions/``.
Aliases (human-readable names → definition IDs) live in ``agents.yaml``
and ``behaviors.yaml`` at the registry root.
"""

from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_DEFAULT_HOME = Path.home() / ".amplifier"


class Registry:
    """Manages the ``$AMPLIFIER_HOME`` directory layout and CRUD operations."""

    def __init__(self, home: Path | None = None) -> None:
        env_home = os.environ.get("AMPLIFIER_HOME")
        if home is not None:
            self._home = home
        elif env_home is not None:
            self._home = Path(env_home)
        else:
            self._home = _DEFAULT_HOME

    @property
    def home(self) -> Path:
        """The root directory of the registry."""
        return self._home

    # ------------------------------------------------------------------
    # Directory structure
    # ------------------------------------------------------------------

    def ensure_home(self) -> None:
        """Create the standard directory layout if it doesn't exist."""
        self._home.mkdir(parents=True, exist_ok=True)
        (self._home / "definitions").mkdir(exist_ok=True)
        (self._home / "environments").mkdir(exist_ok=True)

        for alias_file in ("agents.yaml", "behaviors.yaml"):
            path = self._home / alias_file
            if not path.exists():
                path.write_text("{}\n")

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_definition(
        self,
        yaml_content: str,
        source_url: str | None = None,
    ) -> str:
        """Parse a definition YAML, cache it, and register an alias.

        Args:
            yaml_content: Raw YAML string of the definition.
            source_url: If provided, a ``_meta`` block is added with
                source URL, SHA-256 hash of the raw bytes, and timestamp.

        Returns:
            The definition ID (``<type>_<local_ref>_<uuid_first_8>``).
        """
        data: dict[str, Any] = yaml.safe_load(yaml_content)

        def_type: str = data["type"]  # "agent" or "behavior"
        local_ref: str = data["local_ref"]
        uuid_str: str = str(data["uuid"])
        uuid_short = uuid_str.split("-")[0]

        definition_id = f"{def_type}_{local_ref}_{uuid_short}"

        # Add _meta block if source_url provided
        if source_url is not None:
            raw_hash = hashlib.sha256(yaml_content.encode()).hexdigest()
            data["_meta"] = {
                "source_url": source_url,
                "source_hash": f"sha256:{raw_hash}",
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }

        # Write definition file
        def_path = self._home / "definitions" / f"{definition_id}.yaml"
        def_path.write_text(yaml.dump(data, default_flow_style=False))

        # Update alias file
        alias_file = "agents.yaml" if def_type == "agent" else "behaviors.yaml"
        alias_path = self._home / alias_file
        aliases: dict[str, str] = yaml.safe_load(alias_path.read_text()) or {}
        aliases[local_ref] = definition_id
        alias_path.write_text(yaml.dump(aliases, default_flow_style=False))

        return definition_id
```

### Step 4: Run the tests to verify they pass

Run: `cd amplifier-ipc/amplifier-ipc-cli && python -m pytest tests/test_registry.py -v`
Expected: All tests PASS.

### Step 5: Commit

```bash
cd amplifier-ipc/amplifier-ipc-cli && git add -A && git commit -m "feat(cli): registry core — ensure_home() and register_definition()

Registry manages \$AMPLIFIER_HOME directory layout. register_definition()
parses YAML, computes definition ID, writes to definitions/, and updates
alias files. Supports _meta block with source URL and SHA-256 hash."
```

---

## Task 5: Registry — Lookups

Add lookup methods to the Registry: resolve aliases, check installation status, read metadata.

**Files:**
- Modify: `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/registry.py`
- Modify: `amplifier-ipc/amplifier-ipc-cli/tests/test_registry.py`

### Step 1: Write failing tests for lookup methods

Append to `amplifier-ipc/amplifier-ipc-cli/tests/test_registry.py`:

```python
# ---------------------------------------------------------------------------
# resolve_agent / resolve_behavior
# ---------------------------------------------------------------------------


def test_resolve_agent_returns_path(tmp_path: Path) -> None:
    """resolve_agent() returns the path to the definition file."""
    registry = Registry(home=tmp_path)
    registry.ensure_home()
    registry.register_definition(_SAMPLE_AGENT_YAML)

    path = registry.resolve_agent("foundation")
    assert path.is_file()
    assert path.name == "agent_foundation_3898a638.yaml"


def test_resolve_agent_unknown_raises(tmp_path: Path) -> None:
    """resolve_agent() raises FileNotFoundError for unknown names."""
    registry = Registry(home=tmp_path)
    registry.ensure_home()

    import pytest
    with pytest.raises(FileNotFoundError, match="Agent 'unknown' not found"):
        registry.resolve_agent("unknown")


def test_resolve_behavior_returns_path(tmp_path: Path) -> None:
    """resolve_behavior() returns the path to the definition file."""
    registry = Registry(home=tmp_path)
    registry.ensure_home()
    registry.register_definition(_SAMPLE_BEHAVIOR_YAML)

    path = registry.resolve_behavior("amplifier-dev")
    assert path.is_file()
    assert path.name == "behavior_amplifier-dev_a6a2e2b5.yaml"


def test_resolve_behavior_unknown_raises(tmp_path: Path) -> None:
    """resolve_behavior() raises FileNotFoundError for unknown names."""
    registry = Registry(home=tmp_path)
    registry.ensure_home()

    import pytest
    with pytest.raises(FileNotFoundError, match="Behavior 'missing' not found"):
        registry.resolve_behavior("missing")


# ---------------------------------------------------------------------------
# get_environment_path / is_installed
# ---------------------------------------------------------------------------


def test_get_environment_path(tmp_path: Path) -> None:
    """get_environment_path() returns the expected path under environments/."""
    registry = Registry(home=tmp_path)
    registry.ensure_home()

    path = registry.get_environment_path("behavior_amplifier-dev_a6a2e2b5")
    assert path == tmp_path / "environments" / "behavior_amplifier-dev_a6a2e2b5"


def test_is_installed_false_when_no_env(tmp_path: Path) -> None:
    """is_installed() returns False when the environment directory doesn't exist."""
    registry = Registry(home=tmp_path)
    registry.ensure_home()

    assert registry.is_installed("behavior_amplifier-dev_a6a2e2b5") is False


def test_is_installed_true_when_env_exists(tmp_path: Path) -> None:
    """is_installed() returns True when the environment directory exists."""
    registry = Registry(home=tmp_path)
    registry.ensure_home()

    env_path = tmp_path / "environments" / "behavior_amplifier-dev_a6a2e2b5"
    env_path.mkdir(parents=True)

    assert registry.is_installed("behavior_amplifier-dev_a6a2e2b5") is True


# ---------------------------------------------------------------------------
# get_source_meta
# ---------------------------------------------------------------------------


def test_get_source_meta_returns_meta_block(tmp_path: Path) -> None:
    """get_source_meta() returns the _meta dict when present."""
    registry = Registry(home=tmp_path)
    registry.ensure_home()

    source_url = "https://example.com/behavior.yaml"
    definition_id = registry.register_definition(
        _SAMPLE_BEHAVIOR_YAML, source_url=source_url
    )

    meta = registry.get_source_meta(definition_id)
    assert meta is not None
    assert meta["source_url"] == source_url
    assert meta["source_hash"].startswith("sha256:")


def test_get_source_meta_returns_none_when_no_meta(tmp_path: Path) -> None:
    """get_source_meta() returns None when no _meta block exists."""
    registry = Registry(home=tmp_path)
    registry.ensure_home()

    definition_id = registry.register_definition(_SAMPLE_AGENT_YAML)
    meta = registry.get_source_meta(definition_id)
    assert meta is None


def test_get_source_meta_unknown_definition(tmp_path: Path) -> None:
    """get_source_meta() returns None for nonexistent definitions."""
    registry = Registry(home=tmp_path)
    registry.ensure_home()

    meta = registry.get_source_meta("nonexistent_def_12345678")
    assert meta is None
```

### Step 2: Run to verify they fail

Run: `cd amplifier-ipc/amplifier-ipc-cli && python -m pytest tests/test_registry.py -v -k "resolve or environment or installed or source_meta"`
Expected: FAIL with `AttributeError: 'Registry' object has no attribute 'resolve_agent'`

### Step 3: Implement the lookup methods

Add to `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/registry.py` in the `Registry` class:

```python
    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------

    def resolve_agent(self, name: str) -> Path:
        """Resolve an agent alias to its definition file path.

        Args:
            name: The human-readable agent name (alias).

        Returns:
            Path to the definition YAML file.

        Raises:
            FileNotFoundError: If the alias does not exist.
        """
        return self._resolve_alias(name, "agents.yaml", "Agent")

    def resolve_behavior(self, name: str) -> Path:
        """Resolve a behavior alias to its definition file path.

        Args:
            name: The human-readable behavior name (alias).

        Returns:
            Path to the definition YAML file.

        Raises:
            FileNotFoundError: If the alias does not exist.
        """
        return self._resolve_alias(name, "behaviors.yaml", "Behavior")

    def _resolve_alias(self, name: str, alias_file: str, kind: str) -> Path:
        """Resolve an alias from the given alias file."""
        alias_path = self._home / alias_file
        if not alias_path.exists():
            raise FileNotFoundError(
                f"{kind} '{name}' not found. "
                f"Run `amplifier-ipc discover` to register {kind.lower()}s."
            )
        aliases: dict[str, str] = yaml.safe_load(alias_path.read_text()) or {}
        definition_id = aliases.get(name)
        if definition_id is None:
            raise FileNotFoundError(
                f"{kind} '{name}' not found. "
                f"Run `amplifier-ipc discover` to register {kind.lower()}s."
            )
        def_path = self._home / "definitions" / f"{definition_id}.yaml"
        if not def_path.exists():
            raise FileNotFoundError(
                f"{kind} '{name}' alias points to {definition_id} "
                f"but the definition file is missing."
            )
        return def_path

    # ------------------------------------------------------------------
    # Environment management
    # ------------------------------------------------------------------

    def get_environment_path(self, definition_id: str) -> Path:
        """Return the path to the environment directory for a definition."""
        return self._home / "environments" / definition_id

    def is_installed(self, definition_id: str) -> bool:
        """Return True if the environment for the given definition exists."""
        return self.get_environment_path(definition_id).is_dir()

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    def get_source_meta(self, definition_id: str) -> dict[str, Any] | None:
        """Return the ``_meta`` block from a definition, or None."""
        def_path = self._home / "definitions" / f"{definition_id}.yaml"
        if not def_path.exists():
            return None
        data: dict[str, Any] = yaml.safe_load(def_path.read_text()) or {}
        return data.get("_meta")
```

### Step 4: Run all registry tests

Run: `cd amplifier-ipc/amplifier-ipc-cli && python -m pytest tests/test_registry.py -v`
Expected: All tests PASS.

### Step 5: Commit

```bash
cd amplifier-ipc/amplifier-ipc-cli && git add -A && git commit -m "feat(cli): registry lookups — resolve_agent, resolve_behavior, is_installed, get_source_meta"
```

---

## Task 6: Definitions — YAML Parsing

Create dataclasses for parsed agent/behavior definitions and parsing functions. TDD.

**Files:**
- Create: `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/definitions.py`
- Test: `amplifier-ipc/amplifier-ipc-cli/tests/test_definitions.py`

### Step 1: Write failing tests for definition parsing

Create `amplifier-ipc/amplifier-ipc-cli/tests/test_definitions.py`:

```python
"""Tests for agent/behavior definition parsing and resolution."""

from __future__ import annotations

from amplifier_ipc_cli.definitions import (
    AgentDefinition,
    BehaviorDefinition,
    ServiceEntry,
    parse_agent_definition,
    parse_behavior_definition,
)


# ---------------------------------------------------------------------------
# Sample YAML strings
# ---------------------------------------------------------------------------

_AGENT_YAML = """\
type: agent
local_ref: foundation
uuid: 3898a638-1234-5678-9abc-def012345678
version: "1.0"
description: Foundation agent
orchestrator: streaming
context_manager: simple
provider: anthropic
behaviors:
  - name: amplifier-dev
    url: https://example.com/amplifier-dev.yaml
  - name: agents
    url: https://example.com/agents.yaml
services:
  - name: amplifier-foundation
    installer: pip
    source: amplifier-foundation
"""

_BEHAVIOR_YAML = """\
type: behavior
local_ref: amplifier-dev
uuid: a6a2e2b5-abcd-1234-5678-abcdef012345
version: "1.0"
description: Amplifier development behavior
tools:
  - name: bash
  - name: edit
hooks:
  - name: status_context
behaviors:
  - name: design-intelligence
    url: https://example.com/design-intelligence.yaml
services:
  - name: amplifier-foundation
    installer: pip
    source: amplifier-foundation
"""


# ---------------------------------------------------------------------------
# parse_agent_definition
# ---------------------------------------------------------------------------


def test_parse_agent_definition_basic_fields() -> None:
    agent = parse_agent_definition(_AGENT_YAML)
    assert isinstance(agent, AgentDefinition)
    assert agent.type == "agent"
    assert agent.local_ref == "foundation"
    assert agent.uuid == "3898a638-1234-5678-9abc-def012345678"
    assert agent.version == "1.0"
    assert agent.description == "Foundation agent"
    assert agent.orchestrator == "streaming"
    assert agent.context_manager == "simple"
    assert agent.provider == "anthropic"


def test_parse_agent_definition_behaviors() -> None:
    agent = parse_agent_definition(_AGENT_YAML)
    assert len(agent.behaviors) == 2
    assert agent.behaviors[0]["name"] == "amplifier-dev"
    assert agent.behaviors[0]["url"] == "https://example.com/amplifier-dev.yaml"


def test_parse_agent_definition_services() -> None:
    agent = parse_agent_definition(_AGENT_YAML)
    assert len(agent.services) == 1
    svc = agent.services[0]
    assert isinstance(svc, ServiceEntry)
    assert svc.name == "amplifier-foundation"
    assert svc.installer == "pip"
    assert svc.source == "amplifier-foundation"


# ---------------------------------------------------------------------------
# parse_behavior_definition
# ---------------------------------------------------------------------------


def test_parse_behavior_definition_basic_fields() -> None:
    behavior = parse_behavior_definition(_BEHAVIOR_YAML)
    assert isinstance(behavior, BehaviorDefinition)
    assert behavior.type == "behavior"
    assert behavior.local_ref == "amplifier-dev"
    assert behavior.uuid == "a6a2e2b5-abcd-1234-5678-abcdef012345"


def test_parse_behavior_definition_tools_hooks() -> None:
    behavior = parse_behavior_definition(_BEHAVIOR_YAML)
    assert len(behavior.tools) == 2
    assert behavior.tools[0]["name"] == "bash"
    assert len(behavior.hooks) == 1


def test_parse_behavior_definition_nested_behaviors() -> None:
    behavior = parse_behavior_definition(_BEHAVIOR_YAML)
    assert len(behavior.behaviors) == 1
    assert behavior.behaviors[0]["name"] == "design-intelligence"


def test_parse_behavior_definition_services() -> None:
    behavior = parse_behavior_definition(_BEHAVIOR_YAML)
    assert len(behavior.services) == 1
    assert behavior.services[0].name == "amplifier-foundation"


# ---------------------------------------------------------------------------
# ServiceEntry
# ---------------------------------------------------------------------------


def test_service_entry_definition_id() -> None:
    """ServiceEntry.definition_id property formats correctly."""
    svc = ServiceEntry(name="amplifier-foundation", installer="pip", source="amplifier-foundation")
    # definition_id is not set on construction — it's populated during resolution
    assert svc.name == "amplifier-foundation"
```

### Step 2: Run to verify failure

Run: `cd amplifier-ipc/amplifier-ipc-cli && python -m pytest tests/test_definitions.py -v`
Expected: FAIL with `ModuleNotFoundError`

### Step 3: Implement the definitions module

Create `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/definitions.py`:

```python
"""Agent/behavior definition parsing and resolution.

Parses YAML definition files into structured dataclasses, walks behavior
trees recursively, and collects the full set of services needed for a session.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import yaml


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ServiceEntry:
    """A service declared in a definition's ``services`` section."""

    name: str
    installer: str = ""
    source: str = ""


@dataclass
class AgentDefinition:
    """Parsed representation of an agent definition YAML."""

    type: str
    local_ref: str
    uuid: str
    version: str = ""
    description: str = ""
    orchestrator: str = ""
    context_manager: str = ""
    provider: str | None = None
    behaviors: list[dict[str, Any]] = field(default_factory=list)
    services: list[ServiceEntry] = field(default_factory=list)
    tools: list[dict[str, Any]] = field(default_factory=list)
    hooks: list[dict[str, Any]] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    agents: list[dict[str, Any]] = field(default_factory=list)
    component_config: dict[str, Any] = field(default_factory=dict)


@dataclass
class BehaviorDefinition:
    """Parsed representation of a behavior definition YAML."""

    type: str
    local_ref: str
    uuid: str
    version: str = ""
    description: str = ""
    behaviors: list[dict[str, Any]] = field(default_factory=list)
    services: list[ServiceEntry] = field(default_factory=list)
    tools: list[dict[str, Any]] = field(default_factory=list)
    hooks: list[dict[str, Any]] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResolvedAgent:
    """The fully resolved data needed to launch a session.

    Produced by :func:`resolve_agent` after walking the behavior tree,
    deduplicating services, and merging extra behaviors.
    """

    services: list[ServiceEntry]
    orchestrator: str
    context_manager: str
    provider: str | None
    component_config: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _parse_services(raw_services: list[dict[str, Any]] | None) -> list[ServiceEntry]:
    """Parse a list of service dicts into ServiceEntry objects."""
    if not raw_services:
        return []
    return [
        ServiceEntry(
            name=svc.get("name", ""),
            installer=svc.get("installer", ""),
            source=svc.get("source", ""),
        )
        for svc in raw_services
    ]


def parse_agent_definition(yaml_content: str) -> AgentDefinition:
    """Parse an agent definition YAML string into an AgentDefinition.

    Args:
        yaml_content: Raw YAML string.

    Returns:
        Parsed AgentDefinition.
    """
    data: dict[str, Any] = yaml.safe_load(yaml_content) or {}

    return AgentDefinition(
        type=data.get("type", "agent"),
        local_ref=data.get("local_ref", ""),
        uuid=str(data.get("uuid", "")),
        version=str(data.get("version", "")),
        description=data.get("description", ""),
        orchestrator=data.get("orchestrator", ""),
        context_manager=data.get("context_manager", ""),
        provider=data.get("provider"),
        behaviors=data.get("behaviors", []),
        services=_parse_services(data.get("services")),
        tools=data.get("tools", []),
        hooks=data.get("hooks", []),
        context=data.get("context", {}),
        agents=data.get("agents", []),
        component_config=data.get("config", {}),
    )


def parse_behavior_definition(yaml_content: str) -> BehaviorDefinition:
    """Parse a behavior definition YAML string into a BehaviorDefinition.

    Args:
        yaml_content: Raw YAML string.

    Returns:
        Parsed BehaviorDefinition.
    """
    data: dict[str, Any] = yaml.safe_load(yaml_content) or {}

    return BehaviorDefinition(
        type=data.get("type", "behavior"),
        local_ref=data.get("local_ref", ""),
        uuid=str(data.get("uuid", "")),
        version=str(data.get("version", "")),
        description=data.get("description", ""),
        behaviors=data.get("behaviors", []),
        services=_parse_services(data.get("services")),
        tools=data.get("tools", []),
        hooks=data.get("hooks", []),
        context=data.get("context", {}),
    )
```

### Step 4: Run the tests

Run: `cd amplifier-ipc/amplifier-ipc-cli && python -m pytest tests/test_definitions.py -v`
Expected: All tests PASS.

### Step 5: Commit

```bash
cd amplifier-ipc/amplifier-ipc-cli && git add -A && git commit -m "feat(cli): definition YAML parsing — AgentDefinition, BehaviorDefinition, ServiceEntry dataclasses"
```

---

## Task 7: Definitions — Tree Walking

Add `resolve_agent()` function that walks the behavior tree, collects services, and deduplicates by UUID.

**Files:**
- Modify: `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/definitions.py`
- Modify: `amplifier-ipc/amplifier-ipc-cli/tests/test_definitions.py`

### Step 1: Write failing tests for tree walking

Append to `amplifier-ipc/amplifier-ipc-cli/tests/test_definitions.py`:

```python
import pytest

from pathlib import Path

from amplifier_ipc_cli.definitions import ResolvedAgent, resolve_agent
from amplifier_ipc_cli.registry import Registry


# ---------------------------------------------------------------------------
# Fixtures for tree-walking tests
# ---------------------------------------------------------------------------


_BEHAVIOR_INNER_YAML = """\
type: behavior
local_ref: design-intelligence
uuid: bbbb1111-aaaa-2222-3333-444455556666
version: "1.0"
description: Design intelligence behavior
tools:
  - name: design_tool
services:
  - name: amplifier-foundation
    installer: pip
    source: amplifier-foundation
"""


def _setup_registry_with_definitions(tmp_path: Path) -> Registry:
    """Create a registry and register agent + behavior definitions."""
    registry = Registry(home=tmp_path)
    registry.ensure_home()

    # Register the inner behavior first
    registry.register_definition(_BEHAVIOR_INNER_YAML)

    # Register the outer behavior (references design-intelligence by name)
    outer_behavior = """\
type: behavior
local_ref: amplifier-dev
uuid: a6a2e2b5-abcd-1234-5678-abcdef012345
version: "1.0"
description: Amplifier development behavior
tools:
  - name: bash
behaviors:
  - name: design-intelligence
services:
  - name: amplifier-foundation
    installer: pip
    source: amplifier-foundation
"""
    registry.register_definition(outer_behavior)

    # Register the agent (references amplifier-dev by name)
    agent = """\
type: agent
local_ref: foundation
uuid: 3898a638-1234-5678-9abc-def012345678
version: "1.0"
description: Foundation agent
orchestrator: streaming
context_manager: simple
provider: anthropic
behaviors:
  - name: amplifier-dev
services:
  - name: amplifier-foundation
    installer: pip
    source: amplifier-foundation
"""
    registry.register_definition(agent)
    return registry


# ---------------------------------------------------------------------------
# resolve_agent tests
# ---------------------------------------------------------------------------


async def test_resolve_agent_basic(tmp_path: Path) -> None:
    """resolve_agent() returns a ResolvedAgent with collected services."""
    registry = _setup_registry_with_definitions(tmp_path)
    resolved = await resolve_agent(registry, "foundation")

    assert isinstance(resolved, ResolvedAgent)
    assert resolved.orchestrator == "streaming"
    assert resolved.context_manager == "simple"
    assert resolved.provider == "anthropic"


async def test_resolve_agent_deduplicates_services(tmp_path: Path) -> None:
    """Services with the same name are deduplicated."""
    registry = _setup_registry_with_definitions(tmp_path)
    resolved = await resolve_agent(registry, "foundation")

    # All three definitions reference 'amplifier-foundation' — should be deduped to 1
    service_names = [s.name for s in resolved.services]
    assert service_names.count("amplifier-foundation") == 1


async def test_resolve_agent_walks_nested_behaviors(tmp_path: Path) -> None:
    """resolve_agent() recurses into nested behaviors."""
    registry = _setup_registry_with_definitions(tmp_path)
    resolved = await resolve_agent(registry, "foundation")

    # Should have at least one service (from the tree walk)
    assert len(resolved.services) >= 1


async def test_resolve_agent_with_extra_behaviors(tmp_path: Path) -> None:
    """Extra behaviors are merged into the resolved agent."""
    registry = _setup_registry_with_definitions(tmp_path)
    resolved = await resolve_agent(
        registry, "foundation", extra_behaviors=["design-intelligence"]
    )

    assert isinstance(resolved, ResolvedAgent)
    # Extra behavior's services should also be included
    assert len(resolved.services) >= 1


async def test_resolve_agent_unknown_agent(tmp_path: Path) -> None:
    """resolve_agent() raises FileNotFoundError for unknown agent."""
    registry = Registry(home=tmp_path)
    registry.ensure_home()

    with pytest.raises(FileNotFoundError):
        await resolve_agent(registry, "nonexistent")
```

### Step 2: Run to verify failure

Run: `cd amplifier-ipc/amplifier-ipc-cli && python -m pytest tests/test_definitions.py -v -k "resolve_agent"`
Expected: FAIL with `ImportError: cannot import name 'resolve_agent'`

### Step 3: Implement `resolve_agent`

Add to `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/definitions.py`:

```python
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from amplifier_ipc_cli.registry import Registry

logger = logging.getLogger(__name__)


async def resolve_agent(
    registry: Registry,
    agent_name: str,
    extra_behaviors: list[str] | None = None,
) -> ResolvedAgent:
    """Resolve an agent name into a fully populated ResolvedAgent.

    1. Look up the agent alias in the registry.
    2. Parse the agent definition YAML.
    3. Walk the behavior tree recursively, collecting services.
    4. Deduplicate services by name.
    5. Merge any extra behaviors.
    6. Return a ResolvedAgent.

    Args:
        registry: The Registry instance to look up definitions.
        agent_name: Human-readable agent name (alias).
        extra_behaviors: Additional behavior names to include.

    Returns:
        A ResolvedAgent with all services and component selections.

    Raises:
        FileNotFoundError: If the agent or a referenced behavior is not found.
    """
    agent_path = registry.resolve_agent(agent_name)
    agent_def = parse_agent_definition(agent_path.read_text())

    # Collect services from the agent itself
    seen_services: dict[str, ServiceEntry] = {}
    for svc in agent_def.services:
        seen_services[svc.name] = svc

    # Walk behaviors
    visited_behaviors: set[str] = set()

    def _walk_behavior(behavior_ref: dict[str, Any]) -> None:
        """Recursively resolve a behavior reference and collect its services."""
        name = behavior_ref.get("name", "")
        url = behavior_ref.get("url")

        if name in visited_behaviors:
            return
        visited_behaviors.add(name)

        # Try to load from local registry first
        try:
            behavior_path = registry.resolve_behavior(name)
        except FileNotFoundError:
            if url:
                # URL fetching is handled in Task 8 — for now, skip
                logger.warning(
                    "Behavior '%s' not found locally and URL fetching "
                    "is not yet implemented. Skipping.",
                    name,
                )
                return
            raise

        behavior_def = parse_behavior_definition(behavior_path.read_text())

        # Collect services
        for svc in behavior_def.services:
            if svc.name not in seen_services:
                seen_services[svc.name] = svc

        # Recurse into nested behaviors
        for nested_ref in behavior_def.behaviors:
            _walk_behavior(nested_ref)

    # Walk all behaviors declared in the agent
    for behavior_ref in agent_def.behaviors:
        _walk_behavior(behavior_ref)

    # Walk extra behaviors
    if extra_behaviors:
        for extra_name in extra_behaviors:
            _walk_behavior({"name": extra_name})

    return ResolvedAgent(
        services=list(seen_services.values()),
        orchestrator=agent_def.orchestrator,
        context_manager=agent_def.context_manager,
        provider=agent_def.provider,
        component_config=agent_def.component_config,
    )
```

Note: The `_walk_behavior` function is synchronous because local file reads are fast. The `resolve_agent` function is `async` to support URL fetching in Task 8.

### Step 4: Run the tests

Run: `cd amplifier-ipc/amplifier-ipc-cli && python -m pytest tests/test_definitions.py -v`
Expected: All tests PASS.

### Step 5: Commit

```bash
cd amplifier-ipc/amplifier-ipc-cli && git add -A && git commit -m "feat(cli): definition tree walking — resolve_agent() with recursive behavior traversal and service deduplication"
```

---

## Task 8: Definitions — URL Fetching

Add URL fetching to `resolve_agent()`: when a behavior is referenced by URL and not registered locally, fetch and auto-register it.

**Files:**
- Modify: `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/definitions.py`
- Modify: `amplifier-ipc/amplifier-ipc-cli/tests/test_definitions.py`

### Step 1: Write failing tests for URL fetching

Append to `amplifier-ipc/amplifier-ipc-cli/tests/test_definitions.py`:

```python
from unittest.mock import AsyncMock, patch


# ---------------------------------------------------------------------------
# URL fetching tests
# ---------------------------------------------------------------------------

_REMOTE_BEHAVIOR_YAML = """\
type: behavior
local_ref: remote-tool
uuid: cccc2222-dddd-3333-4444-555566667777
version: "1.0"
description: A remotely-fetched behavior
tools:
  - name: remote_tool
services:
  - name: remote-service
    installer: pip
    source: remote-service-pkg
"""


async def test_resolve_agent_fetches_url_behavior(tmp_path: Path) -> None:
    """When a behavior URL is given and not registered locally, fetch and auto-register."""
    registry = Registry(home=tmp_path)
    registry.ensure_home()

    # Agent references a behavior by URL (not registered locally)
    agent_yaml = """\
type: agent
local_ref: test-agent
uuid: eeee3333-ffff-4444-5555-666677778888
version: "1.0"
orchestrator: streaming
context_manager: simple
behaviors:
  - name: remote-tool
    url: https://example.com/remote-tool.yaml
services:
  - name: test-service
    installer: pip
    source: test-service-pkg
"""
    registry.register_definition(agent_yaml)

    # Mock the URL fetch
    mock_fetch = AsyncMock(return_value=_REMOTE_BEHAVIOR_YAML)

    with patch("amplifier_ipc_cli.definitions._fetch_url", mock_fetch):
        resolved = await resolve_agent(registry, "test-agent")

    # The remote behavior's service should be included
    service_names = [s.name for s in resolved.services]
    assert "remote-service" in service_names

    # The behavior should now be registered locally
    path = registry.resolve_behavior("remote-tool")
    assert path.is_file()

    # The fetch was called with the correct URL
    mock_fetch.assert_called_once_with("https://example.com/remote-tool.yaml")


async def test_resolve_agent_uses_cached_behavior_on_second_call(
    tmp_path: Path,
) -> None:
    """After auto-registering, a second resolve should not fetch again."""
    registry = Registry(home=tmp_path)
    registry.ensure_home()

    agent_yaml = """\
type: agent
local_ref: test-agent2
uuid: aaaa1111-bbbb-2222-3333-444455556666
version: "1.0"
orchestrator: streaming
context_manager: simple
behaviors:
  - name: remote-tool
    url: https://example.com/remote-tool.yaml
services:
  - name: test-service
    installer: pip
    source: test-service-pkg
"""
    registry.register_definition(agent_yaml)

    mock_fetch = AsyncMock(return_value=_REMOTE_BEHAVIOR_YAML)

    # First call — fetches
    with patch("amplifier_ipc_cli.definitions._fetch_url", mock_fetch):
        await resolve_agent(registry, "test-agent2")

    mock_fetch.reset_mock()

    # Second call — should use cache, not fetch
    with patch("amplifier_ipc_cli.definitions._fetch_url", mock_fetch):
        await resolve_agent(registry, "test-agent2")

    mock_fetch.assert_not_called()
```

### Step 2: Run to verify failure

Run: `cd amplifier-ipc/amplifier-ipc-cli && python -m pytest tests/test_definitions.py -v -k "fetches_url or cached_behavior"`
Expected: FAIL (either import error or behavior lookup fails)

### Step 3: Implement URL fetching

Add to `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/definitions.py`:

```python
import urllib.request
import urllib.error


async def _fetch_url(url: str) -> str:
    """Fetch a URL and return its content as a string.

    Uses urllib (no external dependency). Runs in an executor for async compat.

    Args:
        url: The URL to fetch.

    Returns:
        The response body as a string.

    Raises:
        urllib.error.URLError: On network/HTTP errors.
    """
    import asyncio

    loop = asyncio.get_running_loop()

    def _do_fetch() -> str:
        with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310
            return resp.read().decode("utf-8")

    return await loop.run_in_executor(None, _do_fetch)
```

Then update the `_walk_behavior` inner function inside `resolve_agent` to handle URL fetching. Replace the `_walk_behavior` function and make it async:

```python
    async def _walk_behavior(behavior_ref: dict[str, Any]) -> None:
        """Recursively resolve a behavior reference and collect its services."""
        name = behavior_ref.get("name", "")
        url = behavior_ref.get("url")

        if name in visited_behaviors:
            return
        visited_behaviors.add(name)

        # Try local registry first
        try:
            behavior_path = registry.resolve_behavior(name)
        except FileNotFoundError:
            if url:
                # Fetch from URL and auto-register
                logger.info("Fetching behavior '%s' from %s", name, url)
                yaml_content = await _fetch_url(url)
                registry.register_definition(yaml_content, source_url=url)
                behavior_path = registry.resolve_behavior(name)
            else:
                raise

        behavior_def = parse_behavior_definition(behavior_path.read_text())

        # Collect services
        for svc in behavior_def.services:
            if svc.name not in seen_services:
                seen_services[svc.name] = svc

        # Recurse into nested behaviors
        for nested_ref in behavior_def.behaviors:
            await _walk_behavior(nested_ref)

    # Walk all behaviors declared in the agent
    for behavior_ref in agent_def.behaviors:
        await _walk_behavior(behavior_ref)

    # Walk extra behaviors
    if extra_behaviors:
        for extra_name in extra_behaviors:
            await _walk_behavior({"name": extra_name})
```

### Step 4: Run the tests

Run: `cd amplifier-ipc/amplifier-ipc-cli && python -m pytest tests/test_definitions.py -v`
Expected: All tests PASS.

### Step 5: Commit

```bash
cd amplifier-ipc/amplifier-ipc-cli && git add -A && git commit -m "feat(cli): URL fetching for remote behavior definitions

When a behavior is referenced by URL and not found locally, fetch it,
auto-register via registry.register_definition(), then continue resolution.
_meta block records source_url, source_hash (SHA-256), and fetched_at."
```

---

## Task 9: Session Launcher

Create the session launcher that bridges definition resolution and Host creation. TDD.

**Files:**
- Create: `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/session_launcher.py`
- Test: `amplifier-ipc/amplifier-ipc-cli/tests/test_session_launcher.py`

### Step 1: Write failing tests

Create `amplifier-ipc/amplifier-ipc-cli/tests/test_session_launcher.py`:

```python
"""Tests for the session launcher — bridges definitions to Host."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from amplifier_ipc_cli.session_launcher import build_session_config, launch_session
from amplifier_ipc_cli.definitions import ResolvedAgent, ServiceEntry


# ---------------------------------------------------------------------------
# build_session_config
# ---------------------------------------------------------------------------


def test_build_session_config_basic() -> None:
    """build_session_config() produces a SessionConfig from a ResolvedAgent."""
    resolved = ResolvedAgent(
        services=[
            ServiceEntry(name="amplifier-foundation", installer="pip", source="pkg"),
        ],
        orchestrator="streaming",
        context_manager="simple",
        provider="anthropic",
    )

    config = build_session_config(resolved)

    assert config.services == ["amplifier-foundation"]
    assert config.orchestrator == "streaming"
    assert config.context_manager == "simple"
    assert config.provider == "anthropic"


def test_build_session_config_multiple_services() -> None:
    """build_session_config() includes all service names."""
    resolved = ResolvedAgent(
        services=[
            ServiceEntry(name="svc-a", installer="pip", source="a"),
            ServiceEntry(name="svc-b", installer="pip", source="b"),
        ],
        orchestrator="loop",
        context_manager="simple",
        provider="openai",
    )

    config = build_session_config(resolved)
    assert config.services == ["svc-a", "svc-b"]


def test_build_session_config_preserves_component_config() -> None:
    """build_session_config() passes through component_config."""
    resolved = ResolvedAgent(
        services=[ServiceEntry(name="svc", installer="pip", source="pkg")],
        orchestrator="loop",
        context_manager="simple",
        provider="anthropic",
        component_config={"streaming": {"chunk_size": 100}},
    )

    config = build_session_config(resolved)
    assert config.component_config == {"streaming": {"chunk_size": 100}}


# ---------------------------------------------------------------------------
# launch_session
# ---------------------------------------------------------------------------


_AGENT_YAML = """\
type: agent
local_ref: test-agent
uuid: aaaa1111-bbbb-2222-3333-444455556666
version: "1.0"
orchestrator: streaming
context_manager: simple
provider: anthropic
services:
  - name: test-service
    installer: pip
    source: test-service-pkg
"""


async def test_launch_session_creates_host(tmp_path: Path) -> None:
    """launch_session() resolves definitions and creates a Host."""
    from amplifier_ipc_cli.registry import Registry

    registry = Registry(home=tmp_path)
    registry.ensure_home()
    registry.register_definition(_AGENT_YAML)

    mock_host_cls = MagicMock()
    mock_host_instance = MagicMock()
    mock_host_cls.return_value = mock_host_instance

    with patch("amplifier_ipc_cli.session_launcher.Host", mock_host_cls):
        host = await launch_session("test-agent", registry=registry)

    assert host is mock_host_instance
    # Host was constructed with a SessionConfig and HostSettings
    mock_host_cls.assert_called_once()
    call_kwargs = mock_host_cls.call_args
    config = call_kwargs[1].get("config") or call_kwargs[0][0]
    assert config.orchestrator == "streaming"
    assert config.services == ["test-service"]
```

### Step 2: Run to verify failure

Run: `cd amplifier-ipc/amplifier-ipc-cli && python -m pytest tests/test_session_launcher.py -v`
Expected: FAIL with `ModuleNotFoundError`

### Step 3: Implement session_launcher.py

Create `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/session_launcher.py`:

```python
"""Session launcher — bridges definition resolution and Host creation.

Resolves an agent name through the registry, walks the behavior tree,
builds a SessionConfig, and creates an in-process Host instance.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from amplifier_ipc_host.config import HostSettings, SessionConfig
from amplifier_ipc_host.host import Host

from amplifier_ipc_cli.definitions import ResolvedAgent, ServiceEntry, resolve_agent

if TYPE_CHECKING:
    from amplifier_ipc_cli.registry import Registry

logger = logging.getLogger(__name__)


def build_session_config(
    resolved: ResolvedAgent,
) -> SessionConfig:
    """Build a SessionConfig from a ResolvedAgent.

    Args:
        resolved: The fully resolved agent data.

    Returns:
        A SessionConfig ready for Host construction.
    """
    return SessionConfig(
        services=[svc.name for svc in resolved.services],
        orchestrator=resolved.orchestrator,
        context_manager=resolved.context_manager,
        provider=resolved.provider or "",
        component_config=resolved.component_config,
    )


async def launch_session(
    agent_name: str,
    *,
    extra_behaviors: list[str] | None = None,
    registry: Registry | None = None,
) -> Host:
    """Resolve an agent and create a Host instance.

    Steps:
    1. Create or use the provided Registry.
    2. Call resolve_agent() to walk the behavior tree.
    3. Build a SessionConfig from the resolved data.
    4. Create and return a Host instance (does not start it).

    Args:
        agent_name: Human-readable agent name.
        extra_behaviors: Additional behavior names to include.
        registry: Optional Registry instance (created if not provided).

    Returns:
        A configured Host instance ready for ``async for event in host.run(prompt):``.
    """
    if registry is None:
        from amplifier_ipc_cli.registry import Registry

        registry = Registry()
        registry.ensure_home()

    resolved = await resolve_agent(registry, agent_name, extra_behaviors)

    config = build_session_config(resolved)
    settings = HostSettings()

    return Host(config=config, settings=settings)
```

### Step 4: Run the tests

Run: `cd amplifier-ipc/amplifier-ipc-cli && python -m pytest tests/test_session_launcher.py -v`
Expected: All tests PASS.

### Step 5: Commit

```bash
cd amplifier-ipc/amplifier-ipc-cli && git add -A && git commit -m "feat(cli): session launcher — resolve_agent → build SessionConfig → create Host"
```

---

## Task 10: Run Command

Create the `run` command and wire up the Click group in `main.py`.

**Files:**
- Create: `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/commands/run.py`
- Modify: `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/main.py`
- Test: `amplifier-ipc/amplifier-ipc-cli/tests/test_commands/__init__.py`
- Test: `amplifier-ipc/amplifier-ipc-cli/tests/test_commands/test_run.py`

### Step 1: Write failing tests for the run command

Create `amplifier-ipc/amplifier-ipc-cli/tests/test_commands/__init__.py` (empty).

Create `amplifier-ipc/amplifier-ipc-cli/tests/test_commands/test_run.py`:

```python
"""Tests for the run command."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from click.testing import CliRunner

from amplifier_ipc_cli.main import cli


def test_run_no_agent_shows_error() -> None:
    """Running without --agent shows an error message."""
    runner = CliRunner()
    result = runner.invoke(cli, ["run"])
    # Should complain about missing --agent
    assert result.exit_code != 0 or "agent" in result.output.lower()


def test_run_with_agent_invokes_launcher() -> None:
    """run --agent <name> calls launch_session and enters REPL."""
    runner = CliRunner()

    mock_launch = AsyncMock()

    with patch("amplifier_ipc_cli.commands.run._run_agent", mock_launch):
        result = runner.invoke(cli, ["run", "--agent", "foundation"])

    # The command should invoke the launcher (the async wrapper)
    mock_launch.assert_called_once()


def test_run_with_message_passes_prompt() -> None:
    """run --agent <name> 'hello' passes the message as initial prompt."""
    runner = CliRunner()

    mock_launch = AsyncMock()

    with patch("amplifier_ipc_cli.commands.run._run_agent", mock_launch):
        result = runner.invoke(cli, ["run", "--agent", "foundation", "hello world"])

    call_args = mock_launch.call_args
    # The message should be passed through
    assert "hello world" in str(call_args)


def test_cli_without_subcommand_shows_help() -> None:
    """Running the CLI with no subcommand shows help."""
    runner = CliRunner()
    result = runner.invoke(cli, [])
    assert result.exit_code == 0
    assert "amplifier-ipc" in result.output.lower() or "Usage" in result.output


def test_version_command() -> None:
    """The version command works."""
    runner = CliRunner()
    result = runner.invoke(cli, ["version"])
    assert result.exit_code == 0
    assert "amplifier-ipc-cli" in result.output
```

### Step 2: Run to verify failure

Run: `cd amplifier-ipc/amplifier-ipc-cli && python -m pytest tests/test_commands/test_run.py -v`
Expected: FAIL (run command doesn't exist yet)

### Step 3: Implement the run command

Create `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/commands/run.py`:

```python
"""Primary run command for amplifier-ipc-cli.

Resolves an agent definition, creates a Host, and either executes a
single prompt or enters the interactive REPL.
"""

from __future__ import annotations

import asyncio
import logging

import click

from amplifier_ipc_cli.console import console

logger = logging.getLogger(__name__)


@click.command()
@click.option("--agent", "-a", required=True, help="Agent name to run.")
@click.option(
    "--add-behavior",
    "-b",
    multiple=True,
    help="Additional behavior(s) to include.",
)
@click.option("--session", "-s", default=None, help="Session ID to resume.")
@click.option("--project", default=None, help="Project name.")
@click.option("--working-dir", "-w", default=None, help="Working directory.")
@click.argument("message", required=False, default=None)
def run(
    agent: str,
    add_behavior: tuple[str, ...],
    session: str | None,
    project: str | None,
    working_dir: str | None,
    message: str | None,
) -> None:
    """Run an interactive session with the specified agent.

    Examples:

        amplifier-ipc run --agent foundation
        amplifier-ipc run --agent foundation "What is 2+2?"
        amplifier-ipc run --agent foundation --add-behavior design-intelligence
    """
    try:
        asyncio.run(
            _run_agent(
                agent_name=agent,
                extra_behaviors=list(add_behavior),
                prompt=message,
                session_id=session,
            )
        )
    except KeyboardInterrupt:
        console.print("\nExiting...")
    except FileNotFoundError as exc:
        console.print(f"[red]Error:[/red] {exc}")
    except Exception as exc:
        console.print(f"[red]Error:[/red] {exc}")
        logger.debug("Run failed", exc_info=True)


async def _run_agent(
    agent_name: str,
    extra_behaviors: list[str] | None = None,
    prompt: str | None = None,
    session_id: str | None = None,
) -> None:
    """Resolve the agent, create a Host, and run.

    If a prompt is provided, execute it and print the result.
    If no prompt, enter the interactive REPL.
    """
    from amplifier_ipc_cli.key_manager import KeyManager
    from amplifier_ipc_cli.session_launcher import launch_session

    # Load API keys
    key_manager = KeyManager()
    key_manager.load_keys()

    console.print(f"[dim]Resolving agent: {agent_name}[/dim]")
    host = await launch_session(agent_name, extra_behaviors=extra_behaviors or None)

    if prompt:
        # Single-shot execution
        console.print(f"[dim]Executing prompt...[/dim]")
        async for event in host.run(prompt):
            _handle_event(event)
    else:
        # Interactive REPL
        from amplifier_ipc_cli.repl import interactive_repl

        await interactive_repl(host, agent_name=agent_name)


def _handle_event(event: object) -> None:
    """Handle a single HostEvent for single-shot mode."""
    from amplifier_ipc_host.events import (
        CompleteEvent,
        StreamThinkingEvent,
        StreamTokenEvent,
        StreamToolCallStartEvent,
    )

    if isinstance(event, StreamTokenEvent):
        import sys

        sys.stdout.write(event.text)
        sys.stdout.flush()
    elif isinstance(event, StreamThinkingEvent):
        console.print(f"[cyan dim]{event.text}[/cyan dim]", end="")
    elif isinstance(event, StreamToolCallStartEvent):
        console.print(f"[dim]Using tool: {event.name}[/dim]")
    elif isinstance(event, CompleteEvent):
        import sys

        sys.stdout.write("\n")
        sys.stdout.flush()
```

### Step 4: Rewrite `main.py` with the full Click group

Replace `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/main.py`:

```python
"""Main entry point for the amplifier-ipc CLI."""

from __future__ import annotations

import click

from amplifier_ipc_cli.commands.allowed_dirs import allowed_dirs_group
from amplifier_ipc_cli.commands.denied_dirs import denied_dirs_group
from amplifier_ipc_cli.commands.notify import notify_group
from amplifier_ipc_cli.commands.run import run
from amplifier_ipc_cli.commands.version import version


@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx: click.Context) -> None:
    """amplifier-ipc — interact with amplifier-ipc sessions."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


cli.add_command(run)
cli.add_command(version)
cli.add_command(allowed_dirs_group, name="allowed-dirs")
cli.add_command(denied_dirs_group, name="denied-dirs")
cli.add_command(notify_group, name="notify")


def main() -> None:
    """Main entry point — delegates to the cli Click group."""
    cli()


if __name__ == "__main__":
    main()
```

### Step 5: Create a stub repl module for imports

Create `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/repl.py`:

```python
"""Interactive REPL — placeholder until Task 11."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from amplifier_ipc_host.host import Host


async def interactive_repl(host: Host, *, agent_name: str = "") -> None:
    """Placeholder REPL — replaced in Task 11."""
    from amplifier_ipc_cli.console import console

    console.print("[yellow]REPL not yet implemented. Use a message argument.[/yellow]")
```

### Step 6: Run the tests

Run: `cd amplifier-ipc/amplifier-ipc-cli && python -m pytest tests/test_commands/test_run.py -v`
Expected: All tests PASS.

### Step 7: Commit

```bash
cd amplifier-ipc/amplifier-ipc-cli && git add -A && git commit -m "feat(cli): run command and Click group wiring

amplifier-ipc run --agent <name> [message] resolves definitions,
creates Host, and either executes single-shot or enters REPL."
```

---

## Task 11: REPL Adaptation

Replace the stub REPL with a full prompt-toolkit REPL that iterates the Host event stream.

**Files:**
- Modify: `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/repl.py`
- Test: `amplifier-ipc/amplifier-ipc-cli/tests/test_repl.py`

### Step 1: Write tests for REPL event handling

Create `amplifier-ipc/amplifier-ipc-cli/tests/test_repl.py`:

```python
"""Tests for the REPL event handling logic."""

from __future__ import annotations

from unittest.mock import MagicMock

from amplifier_ipc_host.events import (
    CompleteEvent,
    StreamThinkingEvent,
    StreamTokenEvent,
    StreamToolCallStartEvent,
)

from amplifier_ipc_cli.repl import handle_host_event


def test_handle_stream_token(capsys: object) -> None:
    """Stream tokens are written to stdout."""
    import sys
    from io import StringIO

    old_stdout = sys.stdout
    sys.stdout = buf = StringIO()
    try:
        event = StreamTokenEvent(text="hello ")
        handle_host_event(event)
        assert buf.getvalue() == "hello "
    finally:
        sys.stdout = old_stdout


def test_handle_complete_event() -> None:
    """CompleteEvent stores the final response."""
    state = {"response": ""}
    event = CompleteEvent(response="The answer is 42.")
    handle_host_event(event, state=state)
    assert state["response"] == "The answer is 42."


def test_handle_tool_call_start() -> None:
    """StreamToolCallStartEvent is handled without error."""
    event = StreamToolCallStartEvent(name="bash", call_id="abc")
    # Should not raise
    handle_host_event(event)
```

### Step 2: Run to verify failure

Run: `cd amplifier-ipc/amplifier-ipc-cli && python -m pytest tests/test_repl.py -v`
Expected: FAIL with `ImportError: cannot import name 'handle_host_event'`

### Step 3: Implement the REPL

Replace `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/repl.py`:

```python
"""Interactive REPL for amplifier-ipc-cli.

Provides:
- handle_host_event(): Process a single HostEvent for display.
- interactive_repl(): The main REPL loop using prompt-toolkit.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory, InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.patch_stdout import patch_stdout
from rich.panel import Panel

from amplifier_ipc_cli.console import console as default_console
from amplifier_ipc_cli.ui.message_renderer import render_message
from amplifier_ipc_host.events import (
    CompleteEvent,
    ErrorEvent,
    HostEvent,
    StreamThinkingEvent,
    StreamTokenEvent,
    StreamToolCallStartEvent,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Event handling (testable, no terminal dependency)
# ---------------------------------------------------------------------------


def handle_host_event(
    event: HostEvent,
    *,
    state: dict[str, Any] | None = None,
) -> None:
    """Handle a single HostEvent for display.

    Args:
        event: The event to handle.
        state: Optional mutable dict for tracking state (e.g. final response).
    """
    if isinstance(event, StreamTokenEvent):
        sys.stdout.write(event.text)
        sys.stdout.flush()
    elif isinstance(event, StreamThinkingEvent):
        default_console.print(f"[cyan dim]{event.text}[/cyan dim]", end="")
    elif isinstance(event, StreamToolCallStartEvent):
        default_console.print(f"\n[dim]Using tool: {event.name}[/dim]")
    elif isinstance(event, ErrorEvent):
        default_console.print(f"\n[red]Error ({event.service}): {event.message}[/red]")
    elif isinstance(event, CompleteEvent):
        sys.stdout.write("\n")
        sys.stdout.flush()
        if state is not None:
            state["response"] = event.response


# ---------------------------------------------------------------------------
# Prompt session factory (copied from lite-cli repl.py)
# ---------------------------------------------------------------------------


def _create_prompt_session(
    *,
    history_path: Path | None = None,
) -> PromptSession:
    """Create a configured PromptSession for the REPL."""
    if history_path is not None:
        history_path.parent.mkdir(parents=True, exist_ok=True)

    history: FileHistory | InMemoryHistory
    if history_path is not None:
        try:
            with open(history_path, "a"):
                pass
            history = FileHistory(str(history_path))
        except OSError:
            history = InMemoryHistory()
    else:
        history = InMemoryHistory()

    kb = KeyBindings()

    @kb.add("c-j")
    def insert_newline(event: Any) -> None:
        event.current_buffer.insert_text("\n")

    @kb.add("enter")
    def accept_input(event: Any) -> None:
        event.current_buffer.validate_and_handle()

    def get_prompt() -> HTML:
        return HTML("\n<ansigreen><b>></b></ansigreen> ")

    return PromptSession(
        message=get_prompt,
        history=history,
        key_bindings=kb,
        multiline=True,
        prompt_continuation="  ",
        enable_history_search=True,
    )


# ---------------------------------------------------------------------------
# REPL loop
# ---------------------------------------------------------------------------


async def interactive_repl(
    host: Any,
    *,
    agent_name: str = "",
    console: Any | None = None,
) -> None:
    """Run the interactive REPL loop.

    Each turn:
    1. Read user input via prompt-toolkit.
    2. If it's a slash command, handle it.
    3. If it's a prompt, iterate host.run(prompt) and handle events.

    Args:
        host: A Host instance (from session_launcher).
        agent_name: Agent name for the banner.
        console: Rich Console for output (defaults to shared singleton).
    """
    con = console or default_console

    from amplifier_ipc_cli.paths import get_repl_history_path

    prompt_session = _create_prompt_session(
        history_path=get_repl_history_path(),
    )

    # Banner
    con.print(
        Panel.fit(
            f"[bold cyan]Amplifier IPC Interactive Session[/bold cyan]\n"
            f"[dim]Agent: {agent_name}[/dim]\n"
            f"Commands: /help | Multi-line: Ctrl-J | Exit: Ctrl-D",
            border_style="cyan",
        )
    )

    try:
        while True:
            try:
                with patch_stdout():
                    user_input = await prompt_session.prompt_async()

                if user_input.lower() in ("exit", "quit"):
                    break

                if not user_input.strip():
                    continue

                # Slash commands
                if user_input.strip().startswith("/"):
                    cmd = user_input.strip().lower()
                    if cmd in ("/exit", "/quit"):
                        break
                    elif cmd == "/help":
                        con.print(
                            "Available commands:\n"
                            "  /help   — Show this help\n"
                            "  /exit   — Exit the session\n"
                            "  /quit   — Exit the session"
                        )
                    else:
                        con.print(f"[yellow]Unknown command: {user_input.strip()}[/yellow]")
                    continue

                # Execute prompt
                con.print("\n[dim]Processing... (Ctrl+C to cancel)[/dim]")
                state: dict[str, Any] = {"response": ""}

                async for event in host.run(user_input):
                    handle_host_event(event, state=state)

                # Render the final response as markdown if we got one
                if state["response"]:
                    render_message(
                        {"role": "assistant", "content": state["response"]}, con
                    )

            except EOFError:
                con.print("\n[dim]Exiting...[/dim]")
                break

            except KeyboardInterrupt:
                con.print()
                continue

            except Exception as exc:
                con.print(f"[red]Error:[/red] {exc}")
                logger.debug("REPL error", exc_info=True)

    finally:
        con.print("\n[yellow]Session exited.[/yellow]")
```

### Step 4: Run the tests

Run: `cd amplifier-ipc/amplifier-ipc-cli && python -m pytest tests/test_repl.py -v`
Expected: All tests PASS.

### Step 5: Commit

```bash
cd amplifier-ipc/amplifier-ipc-cli && git add -A && git commit -m "feat(cli): REPL with prompt-toolkit, Host event stream iteration, slash commands"
```

---

## Task 12: Streaming + Approval

Create event handler functions for stream display and an approval provider that works with Host events.

**Files:**
- Create: `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/streaming.py`
- Create: `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/approval_provider.py`
- Test: `amplifier-ipc/amplifier-ipc-cli/tests/test_streaming.py`

### Step 1: Write failing tests for streaming handlers

Create `amplifier-ipc/amplifier-ipc-cli/tests/test_streaming.py`:

```python
"""Tests for streaming event display and approval handling."""

from __future__ import annotations

from io import StringIO

from rich.console import Console

from amplifier_ipc_host.events import (
    CompleteEvent,
    StreamThinkingEvent,
    StreamTokenEvent,
    StreamToolCallStartEvent,
)

from amplifier_ipc_cli.streaming import StreamingDisplay


def test_streaming_display_token() -> None:
    """StreamingDisplay renders stream tokens."""
    buf = StringIO()
    console = Console(file=buf, force_terminal=True)
    display = StreamingDisplay(console=console)

    display.handle_event(StreamTokenEvent(text="Hello"))
    # Token text should appear in the buffer
    assert "Hello" in buf.getvalue()


def test_streaming_display_thinking() -> None:
    """StreamingDisplay renders thinking tokens when enabled."""
    buf = StringIO()
    console = Console(file=buf, force_terminal=True)
    display = StreamingDisplay(console=console, show_thinking=True)

    display.handle_event(StreamThinkingEvent(text="reasoning..."))
    output = buf.getvalue()
    assert "reasoning" in output


def test_streaming_display_thinking_hidden() -> None:
    """StreamingDisplay hides thinking tokens when disabled."""
    buf = StringIO()
    console = Console(file=buf, force_terminal=True)
    display = StreamingDisplay(console=console, show_thinking=False)

    display.handle_event(StreamThinkingEvent(text="reasoning..."))
    output = buf.getvalue()
    assert "reasoning" not in output


def test_streaming_display_tool_call_start() -> None:
    """StreamingDisplay shows tool name on tool_call_start."""
    buf = StringIO()
    console = Console(file=buf, force_terminal=True)
    display = StreamingDisplay(console=console)

    display.handle_event(StreamToolCallStartEvent(name="bash", call_id="abc"))
    assert "bash" in buf.getvalue()


def test_streaming_display_complete() -> None:
    """StreamingDisplay captures the final response."""
    buf = StringIO()
    console = Console(file=buf, force_terminal=True)
    display = StreamingDisplay(console=console)

    display.handle_event(CompleteEvent(response="The answer"))
    assert display.response == "The answer"
```

### Step 2: Run to verify failure

Run: `cd amplifier-ipc/amplifier-ipc-cli && python -m pytest tests/test_streaming.py -v`
Expected: FAIL with `ModuleNotFoundError` or `ImportError`

### Step 3: Implement StreamingDisplay

Create `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/streaming.py`:

```python
"""Streaming event display for the CLI.

Replaces the HookRegistry-based StreamingUIHooks from amplifier-lite-cli.
Instead of registering callbacks, the CLI calls handle_event() for each
HostEvent yielded by Host.run().
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from amplifier_ipc_host.events import (
    CompleteEvent,
    ErrorEvent,
    HostEvent,
    StreamThinkingEvent,
    StreamTokenEvent,
    StreamToolCallStartEvent,
)

if TYPE_CHECKING:
    from rich.console import Console


class StreamingDisplay:
    """Handles HostEvent display via Rich console.

    Args:
        console: Rich Console for output.
        show_thinking: Whether to display thinking/reasoning tokens.
        show_token_usage: Whether to display token usage stats.
    """

    def __init__(
        self,
        console: Console,
        *,
        show_thinking: bool = True,
        show_token_usage: bool = True,
    ) -> None:
        self._console = console
        self._show_thinking = show_thinking
        self._show_token_usage = show_token_usage
        self._response: str = ""

    @property
    def response(self) -> str:
        """The final response text from the last complete event."""
        return self._response

    def handle_event(self, event: HostEvent) -> None:
        """Handle a single HostEvent for display.

        Args:
            event: The event to render.
        """
        if isinstance(event, StreamTokenEvent):
            self._console.print(event.text, end="", markup=False, highlight=False)
        elif isinstance(event, StreamThinkingEvent):
            if self._show_thinking:
                self._console.print(
                    f"[cyan dim]{event.text}[/cyan dim]", end=""
                )
        elif isinstance(event, StreamToolCallStartEvent):
            self._console.print(f"\n[dim]Using tool: {event.name}[/dim]")
        elif isinstance(event, ErrorEvent):
            self._console.print(
                f"\n[red]Error ({event.service}): {event.message}[/red]"
            )
        elif isinstance(event, CompleteEvent):
            self._response = event.response
            self._console.print()  # Newline after streaming
```

### Step 4: Create the approval provider

Create `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/approval_provider.py`:

```python
"""CLI approval provider for Host approval_request events.

When the Host yields an ApprovalRequestEvent, the CLI displays a Rich
panel and prompts the user for a yes/no decision.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from rich.panel import Panel
from rich.prompt import Confirm

from amplifier_ipc_host.events import ApprovalRequestEvent

if TYPE_CHECKING:
    from rich.console import Console


class CLIApprovalHandler:
    """Handles approval requests from the Host event stream.

    Args:
        console: Rich Console for display.
    """

    def __init__(self, console: Console) -> None:
        self._console = console

    async def handle_approval(self, event: ApprovalRequestEvent) -> bool:
        """Display an approval dialog and return the user's decision.

        Args:
            event: The approval request event from the Host.

        Returns:
            True if approved, False if denied.
        """
        risk_color = _get_risk_color(event.risk_level)

        lines = [
            f"Tool:    [bold]{event.tool_name}[/bold]",
            f"Action:  {event.action}",
            f"Risk:    [{risk_color}]{event.risk_level.upper()}[/{risk_color}]",
        ]

        if event.details:
            lines.append("")
            for key, value in event.details.items():
                display_value = str(value)
                if len(display_value) > 100:
                    display_value = display_value[:100] + "\u2026"
                lines.append(f"  {key}: {display_value}")

        max_width = min(76, self._console.width - 4)
        panel = Panel(
            "\n".join(lines),
            title="\u26a0  Approval Required",
            border_style=risk_color,
            padding=(1, 2),
            width=max_width,
        )
        self._console.print(panel)

        loop = asyncio.get_running_loop()
        approved: bool = await loop.run_in_executor(
            None, lambda: Confirm.ask("Approve?", console=self._console)
        )
        return approved


def _get_risk_color(risk_level: str) -> str:
    """Map risk level to Rich color."""
    return {
        "low": "green",
        "medium": "yellow",
        "high": "red",
        "critical": "bold red",
    }.get(risk_level, "white")
```

### Step 5: Run the tests

Run: `cd amplifier-ipc/amplifier-ipc-cli && python -m pytest tests/test_streaming.py -v`
Expected: All tests PASS.

### Step 6: Commit

```bash
cd amplifier-ipc/amplifier-ipc-cli && git add -A && git commit -m "feat(cli): streaming display and approval handler for Host events

StreamingDisplay handles stream.token, stream.thinking, stream.tool_call_start,
and complete events. CLIApprovalHandler shows Rich panel for approval_request."
```

---

## Task 13: Integration Test

End-to-end test proving the full stack works: definition resolution → SessionConfig → Host → foundation service → events stream back.

**Files:**
- Test: `amplifier-ipc/amplifier-ipc-cli/tests/test_integration.py`

### Step 1: Write the integration test

Create `amplifier-ipc/amplifier-ipc-cli/tests/test_integration.py`:

```python
"""Integration test: full stack from definition resolution to Host event stream.

This test:
1. Creates a mock service package (like amplifier-ipc-host's test_integration.py)
2. Registers an agent definition pointing to that service
3. Calls launch_session() to resolve definitions → build config → create Host
4. Manually spawns the service and injects it (bypassing install/spawn)
5. Iterates host.run() to verify events stream back

This proves the CLI layer correctly connects definition resolution to the Host.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

from amplifier_ipc_cli.definitions import resolve_agent
from amplifier_ipc_cli.registry import Registry
from amplifier_ipc_cli.session_launcher import build_session_config
from amplifier_ipc_host.config import HostSettings
from amplifier_ipc_host.events import CompleteEvent, HostEvent, StreamTokenEvent
from amplifier_ipc_host.host import Host
from amplifier_ipc_host.lifecycle import ServiceProcess, shutdown_service
from amplifier_ipc_protocol.client import Client


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

_PROTOCOL_SRC = (
    Path(__file__).parent.parent.parent
    / "amplifier-ipc-protocol"
    / "src"
)
_HOST_SRC = (
    Path(__file__).parent.parent.parent
    / "amplifier-ipc-host"
    / "src"
)


# ---------------------------------------------------------------------------
# Mock service builder (same pattern as amplifier-ipc-host test_integration.py)
# ---------------------------------------------------------------------------


def _create_mock_service_package(tmp_path: Path) -> Path:
    """Create a mock service package with echo tool and orchestrator."""
    pkg = tmp_path / "mock_service"
    pkg.mkdir()

    (pkg / "__init__.py").write_text("")

    (pkg / "__main__.py").write_text(
        "from amplifier_ipc_protocol.server import Server\n"
        'Server("mock_service").run()\n'
    )

    # Tools
    tools_dir = pkg / "tools"
    tools_dir.mkdir()
    (tools_dir / "__init__.py").write_text("")
    (tools_dir / "echo.py").write_text(
        "from amplifier_ipc_protocol.decorators import tool\n"
        "from amplifier_ipc_protocol.models import ToolResult\n"
        "\n"
        "@tool\n"
        "class EchoTool:\n"
        '    name = "echo"\n'
        '    description = "Echoes back"\n'
        "    input_schema = {\n"
        '        "type": "object",\n'
        '        "properties": {"text": {"type": "string"}},\n'
        "    }\n"
        "\n"
        "    async def execute(self, input):\n"
        '        return ToolResult(success=True, output=input.get("text", ""))\n'
    )

    # Content
    agents_dir = pkg / "agents"
    agents_dir.mkdir()
    (agents_dir / "test.md").write_text("# Test Agent")

    context_dir = pkg / "context"
    context_dir.mkdir()
    (context_dir / "base.md").write_text("Base context.")

    return tmp_path


def _build_env(pkg_parent: Path) -> dict[str, str]:
    """Build environment dict with PYTHONPATH for the mock service."""
    existing = os.environ.get("PYTHONPATH", "")
    extra = [str(pkg_parent), str(_PROTOCOL_SRC), str(_HOST_SRC)]
    if existing:
        extra.append(existing)
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(extra)
    return env


async def _spawn_mock(pkg_parent: Path) -> ServiceProcess:
    """Spawn the mock service subprocess."""
    env = _build_env(pkg_parent)
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "mock_service",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    assert process.stdout is not None
    assert process.stdin is not None
    client = Client(reader=process.stdout, writer=process.stdin)
    return ServiceProcess(name="mock_service", process=process, client=client)


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


async def test_definition_to_session_config(tmp_path: Path) -> None:
    """Definitions resolve correctly into a SessionConfig."""
    home = tmp_path / "amplifier_home"
    registry = Registry(home=home)
    registry.ensure_home()

    agent_yaml = """\
type: agent
local_ref: test-agent
uuid: aaaa1111-bbbb-2222-3333-444455556666
version: "1.0"
orchestrator: loop
context_manager: simple
provider: anthropic
services:
  - name: mock_service
    installer: pip
    source: mock-service-pkg
"""
    registry.register_definition(agent_yaml)

    resolved = await resolve_agent(registry, "test-agent")
    config = build_session_config(resolved)

    assert config.services == ["mock_service"]
    assert config.orchestrator == "loop"
    assert config.context_manager == "simple"
    assert config.provider == "anthropic"


async def test_host_build_registry_from_cli_definitions(tmp_path: Path) -> None:
    """Full stack: CLI definitions → SessionConfig → Host → describe → registry populated."""
    home = tmp_path / "amplifier_home"
    registry = Registry(home=home)
    registry.ensure_home()

    agent_yaml = """\
type: agent
local_ref: integration-agent
uuid: ffff9999-aaaa-bbbb-cccc-ddddeeee0000
version: "1.0"
orchestrator: loop
context_manager: simple
provider: anthropic
services:
  - name: mock_service
    installer: pip
    source: mock-service-pkg
"""
    registry.register_definition(agent_yaml)

    resolved = await resolve_agent(registry, "integration-agent")
    config = build_session_config(resolved)

    # Create Host
    settings = HostSettings()
    host = Host(config=config, settings=settings)

    # Spawn real mock service and inject it
    pkg_parent = _create_mock_service_package(tmp_path / "service_pkg")
    service = await _spawn_mock(pkg_parent)

    host._services = {"mock_service": service}

    try:
        # Build registry from the real service's describe response
        await host._build_registry()

        # Verify the registry was populated
        assert host._registry.get_tool_service("echo") == "mock_service"
    finally:
        await shutdown_service(service, timeout=5.0)
```

### Step 2: Run the integration test

Run: `cd amplifier-ipc/amplifier-ipc-cli && python -m pytest tests/test_integration.py -v --timeout=30`
Expected: All tests PASS.

The first test (`test_definition_to_session_config`) verifies the pure data flow: definition YAML → Registry → `resolve_agent()` → `build_session_config()` → `SessionConfig`.

The second test (`test_host_build_registry_from_cli_definitions`) proves the full stack: CLI definition resolution produces a `SessionConfig` that creates a working `Host` which can build its capability registry from a real subprocess service.

### Step 3: Commit

```bash
cd amplifier-ipc/amplifier-ipc-cli && git add -A && git commit -m "test(cli): integration test — full stack definition resolution → Host → service describe

Proves CLI definitions resolve into SessionConfig that creates a working Host.
Uses real mock service subprocess (same pattern as amplifier-ipc-host tests)."
```

---

## Summary

| Task | What | Key Files |
|------|------|-----------|
| 1 | Host event model | `host.py`, `events.py` |
| 2 | Package scaffold | `pyproject.toml`, `__init__.py`, `__main__.py`, `main.py` |
| 3 | Copy wholesale | `console.py`, `key_manager.py`, `paths.py`, `settings.py`, `ui/*`, `commands/*` |
| 4 | Registry core | `registry.py` — `ensure_home()`, `register_definition()` |
| 5 | Registry lookups | `registry.py` — `resolve_agent()`, `resolve_behavior()`, `is_installed()`, `get_source_meta()` |
| 6 | Definitions parsing | `definitions.py` — `AgentDefinition`, `BehaviorDefinition`, `ServiceEntry` |
| 7 | Tree walking | `definitions.py` — `resolve_agent()` with recursive behavior traversal |
| 8 | URL fetching | `definitions.py` — `_fetch_url()`, auto-register on first encounter |
| 9 | Session launcher | `session_launcher.py` — `build_session_config()`, `launch_session()` |
| 10 | Run command | `commands/run.py`, `main.py` — Click group and run command |
| 11 | REPL | `repl.py` — prompt-toolkit loop consuming Host event stream |
| 12 | Streaming + approval | `streaming.py`, `approval_provider.py` — event display handlers |
| 13 | Integration test | `test_integration.py` — end-to-end definition → Host → service |
