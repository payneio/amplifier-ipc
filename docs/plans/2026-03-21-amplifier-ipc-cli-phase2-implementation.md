# amplifier-ipc CLI Phase 2 Implementation Plan

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Add management commands (discover, register, install, update), session spawning for agent delegation, session management (list/show/delete/cleanup/fork), and wire all commands into the CLI.

**Architecture:** Phase 1 delivered a working `amplifier-ipc run --agent foundation` with registry, definitions, session launcher, REPL, and streaming. Phase 2 builds on top: management commands manipulate `$AMPLIFIER_HOME` (definitions, aliases, environments), the session spawner creates child Host instances for agent delegation, and session management commands read/write the persistence layer (JSONL transcripts + metadata.json). All new commands are wired into `main.py`'s Click group.

**Tech Stack:** Python 3.11+, hatchling build, Click CLI, Rich console, PyYAML, pytest + pytest-asyncio, subprocess (for `uv` venv creation).

**Assumes Phase 1 complete:** The CLI package exists at `amplifier-ipc/amplifier-ipc-cli/`. The following modules are functional: `registry.py`, `definitions.py`, `session_launcher.py`, `repl.py`, `streaming.py`, `approval_provider.py`, `main.py` (Click group with `run`, `version`, `allowed-dirs`, `denied-dirs`, `notify` commands), and all `ui/` modules.

---

## Task 1: Discover Command

Create `amplifier-ipc discover <location> [--register] [--install]` — scans a location for agent/behavior YAML files.

**Files:**
- Create: `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/commands/discover.py`
- Test: `amplifier-ipc/amplifier-ipc-cli/tests/test_commands/test_discover.py`

### Step 1: Write the failing tests

Create `amplifier-ipc/amplifier-ipc-cli/tests/test_commands/test_discover.py`:

```python
"""Tests for the discover command."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from amplifier_ipc_cli.commands.discover import discover, scan_location


# ---------------------------------------------------------------------------
# scan_location (pure logic)
# ---------------------------------------------------------------------------

_AGENT_YAML = """\
type: agent
local_ref: test-agent
uuid: aaaa1111-bbbb-2222-3333-444455556666
version: "1.0"
description: A test agent
orchestrator: streaming
context_manager: simple
services:
  - name: test-service
    installer: pip
    source: test-pkg
"""

_BEHAVIOR_YAML = """\
type: behavior
local_ref: test-behavior
uuid: cccc3333-dddd-4444-5555-666677778888
version: "1.0"
description: A test behavior
tools:
  - name: bash
services:
  - name: test-service
    installer: pip
    source: test-pkg
"""

_NOT_A_DEFINITION = """\
name: some-config
settings:
  key: value
"""


def test_scan_location_finds_agent_yaml(tmp_path: Path) -> None:
    """scan_location() finds YAML files with 'type: agent' at top level."""
    (tmp_path / "agent.yaml").write_text(_AGENT_YAML)
    (tmp_path / "config.yaml").write_text(_NOT_A_DEFINITION)

    results = scan_location(str(tmp_path))

    assert len(results) == 1
    assert results[0]["type"] == "agent"
    assert results[0]["local_ref"] == "test-agent"


def test_scan_location_finds_behavior_yaml(tmp_path: Path) -> None:
    """scan_location() finds YAML files with 'type: behavior' at top level."""
    (tmp_path / "behavior.yaml").write_text(_BEHAVIOR_YAML)

    results = scan_location(str(tmp_path))

    assert len(results) == 1
    assert results[0]["type"] == "behavior"
    assert results[0]["local_ref"] == "test-behavior"


def test_scan_location_finds_multiple(tmp_path: Path) -> None:
    """scan_location() returns all agent/behavior definitions found."""
    (tmp_path / "agent.yaml").write_text(_AGENT_YAML)
    (tmp_path / "behavior.yaml").write_text(_BEHAVIOR_YAML)
    (tmp_path / "config.yaml").write_text(_NOT_A_DEFINITION)

    results = scan_location(str(tmp_path))

    types = {r["type"] for r in results}
    assert types == {"agent", "behavior"}


def test_scan_location_empty_directory(tmp_path: Path) -> None:
    """scan_location() returns empty list for directory with no definitions."""
    results = scan_location(str(tmp_path))
    assert results == []


def test_scan_location_recurses_subdirectories(tmp_path: Path) -> None:
    """scan_location() searches subdirectories for definitions."""
    sub = tmp_path / "services" / "foundation"
    sub.mkdir(parents=True)
    (sub / "agent.yaml").write_text(_AGENT_YAML)

    results = scan_location(str(tmp_path))

    assert len(results) == 1
    assert results[0]["local_ref"] == "test-agent"


# ---------------------------------------------------------------------------
# discover Click command
# ---------------------------------------------------------------------------


def test_discover_local_path(tmp_path: Path) -> None:
    """discover <local_path> reports found definitions."""
    (tmp_path / "agent.yaml").write_text(_AGENT_YAML)

    runner = CliRunner()
    result = runner.invoke(discover, [str(tmp_path)])

    assert result.exit_code == 0
    assert "test-agent" in result.output


def test_discover_with_register(tmp_path: Path) -> None:
    """discover --register caches definitions to the registry."""
    (tmp_path / "agent.yaml").write_text(_AGENT_YAML)

    home = tmp_path / "amp_home"
    runner = CliRunner()
    result = runner.invoke(
        discover, [str(tmp_path), "--register", "--home", str(home)]
    )

    assert result.exit_code == 0
    assert "Registered" in result.output
    # Alias file should have the agent
    assert (home / "agents.yaml").exists()


def test_discover_no_definitions(tmp_path: Path) -> None:
    """discover on empty directory reports nothing found."""
    runner = CliRunner()
    result = runner.invoke(discover, [str(tmp_path)])

    assert result.exit_code == 0
    assert "No" in result.output or "0" in result.output
```

### Step 2: Run tests to verify they fail

Run: `cd amplifier-ipc/amplifier-ipc-cli && python -m pytest tests/test_commands/test_discover.py -v`
Expected: FAIL with `ImportError: cannot import name 'discover' from 'amplifier_ipc_cli.commands.discover'`

### Step 3: Implement the discover command

Create `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/commands/discover.py`:

```python
"""Discover command — scan a location for agent/behavior definitions.

Scans a local path (or cloned git repository) for YAML files that contain
``type: agent`` or ``type: behavior`` at the top level. Reports what was
found, and optionally registers and/or installs each definition.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

import click
import yaml

from amplifier_ipc_cli.console import console

logger = logging.getLogger(__name__)


def scan_location(location: str) -> list[dict[str, Any]]:
    """Scan a filesystem path for agent/behavior definition YAML files.

    Recursively walks *location* looking for ``.yaml`` / ``.yml`` files
    whose parsed content has a ``type`` key equal to ``"agent"`` or
    ``"behavior"``.

    Args:
        location: Local filesystem path to scan.

    Returns:
        A list of dicts, each containing at minimum ``type``, ``local_ref``,
        and ``path`` (the absolute path to the YAML file).
    """
    root = Path(location)
    if not root.is_dir():
        return []

    results: list[dict[str, Any]] = []
    for yaml_path in sorted(root.rglob("*.yaml")):
        _try_parse_definition(yaml_path, results)
    for yaml_path in sorted(root.rglob("*.yml")):
        _try_parse_definition(yaml_path, results)

    return results


def _try_parse_definition(
    yaml_path: Path, results: list[dict[str, Any]]
) -> None:
    """Parse a YAML file and append to results if it's a definition."""
    try:
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError):
        return

    if not isinstance(data, dict):
        return

    def_type = data.get("type")
    if def_type not in ("agent", "behavior"):
        return

    local_ref = data.get("local_ref", "")
    results.append(
        {
            "type": def_type,
            "local_ref": local_ref,
            "path": str(yaml_path.resolve()),
            "raw_content": yaml_path.read_text(encoding="utf-8"),
        }
    )


def _clone_git_location(location: str) -> Path:
    """Clone a git URL to a temporary directory and return the path.

    Supports ``git+https://...`` and ``https://...`` URLs.
    For URLs with ``#subdirectory=/path``, returns the subdirectory.
    """
    import subprocess

    # Strip git+ prefix
    url = location.removeprefix("git+")

    # Handle #subdirectory= fragment
    subdirectory = ""
    if "#subdirectory=" in url:
        url, subdirectory = url.rsplit("#subdirectory=", 1)

    tmp_dir = Path(tempfile.mkdtemp(prefix="amplifier-discover-"))
    subprocess.run(
        ["git", "clone", "--depth=1", url, str(tmp_dir / "repo")],
        check=True,
        capture_output=True,
    )

    clone_path = tmp_dir / "repo"
    if subdirectory:
        clone_path = clone_path / subdirectory.lstrip("/")

    return clone_path


@click.command()
@click.argument("location")
@click.option("--register", is_flag=True, help="Register found definitions.")
@click.option("--install", is_flag=True, help="Also install registered definitions.")
@click.option(
    "--home",
    default=None,
    help="Override $AMPLIFIER_HOME path (for testing).",
)
def discover(
    location: str,
    register: bool,
    install: bool,
    home: str | None,
) -> None:
    """Scan a location for agent and behavior definitions.

    LOCATION can be a local path or a git URL
    (e.g., git+https://github.com/org/repo@main#subdirectory=/services).

    Examples:

        amplifier-ipc discover ./services/
        amplifier-ipc discover ./services/ --register
        amplifier-ipc discover git+https://github.com/org/repo@main --register --install
    """
    # Handle git URLs
    scan_path: str
    if location.startswith("git+") or (
        location.startswith("https://") and "github" in location
    ):
        try:
            console.print(f"[dim]Cloning {location}...[/dim]")
            clone_path = _clone_git_location(location)
            scan_path = str(clone_path)
        except Exception as exc:
            console.print(f"[red]Error cloning repository:[/red] {exc}")
            return
    else:
        scan_path = location

    results = scan_location(scan_path)

    if not results:
        console.print("No agent or behavior definitions found.")
        return

    # Report findings
    console.print(f"Found {len(results)} definition(s):")
    for item in results:
        console.print(
            f"  [{item['type']}] {item['local_ref']}  ({item['path']})"
        )

    # Register if requested
    if register:
        from amplifier_ipc_cli.registry import Registry

        home_path = Path(home) if home else None
        registry = Registry(home=home_path)
        registry.ensure_home()

        for item in results:
            try:
                def_id = registry.register_definition(item["raw_content"])
                console.print(f"  Registered: {item['local_ref']} → {def_id}")
            except Exception as exc:
                console.print(
                    f"  [red]Error registering {item['local_ref']}:[/red] {exc}"
                )

    if install and register:
        console.print(
            "[yellow]Install not yet implemented — "
            "use `amplifier-ipc install <agent>` manually.[/yellow]"
        )
```

### Step 4: Run the tests

Run: `cd amplifier-ipc/amplifier-ipc-cli && python -m pytest tests/test_commands/test_discover.py -v`
Expected: All tests PASS.

### Step 5: Commit

```bash
cd amplifier-ipc/amplifier-ipc-cli && git add -A && git commit -m "feat(cli): discover command — scan locations for agent/behavior definitions

amplifier-ipc discover <location> [--register] [--install]
Scans local paths and git URLs for YAML files with type: agent/behavior.
Optionally registers definitions to \$AMPLIFIER_HOME."
```

---

## Task 2: Register Command

Create `amplifier-ipc register <path> [--install]` — register a single definition file.

**Files:**
- Create: `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/commands/register.py`
- Test: `amplifier-ipc/amplifier-ipc-cli/tests/test_commands/test_register.py`

### Step 1: Write the failing tests

Create `amplifier-ipc/amplifier-ipc-cli/tests/test_commands/test_register.py`:

```python
"""Tests for the register command."""

from __future__ import annotations

from pathlib import Path

import yaml
from click.testing import CliRunner

from amplifier_ipc_cli.commands.register import register


_AGENT_YAML = """\
type: agent
local_ref: reg-agent
uuid: aaaa1111-bbbb-2222-3333-444455556666
version: "1.0"
orchestrator: streaming
context_manager: simple
services:
  - name: test-service
    installer: pip
    source: test-pkg
"""


def test_register_local_file(tmp_path: Path) -> None:
    """register <path> reads the file and registers it."""
    yaml_file = tmp_path / "agent.yaml"
    yaml_file.write_text(_AGENT_YAML)

    home = tmp_path / "amp_home"
    runner = CliRunner()
    result = runner.invoke(register, [str(yaml_file), "--home", str(home)])

    assert result.exit_code == 0
    assert "Registered" in result.output

    # Verify it's in the alias file
    aliases = yaml.safe_load((home / "agents.yaml").read_text())
    assert "reg-agent" in aliases


def test_register_nonexistent_file(tmp_path: Path) -> None:
    """register with a nonexistent path shows an error."""
    runner = CliRunner()
    result = runner.invoke(register, [str(tmp_path / "nope.yaml")])

    assert result.exit_code != 0 or "Error" in result.output or "not found" in result.output.lower()


def test_register_invalid_yaml(tmp_path: Path) -> None:
    """register with invalid YAML shows an error."""
    bad_file = tmp_path / "bad.yaml"
    bad_file.write_text("not: a: valid: definition")

    home = tmp_path / "amp_home"
    runner = CliRunner()
    result = runner.invoke(register, [str(bad_file), "--home", str(home)])

    assert "Error" in result.output or "error" in result.output.lower()


_BEHAVIOR_YAML = """\
type: behavior
local_ref: reg-behavior
uuid: dddd4444-eeee-5555-6666-777788889999
version: "1.0"
tools:
  - name: bash
services:
  - name: test-service
    installer: pip
    source: test-pkg
"""


def test_register_behavior(tmp_path: Path) -> None:
    """register correctly handles behavior definitions."""
    yaml_file = tmp_path / "behavior.yaml"
    yaml_file.write_text(_BEHAVIOR_YAML)

    home = tmp_path / "amp_home"
    runner = CliRunner()
    result = runner.invoke(register, [str(yaml_file), "--home", str(home)])

    assert result.exit_code == 0
    assert "Registered" in result.output

    aliases = yaml.safe_load((home / "behaviors.yaml").read_text())
    assert "reg-behavior" in aliases
```

### Step 2: Run tests to verify they fail

Run: `cd amplifier-ipc/amplifier-ipc-cli && python -m pytest tests/test_commands/test_register.py -v`
Expected: FAIL with `ImportError`

### Step 3: Implement the register command

Create `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/commands/register.py`:

```python
"""Register command — cache a single agent/behavior definition to $AMPLIFIER_HOME."""

from __future__ import annotations

import logging
from pathlib import Path

import click

from amplifier_ipc_cli.console import console

logger = logging.getLogger(__name__)


def _read_definition(fsspec: str) -> str:
    """Read a definition from a local path or URL.

    Args:
        fsspec: Local file path or HTTP(S) URL.

    Returns:
        Raw YAML content as a string.

    Raises:
        FileNotFoundError: If the local path does not exist.
        Exception: On HTTP fetch errors.
    """
    if fsspec.startswith("http://") or fsspec.startswith("https://"):
        import urllib.request

        with urllib.request.urlopen(fsspec, timeout=30) as resp:  # noqa: S310
            return resp.read().decode("utf-8")

    path = Path(fsspec)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {fsspec}")
    return path.read_text(encoding="utf-8")


@click.command()
@click.argument("fsspec")
@click.option("--install", is_flag=True, help="Also install the service after registration.")
@click.option(
    "--home",
    default=None,
    help="Override $AMPLIFIER_HOME path (for testing).",
)
def register(fsspec: str, install: bool, home: str | None) -> None:
    """Register a single agent or behavior definition.

    FSSPEC can be a local file path or a URL.

    Examples:

        amplifier-ipc register ./agent.yaml
        amplifier-ipc register https://example.com/behavior.yaml --install
    """
    from amplifier_ipc_cli.registry import Registry

    try:
        yaml_content = _read_definition(fsspec)
    except FileNotFoundError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        return
    except Exception as exc:
        console.print(f"[red]Error reading definition:[/red] {exc}")
        return

    home_path = Path(home) if home else None
    registry = Registry(home=home_path)
    registry.ensure_home()

    # Determine source_url for remote sources
    source_url: str | None = None
    if fsspec.startswith("http://") or fsspec.startswith("https://"):
        source_url = fsspec

    try:
        definition_id = registry.register_definition(
            yaml_content, source_url=source_url
        )
        console.print(f"Registered: {definition_id}")
    except Exception as exc:
        console.print(f"[red]Error registering definition:[/red] {exc}")
        return

    if install:
        console.print(
            "[yellow]Install not yet wired — "
            "use `amplifier-ipc install` separately.[/yellow]"
        )
```

### Step 4: Run the tests

Run: `cd amplifier-ipc/amplifier-ipc-cli && python -m pytest tests/test_commands/test_register.py -v`
Expected: All tests PASS.

### Step 5: Commit

```bash
cd amplifier-ipc/amplifier-ipc-cli && git add -A && git commit -m "feat(cli): register command — cache a single definition to \$AMPLIFIER_HOME"
```

---

## Task 3: Install Command

Create `amplifier-ipc install <agent_or_behavior>` — resolve a name via registry, create a virtualenv, install the service.

**Files:**
- Create: `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/commands/install.py`
- Test: `amplifier-ipc/amplifier-ipc-cli/tests/test_commands/test_install.py`

### Step 1: Write the failing tests

Create `amplifier-ipc/amplifier-ipc-cli/tests/test_commands/test_install.py`:

```python
"""Tests for the install command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml
from click.testing import CliRunner

from amplifier_ipc_cli.commands.install import install, install_service
from amplifier_ipc_cli.registry import Registry


# ---------------------------------------------------------------------------
# Sample definitions
# ---------------------------------------------------------------------------

_AGENT_YAML = """\
type: agent
local_ref: inst-agent
uuid: aaaa1111-bbbb-2222-3333-444455556666
version: "1.0"
orchestrator: streaming
context_manager: simple
services:
  - name: inst-service
    installer: pip
    source: inst-service-pkg
"""


# ---------------------------------------------------------------------------
# install_service (unit)
# ---------------------------------------------------------------------------


def test_install_service_creates_venv(tmp_path: Path) -> None:
    """install_service() calls uv to create a venv and install."""
    registry = Registry(home=tmp_path)
    registry.ensure_home()
    def_id = registry.register_definition(_AGENT_YAML)

    with patch("amplifier_ipc_cli.commands.install._run_uv") as mock_uv:
        mock_uv.return_value = None  # Success
        install_service(registry, def_id, "inst-service-pkg")

    # uv should have been called twice: venv creation and pip install
    assert mock_uv.call_count == 2

    # First call: create the venv
    first_call_args = mock_uv.call_args_list[0]
    assert "venv" in str(first_call_args)

    # Second call: install the package
    second_call_args = mock_uv.call_args_list[1]
    assert "pip" in str(second_call_args) and "install" in str(second_call_args)


def test_install_service_already_installed(tmp_path: Path) -> None:
    """install_service() skips if already installed."""
    registry = Registry(home=tmp_path)
    registry.ensure_home()
    def_id = registry.register_definition(_AGENT_YAML)

    # Fake an existing environment
    env_path = registry.get_environment_path(def_id)
    env_path.mkdir(parents=True)

    with patch("amplifier_ipc_cli.commands.install._run_uv") as mock_uv:
        install_service(registry, def_id, "inst-service-pkg", force=False)

    mock_uv.assert_not_called()


# ---------------------------------------------------------------------------
# install Click command
# ---------------------------------------------------------------------------


def test_install_command_unknown_name(tmp_path: Path) -> None:
    """install <unknown> shows an error."""
    runner = CliRunner()
    result = runner.invoke(install, ["nonexistent", "--home", str(tmp_path)])

    assert "not found" in result.output.lower() or "Error" in result.output


def test_install_command_calls_install_service(tmp_path: Path) -> None:
    """install <name> resolves and installs the agent's services."""
    registry = Registry(home=tmp_path)
    registry.ensure_home()
    registry.register_definition(_AGENT_YAML)

    with patch("amplifier_ipc_cli.commands.install._run_uv"):
        runner = CliRunner()
        result = runner.invoke(install, ["inst-agent", "--home", str(tmp_path)])

    assert result.exit_code == 0
    assert "Install" in result.output or "install" in result.output.lower()
```

### Step 2: Run tests to verify they fail

Run: `cd amplifier-ipc/amplifier-ipc-cli && python -m pytest tests/test_commands/test_install.py -v`
Expected: FAIL with `ImportError`

### Step 3: Implement the install command

Create `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/commands/install.py`:

```python
"""Install command — create virtualenvs and install service dependencies.

Resolves an agent or behavior name via the registry, reads the definition's
``services`` section, and for each service creates a virtualenv at
``$AMPLIFIER_HOME/environments/<ID>/`` using ``uv``.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any

import click
import yaml

from amplifier_ipc_cli.console import console

logger = logging.getLogger(__name__)


def _run_uv(args: list[str]) -> None:
    """Run a uv command, raising on failure.

    Args:
        args: Arguments to pass to ``uv`` (e.g. ``["venv", "--python", ...]``).

    Raises:
        subprocess.CalledProcessError: If the command exits with a non-zero code.
    """
    cmd = ["uv", *args]
    logger.debug("Running: %s", " ".join(cmd))
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def install_service(
    registry: Any,
    definition_id: str,
    source: str,
    *,
    force: bool = False,
) -> None:
    """Create a virtualenv for a definition and install the package.

    Args:
        registry: The Registry instance.
        definition_id: The definition ID (used for the environment directory name).
        source: pip-installable source string.
        force: If True, reinstall even if environment already exists.
    """
    if not force and registry.is_installed(definition_id):
        logger.info("Already installed: %s", definition_id)
        return

    env_path = registry.get_environment_path(definition_id)
    python_path = env_path / "bin" / "python"

    console.print(f"  [dim]Creating virtualenv: {env_path}[/dim]")
    _run_uv(["venv", str(env_path)])

    console.print(f"  [dim]Installing: {source}[/dim]")
    _run_uv(["pip", "install", "--python", str(python_path), source])


@click.command()
@click.argument("name")
@click.option("--force", is_flag=True, help="Reinstall even if already installed.")
@click.option(
    "--home",
    default=None,
    help="Override $AMPLIFIER_HOME path (for testing).",
)
def install(name: str, force: bool, home: str | None) -> None:
    """Install service dependencies for an agent or behavior.

    NAME is the registered agent or behavior name.

    Creates a virtualenv at $AMPLIFIER_HOME/environments/<ID>/ and installs
    the service's pip dependencies using uv.

    Examples:

        amplifier-ipc install foundation
        amplifier-ipc install amplifier-dev --force
    """
    from amplifier_ipc_cli.registry import Registry

    home_path = Path(home) if home else None
    registry = Registry(home=home_path)
    registry.ensure_home()

    # Try agent first, then behavior
    def_path = None
    try:
        def_path = registry.resolve_agent(name)
    except FileNotFoundError:
        try:
            def_path = registry.resolve_behavior(name)
        except FileNotFoundError:
            console.print(
                f"[red]Error:[/red] '{name}' not found as agent or behavior. "
                f"Run `amplifier-ipc discover` first."
            )
            return

    # Read definition to get services
    data: dict[str, Any] = yaml.safe_load(def_path.read_text()) or {}
    services = data.get("services", [])
    definition_id = def_path.stem  # filename without .yaml

    if not services:
        console.print(f"No services defined for '{name}'.")
        return

    console.print(f"Installing services for '{name}' ({definition_id}):")

    for svc in services:
        svc_name = svc.get("name", "unknown")
        svc_source = svc.get("source", "")
        if not svc_source:
            console.print(f"  [yellow]Skipping {svc_name}: no source defined[/yellow]")
            continue

        try:
            install_service(registry, definition_id, svc_source, force=force)
            console.print(f"  Installed: {svc_name}")
        except Exception as exc:
            console.print(f"  [red]Error installing {svc_name}:[/red] {exc}")
```

### Step 4: Run the tests

Run: `cd amplifier-ipc/amplifier-ipc-cli && python -m pytest tests/test_commands/test_install.py -v`
Expected: All tests PASS.

### Step 5: Commit

```bash
cd amplifier-ipc/amplifier-ipc-cli && git add -A && git commit -m "feat(cli): install command — create venvs and install service dependencies via uv"
```

---

## Task 4: Update Command

Create `amplifier-ipc update <agent> [--check]` — re-fetch behavior URLs and update cached definitions.

**Files:**
- Create: `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/commands/update.py`
- Test: `amplifier-ipc/amplifier-ipc-cli/tests/test_commands/test_update.py`

### Step 1: Write the failing tests

Create `amplifier-ipc/amplifier-ipc-cli/tests/test_commands/test_update.py`:

```python
"""Tests for the update command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import yaml
from click.testing import CliRunner

from amplifier_ipc_cli.commands.update import check_for_updates
from amplifier_ipc_cli.registry import Registry


# ---------------------------------------------------------------------------
# Sample definitions with _meta blocks
# ---------------------------------------------------------------------------

_BEHAVIOR_YAML = """\
type: behavior
local_ref: updatable-beh
uuid: bbbb2222-cccc-3333-4444-555566667777
version: "1.0"
services:
  - name: test-service
    installer: pip
    source: test-pkg
"""

_AGENT_YAML = """\
type: agent
local_ref: updatable-agent
uuid: aaaa1111-bbbb-2222-3333-444455556666
version: "1.0"
orchestrator: streaming
context_manager: simple
behaviors:
  - name: updatable-beh
services:
  - name: test-service
    installer: pip
    source: test-pkg
"""


# ---------------------------------------------------------------------------
# check_for_updates (unit)
# ---------------------------------------------------------------------------


def test_check_for_updates_no_meta(tmp_path: Path) -> None:
    """Definitions without _meta are skipped (no source URL to check)."""
    registry = Registry(home=tmp_path)
    registry.ensure_home()
    registry.register_definition(_AGENT_YAML)
    registry.register_definition(_BEHAVIOR_YAML)

    results = check_for_updates(registry, "updatable-agent")

    # No _meta blocks → nothing to check
    assert len(results) == 0


def test_check_for_updates_with_unchanged_meta(tmp_path: Path) -> None:
    """Definitions with _meta whose hash hasn't changed report no updates."""
    registry = Registry(home=tmp_path)
    registry.ensure_home()

    # Register with a source URL to get a _meta block
    registry.register_definition(_AGENT_YAML)
    def_id = registry.register_definition(
        _BEHAVIOR_YAML, source_url="https://example.com/beh.yaml"
    )

    # Mock fetch returning the exact same content → same hash
    with patch(
        "amplifier_ipc_cli.commands.update._fetch_url_sync",
        return_value=_BEHAVIOR_YAML,
    ):
        results = check_for_updates(registry, "updatable-agent")

    assert len(results) == 1
    assert results[0]["changed"] is False


def test_check_for_updates_with_changed_meta(tmp_path: Path) -> None:
    """Definitions whose upstream content changed are reported."""
    registry = Registry(home=tmp_path)
    registry.ensure_home()

    registry.register_definition(_AGENT_YAML)
    registry.register_definition(
        _BEHAVIOR_YAML, source_url="https://example.com/beh.yaml"
    )

    # Return different content → different hash
    modified_yaml = _BEHAVIOR_YAML.replace('version: "1.0"', 'version: "2.0"')
    with patch(
        "amplifier_ipc_cli.commands.update._fetch_url_sync",
        return_value=modified_yaml,
    ):
        results = check_for_updates(registry, "updatable-agent")

    assert len(results) == 1
    assert results[0]["changed"] is True
```

### Step 2: Run tests to verify they fail

Run: `cd amplifier-ipc/amplifier-ipc-cli && python -m pytest tests/test_commands/test_update.py -v`
Expected: FAIL with `ImportError`

### Step 3: Implement the update command

Create `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/commands/update.py`:

```python
"""Update command — re-fetch behavior URLs and compare against cached hashes.

Walks an agent's behavior tree, finds behaviors with ``_meta.source_url``,
re-fetches each URL, and compares the SHA-256 hash. Reports changes and
optionally applies updates.
"""

from __future__ import annotations

import hashlib
import logging
import urllib.request
from pathlib import Path
from typing import Any

import click
import yaml

from amplifier_ipc_cli.console import console

logger = logging.getLogger(__name__)


def _fetch_url_sync(url: str) -> str:
    """Fetch a URL synchronously and return content as string."""
    with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310
        return resp.read().decode("utf-8")


def check_for_updates(
    registry: Any,
    agent_name: str,
) -> list[dict[str, Any]]:
    """Walk the agent's behavior tree and check for upstream changes.

    Args:
        registry: The Registry instance.
        agent_name: Human-readable agent name.

    Returns:
        A list of dicts with keys: ``definition_id``, ``local_ref``,
        ``source_url``, ``changed`` (bool), ``old_hash``, ``new_hash``.
    """
    # Resolve agent to find its behaviors
    agent_path = registry.resolve_agent(agent_name)
    agent_data = yaml.safe_load(agent_path.read_text()) or {}

    results: list[dict[str, Any]] = []
    visited: set[str] = set()

    def _check_behavior(name: str) -> None:
        if name in visited:
            return
        visited.add(name)

        try:
            beh_path = registry.resolve_behavior(name)
        except FileNotFoundError:
            return

        beh_data = yaml.safe_load(beh_path.read_text()) or {}
        definition_id = beh_path.stem

        # Check _meta block
        meta = beh_data.get("_meta")
        if meta and meta.get("source_url"):
            source_url = meta["source_url"]
            old_hash = meta.get("source_hash", "")

            try:
                new_content = _fetch_url_sync(source_url)
                raw_hash = hashlib.sha256(new_content.encode()).hexdigest()
                new_hash = f"sha256:{raw_hash}"
                changed = old_hash != new_hash
            except Exception as exc:
                logger.warning(
                    "Failed to fetch %s: %s", source_url, exc
                )
                new_hash = "fetch_failed"
                changed = False

            results.append(
                {
                    "definition_id": definition_id,
                    "local_ref": name,
                    "source_url": source_url,
                    "changed": changed,
                    "old_hash": old_hash,
                    "new_hash": new_hash,
                    "new_content": new_content if changed else None,
                }
            )

        # Recurse into nested behaviors
        for nested in beh_data.get("behaviors", []):
            nested_name = nested.get("name", "") if isinstance(nested, dict) else ""
            if nested_name:
                _check_behavior(nested_name)

    # Walk behaviors from the agent definition
    for beh_ref in agent_data.get("behaviors", []):
        beh_name = beh_ref.get("name", "") if isinstance(beh_ref, dict) else ""
        if beh_name:
            _check_behavior(beh_name)

    return results


@click.command()
@click.argument("agent")
@click.option("--check", is_flag=True, help="Dry-run: report changes without applying.")
@click.option(
    "--home",
    default=None,
    help="Override $AMPLIFIER_HOME path (for testing).",
)
def update(agent: str, check: bool, home: str | None) -> None:
    """Check for and apply updates to an agent's behavior definitions.

    Walks the agent's behavior tree, re-fetches URLs for behaviors that
    have a _meta.source_url, and compares SHA-256 hashes.

    Examples:

        amplifier-ipc update foundation --check
        amplifier-ipc update foundation
    """
    from amplifier_ipc_cli.registry import Registry

    home_path = Path(home) if home else None
    registry = Registry(home=home_path)
    registry.ensure_home()

    try:
        results = check_for_updates(registry, agent)
    except FileNotFoundError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        return

    if not results:
        console.print("No behaviors with remote sources found.")
        return

    changed_count = sum(1 for r in results if r["changed"])

    for item in results:
        status = "[green]changed[/green]" if item["changed"] else "[dim]unchanged[/dim]"
        console.print(f"  {item['local_ref']}: {status}")
        if item["changed"]:
            console.print(f"    URL: {item['source_url']}")
            console.print(f"    Old: {item['old_hash'][:30]}...")
            console.print(f"    New: {item['new_hash'][:30]}...")

    if check:
        console.print(
            f"\n[bold]{changed_count} of {len(results)} behavior(s) have upstream changes.[/bold]"
        )
        console.print("[dim]Run without --check to apply updates.[/dim]")
        return

    # Apply updates
    if changed_count == 0:
        console.print("\nAll behaviors are up to date.")
        return

    for item in results:
        if item["changed"] and item.get("new_content"):
            try:
                registry.register_definition(
                    item["new_content"], source_url=item["source_url"]
                )
                console.print(f"  Updated: {item['local_ref']}")
            except Exception as exc:
                console.print(
                    f"  [red]Error updating {item['local_ref']}:[/red] {exc}"
                )

    console.print(f"\nUpdated {changed_count} behavior(s).")
```

### Step 4: Run the tests

Run: `cd amplifier-ipc/amplifier-ipc-cli && python -m pytest tests/test_commands/test_update.py -v`
Expected: All tests PASS.

### Step 5: Commit

```bash
cd amplifier-ipc/amplifier-ipc-cli && git add -A && git commit -m "feat(cli): update command — re-fetch behavior URLs, compare hashes, apply updates

amplifier-ipc update <agent> [--check]
Walks behavior tree, re-fetches source URLs, compares SHA-256 hashes.
--check does dry-run only."
```

---

## Task 5: Session Spawner

Create the thin session spawner for agent delegation. When the orchestrator's `delegate` tool fires, the CLI intercepts and creates a child Host instance.

**Files:**
- Create: `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/session_spawner.py`
- Test: `amplifier-ipc/amplifier-ipc-cli/tests/test_session_spawner.py`

### Step 1: Write the failing tests

Create `amplifier-ipc/amplifier-ipc-cli/tests/test_session_spawner.py`:

```python
"""Tests for the session spawner — agent delegation via child Host instances."""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from amplifier_ipc_cli.session_spawner import (
    SpawnRequest,
    generate_sub_session_id,
    merge_child_config,
    spawn_sub_session,
)
from amplifier_ipc_host.config import HostSettings, SessionConfig


# ---------------------------------------------------------------------------
# generate_sub_session_id
# ---------------------------------------------------------------------------


def test_generate_sub_session_id_format() -> None:
    """Sub-session IDs contain the parent ID, safe agent name, and hex suffix."""
    result = generate_sub_session_id("parent123", "foundation:explorer")
    parts = result.split("_")
    assert parts[0] == "parent123"
    assert "foundation" in result
    assert "explorer" in result
    assert len(parts) >= 3


def test_generate_sub_session_id_uniqueness() -> None:
    """Two calls with the same inputs produce different IDs."""
    id1 = generate_sub_session_id("p1", "agent-a")
    id2 = generate_sub_session_id("p1", "agent-a")
    assert id1 != id2


# ---------------------------------------------------------------------------
# merge_child_config
# ---------------------------------------------------------------------------


def test_merge_child_config_inherits_parent_services() -> None:
    """Child config inherits parent's service list when child adds none."""
    parent = SessionConfig(
        services=["svc-a", "svc-b"],
        orchestrator="streaming",
        context_manager="simple",
        provider="anthropic",
    )
    child_services: list[str] = []

    merged = merge_child_config(parent, child_services, orchestrator=None)

    assert merged.services == ["svc-a", "svc-b"]
    assert merged.orchestrator == "streaming"


def test_merge_child_config_adds_child_services() -> None:
    """Child services are appended (deduplicated) to parent services."""
    parent = SessionConfig(
        services=["svc-a"],
        orchestrator="streaming",
        context_manager="simple",
        provider="anthropic",
    )
    child_services = ["svc-a", "svc-c"]

    merged = merge_child_config(parent, child_services, orchestrator=None)

    assert "svc-a" in merged.services
    assert "svc-c" in merged.services
    assert merged.services.count("svc-a") == 1  # deduplicated


def test_merge_child_config_overrides_orchestrator() -> None:
    """Child can override the orchestrator."""
    parent = SessionConfig(
        services=["svc-a"],
        orchestrator="streaming",
        context_manager="simple",
        provider="anthropic",
    )

    merged = merge_child_config(parent, [], orchestrator="batch")

    assert merged.orchestrator == "batch"


# ---------------------------------------------------------------------------
# spawn_sub_session
# ---------------------------------------------------------------------------


_CHILD_AGENT_YAML = """\
type: agent
local_ref: explorer
uuid: dddd4444-eeee-5555-6666-777788889999
version: "1.0"
orchestrator: streaming
context_manager: simple
services:
  - name: child-service
    installer: pip
    source: child-pkg
"""


async def test_spawn_sub_session_creates_host(tmp_path: Path) -> None:
    """spawn_sub_session resolves child agent and creates a Host."""
    from amplifier_ipc_cli.registry import Registry

    registry = Registry(home=tmp_path)
    registry.ensure_home()
    registry.register_definition(_CHILD_AGENT_YAML)

    parent_config = SessionConfig(
        services=["parent-svc"],
        orchestrator="streaming",
        context_manager="simple",
        provider="anthropic",
    )

    request = SpawnRequest(
        agent_name="explorer",
        instruction="Find files",
        parent_session_id="parent123",
    )

    mock_host_cls = MagicMock()
    mock_host_instance = MagicMock()
    mock_host_cls.return_value = mock_host_instance

    # Mock host.run() as an async generator
    async def mock_run(prompt: str):
        from amplifier_ipc_host.events import CompleteEvent
        yield CompleteEvent(response="Done!")

    mock_host_instance.run = mock_run

    with patch("amplifier_ipc_cli.session_spawner.Host", mock_host_cls):
        response = await spawn_sub_session(
            request=request,
            parent_config=parent_config,
            registry=registry,
        )

    assert response == "Done!"
    mock_host_cls.assert_called_once()
```

### Step 2: Run tests to verify they fail

Run: `cd amplifier-ipc/amplifier-ipc-cli && python -m pytest tests/test_session_spawner.py -v`
Expected: FAIL with `ImportError`

### Step 3: Implement the session spawner

Create `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/session_spawner.py`:

```python
"""Session spawner — agent delegation via child Host instances.

Thin compared to amplifier-lite-cli's 574-line session_spawner. The IPC
version works with ResolvedAgent objects and SessionConfig dicts — no
ModuleRef juggling, no class-path deduplication.

Key responsibilities:
1. Resolve child agent definitions via definitions.resolve_agent()
2. Build child SessionConfig, merging parent settings with overrides
3. Create a new Host instance for the child session
4. Run the child host, collect the response
5. Return the response to the parent host
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from amplifier_ipc_host.config import HostSettings, SessionConfig
from amplifier_ipc_host.host import Host

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class SpawnRequest:
    """Data needed to spawn a child session."""

    agent_name: str
    instruction: str
    parent_session_id: str
    context_settings: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Sub-session ID generation
# ---------------------------------------------------------------------------


def generate_sub_session_id(parent_session_id: str, agent_name: str) -> str:
    """Generate a sub-session ID from parent session ID and agent name.

    Sub-session IDs contain underscores so they can be distinguished from
    top-level sessions.

    Args:
        parent_session_id: The parent session's ID.
        agent_name: Agent name (e.g., ``"foundation:explorer"``).

    Returns:
        A unique sub-session ID of the form ``{parent_id}_{safe_name}_{hex8}``.
    """
    safe_name = (
        agent_name.replace(" ", "_")
        .replace("/", "_")
        .replace(":", "_")
        .replace("-", "_")
    )
    unique_suffix = uuid.uuid4().hex[:8]
    return f"{parent_session_id}_{safe_name}_{unique_suffix}"


# ---------------------------------------------------------------------------
# Config merging
# ---------------------------------------------------------------------------


def merge_child_config(
    parent: SessionConfig,
    child_services: list[str],
    *,
    orchestrator: str | None = None,
    context_manager: str | None = None,
    provider: str | None = None,
    component_config: dict[str, Any] | None = None,
) -> SessionConfig:
    """Merge parent SessionConfig with child overrides.

    Child services are appended to parent services (deduplicated).
    Component selections (orchestrator, context_manager, provider) default
    to parent values unless overridden.

    Args:
        parent: The parent session's config.
        child_services: Additional services the child needs.
        orchestrator: Override orchestrator (or None to inherit parent).
        context_manager: Override context manager (or None to inherit).
        provider: Override provider (or None to inherit).
        component_config: Override component config (merged with parent).

    Returns:
        A new SessionConfig for the child session.
    """
    # Deduplicate services: parent list + child additions
    seen: set[str] = set()
    merged_services: list[str] = []
    for svc in parent.services + child_services:
        if svc not in seen:
            seen.add(svc)
            merged_services.append(svc)

    # Merge component config
    merged_component_config = dict(parent.component_config)
    if component_config:
        merged_component_config.update(component_config)

    return SessionConfig(
        services=merged_services,
        orchestrator=orchestrator or parent.orchestrator,
        context_manager=context_manager or parent.context_manager,
        provider=provider or parent.provider,
        component_config=merged_component_config,
    )


# ---------------------------------------------------------------------------
# Spawn
# ---------------------------------------------------------------------------


async def spawn_sub_session(
    *,
    request: SpawnRequest,
    parent_config: SessionConfig,
    registry: Any,
    settings: HostSettings | None = None,
    event_handler: Any | None = None,
    nesting_depth: int = 0,
) -> str:
    """Spawn a child session for agent delegation.

    1. Resolve the child agent's definitions.
    2. Build a child SessionConfig, merging parent settings.
    3. Create a new Host instance.
    4. Run the child host, collecting the response.
    5. Return the response string.

    Args:
        request: The spawn request with agent name, instruction, etc.
        parent_config: The parent session's config.
        registry: The Registry instance for definition resolution.
        settings: Host settings (defaults to empty HostSettings).
        event_handler: Optional callable for handling child events
            (e.g., indented streaming display). Called with (event, depth).
        nesting_depth: Display nesting depth for indentation.

    Returns:
        The child session's final response string.
    """
    from amplifier_ipc_cli.definitions import resolve_agent
    from amplifier_ipc_cli.session_launcher import build_session_config

    # 1. Resolve child agent
    resolved = await resolve_agent(registry, request.agent_name)

    # 2. Build child config
    child_session_config = build_session_config(resolved)
    merged_config = merge_child_config(
        parent_config,
        child_session_config.services,
        orchestrator=child_session_config.orchestrator or None,
        context_manager=child_session_config.context_manager or None,
        provider=child_session_config.provider or None,
        component_config=child_session_config.component_config or None,
    )

    # 3. Create child Host
    host_settings = settings or HostSettings()
    child_host = Host(config=merged_config, settings=host_settings)

    # 4. Run child host and collect response
    response = ""
    async for event in child_host.run(request.instruction):
        if event_handler is not None:
            event_handler(event, nesting_depth + 1)

        if event.type == "complete":
            response = event.response

    return response
```

### Step 4: Run the tests

Run: `cd amplifier-ipc/amplifier-ipc-cli && python -m pytest tests/test_session_spawner.py -v`
Expected: All tests PASS.

### Step 5: Commit

```bash
cd amplifier-ipc/amplifier-ipc-cli && git add -A && git commit -m "feat(cli): session spawner — thin agent delegation via child Host instances

SpawnRequest + generate_sub_session_id + merge_child_config + spawn_sub_session.
No ModuleRef juggling — works with ResolvedAgent and SessionConfig."
```

---

## Task 6: Session Management Commands

Create session list/show/delete/cleanup commands that work against the persistence layer.

**Files:**
- Create: `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/commands/session.py`
- Test: `amplifier-ipc/amplifier-ipc-cli/tests/test_commands/test_session.py`

### Step 1: Write the failing tests

Create `amplifier-ipc/amplifier-ipc-cli/tests/test_commands/test_session.py`:

```python
"""Tests for session management commands (list, show, delete, cleanup)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from click.testing import CliRunner

from amplifier_ipc_cli.commands.session import session_group


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_session(
    base_dir: Path,
    session_id: str,
    *,
    messages: list[dict] | None = None,
    metadata: dict | None = None,
) -> Path:
    """Create a fake session directory with transcript and metadata."""
    session_dir = base_dir / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    # Write transcript
    transcript_path = session_dir / "transcript.jsonl"
    if messages:
        with transcript_path.open("w") as f:
            for msg in messages:
                f.write(json.dumps(msg) + "\n")

    # Write metadata
    meta_path = session_dir / "metadata.json"
    meta = metadata or {"session_id": session_id, "status": "completed"}
    with meta_path.open("w") as f:
        json.dump(meta, f)

    return session_dir


# ---------------------------------------------------------------------------
# session list
# ---------------------------------------------------------------------------


def test_session_list_empty(tmp_path: Path) -> None:
    """session list with no sessions shows appropriate message."""
    runner = CliRunner()
    result = runner.invoke(
        session_group,
        ["list", "--sessions-dir", str(tmp_path)],
    )
    assert result.exit_code == 0
    assert "No sessions" in result.output or "no sessions" in result.output.lower()


def test_session_list_shows_sessions(tmp_path: Path) -> None:
    """session list shows stored sessions."""
    _create_session(
        tmp_path,
        "abc123def456",
        messages=[
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ],
        metadata={
            "session_id": "abc123def456",
            "name": "Test Session",
            "status": "completed",
        },
    )

    runner = CliRunner()
    result = runner.invoke(
        session_group,
        ["list", "--sessions-dir", str(tmp_path)],
    )

    assert result.exit_code == 0
    assert "abc123de" in result.output  # truncated ID


# ---------------------------------------------------------------------------
# session show
# ---------------------------------------------------------------------------


def test_session_show_displays_metadata(tmp_path: Path) -> None:
    """session show <id> displays session metadata."""
    _create_session(
        tmp_path,
        "show1234abcd5678",
        messages=[{"role": "user", "content": "hello"}],
        metadata={
            "session_id": "show1234abcd5678",
            "name": "Show Test",
            "status": "completed",
        },
    )

    runner = CliRunner()
    result = runner.invoke(
        session_group,
        ["show", "show1234", "--sessions-dir", str(tmp_path)],
    )

    assert result.exit_code == 0
    assert "show1234" in result.output


def test_session_show_unknown_id(tmp_path: Path) -> None:
    """session show <unknown_id> shows an error."""
    runner = CliRunner()
    result = runner.invoke(
        session_group,
        ["show", "nonexistent", "--sessions-dir", str(tmp_path)],
    )

    assert "not found" in result.output.lower() or "Error" in result.output


# ---------------------------------------------------------------------------
# session delete
# ---------------------------------------------------------------------------


def test_session_delete_removes_directory(tmp_path: Path) -> None:
    """session delete <id> --force removes the session directory."""
    _create_session(tmp_path, "del12345abcdef00")

    runner = CliRunner()
    result = runner.invoke(
        session_group,
        ["delete", "del12345", "--force", "--sessions-dir", str(tmp_path)],
    )

    assert result.exit_code == 0
    assert "Deleted" in result.output
    assert not (tmp_path / "del12345abcdef00").exists()


# ---------------------------------------------------------------------------
# session cleanup
# ---------------------------------------------------------------------------


def test_session_cleanup_removes_old(tmp_path: Path) -> None:
    """session cleanup removes sessions older than --days."""
    import os
    import time

    session_dir = _create_session(tmp_path, "old_session_123456")

    # Set modification time to 60 days ago
    old_time = time.time() - (60 * 86400)
    os.utime(session_dir, (old_time, old_time))

    runner = CliRunner()
    result = runner.invoke(
        session_group,
        ["cleanup", "--days", "30", "--force", "--sessions-dir", str(tmp_path)],
    )

    assert result.exit_code == 0
    assert not (tmp_path / "old_session_123456").exists()
```

### Step 2: Run tests to verify they fail

Run: `cd amplifier-ipc/amplifier-ipc-cli && python -m pytest tests/test_commands/test_session.py -v`
Expected: FAIL with `ImportError`

### Step 3: Implement the session management commands

Create `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/commands/session.py`:

```python
"""Session management commands for amplifier-ipc-cli.

Provides CLI subcommands for listing, showing, deleting, and cleaning up
stored sessions. Works against the JSONL persistence layer
(transcript.jsonl + metadata.json per session directory).
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import click
from rich.panel import Panel
from rich.table import Table

from amplifier_ipc_cli.console import console

# -- Constants ----------------------------------------------------------------

_CLI_NAME = "amplifier-ipc"


# -- Path helpers -------------------------------------------------------------


def _get_default_sessions_dir() -> Path:
    """Return the default sessions directory."""
    return Path.home() / ".amplifier" / "sessions"


# -- Time formatting ----------------------------------------------------------


def _format_time_ago(dt: datetime) -> str:
    """Format a datetime as a human-readable 'time ago' string."""
    now = datetime.now(UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    delta = now - dt
    seconds = int(delta.total_seconds())

    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    days = seconds // 86400
    if days < 30:
        return f"{days}d ago"
    return f"{days // 30}mo ago"


# -- Transcript parsing -------------------------------------------------------


def _parse_transcript(session_dir: Path) -> tuple[int, int]:
    """Parse transcript.jsonl and return (total_messages, user_turns)."""
    transcript_path = session_dir / "transcript.jsonl"
    if not transcript_path.exists():
        return 0, 0
    total = 0
    user_count = 0
    try:
        for line in transcript_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            total += 1
            try:
                msg = json.loads(line)
                if msg.get("role") == "user":
                    user_count += 1
            except (json.JSONDecodeError, AttributeError):
                continue
    except OSError:
        pass
    return total, user_count


def _load_metadata(session_dir: Path) -> dict:
    """Load metadata.json from a session directory."""
    meta_path = session_dir / "metadata.json"
    if not meta_path.exists():
        return {}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _find_session(sessions_dir: Path, prefix: str) -> str | None:
    """Find a session by ID prefix. Returns full ID or None."""
    if not sessions_dir.exists():
        return None
    matches = [
        d.name
        for d in sessions_dir.iterdir()
        if d.is_dir() and d.name.startswith(prefix)
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        # Exact match wins
        if prefix in matches:
            return prefix
        return None
    return None


# -- Session group ------------------------------------------------------------


@click.group(name="session", invoke_without_command=True)
@click.option(
    "--sessions-dir",
    default=None,
    help="Override sessions directory (for testing).",
)
@click.pass_context
def session_group(ctx: click.Context, sessions_dir: str | None) -> None:
    """Manage amplifier-ipc sessions."""
    ctx.ensure_object(dict)
    ctx.obj["sessions_dir"] = (
        Path(sessions_dir) if sessions_dir else _get_default_sessions_dir()
    )
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


# -- list ---------------------------------------------------------------------


@session_group.command(name="list")
@click.option("--limit", "-n", default=20, help="Maximum number of sessions.")
@click.pass_context
def session_list(ctx: click.Context, limit: int) -> None:
    """List stored sessions."""
    sessions_dir = ctx.obj["sessions_dir"]
    if not sessions_dir.exists():
        console.print("No sessions found.")
        return

    session_dirs = sorted(
        [d for d in sessions_dir.iterdir() if d.is_dir()],
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )[:limit]

    if not session_dirs:
        console.print("No sessions found.")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Name")
    table.add_column("Session ID")
    table.add_column("Msgs", justify="right")
    table.add_column("Modified")

    for session_dir in session_dirs:
        metadata = _load_metadata(session_dir)
        name = metadata.get("name", "")
        msg_count, _ = _parse_transcript(session_dir)

        try:
            mtime = session_dir.stat().st_mtime
            dt = datetime.fromtimestamp(mtime, tz=UTC)
            modified = _format_time_ago(dt)
        except OSError:
            modified = "unknown"

        sid = session_dir.name
        truncated = sid[:8] + "..." if len(sid) > 8 else sid
        table.add_row(name, truncated, str(msg_count), modified)

    console.print(table)


# -- show ---------------------------------------------------------------------


@session_group.command(name="show")
@click.argument("session_id")
@click.pass_context
def session_show(ctx: click.Context, session_id: str) -> None:
    """Show metadata for a session."""
    sessions_dir = ctx.obj["sessions_dir"]
    full_id = _find_session(sessions_dir, session_id)

    if full_id is None:
        console.print(f"Error: Session '{session_id}' not found.")
        sys.exit(1)

    session_dir = sessions_dir / full_id
    metadata = _load_metadata(session_dir)
    msg_count, user_turns = _parse_transcript(session_dir)

    lines = [
        f"Session ID:   {full_id}",
        f"Name:         {metadata.get('name', '')}",
        f"Status:       {metadata.get('status', 'unknown')}",
        f"Messages:     {msg_count}",
        f"User turns:   {user_turns}",
    ]
    panel = Panel("\n".join(lines), title="Session Info")
    console.print(panel)


# -- delete -------------------------------------------------------------------


@session_group.command(name="delete")
@click.argument("session_id")
@click.option("--force", "-f", is_flag=True, help="Skip confirmation.")
@click.pass_context
def session_delete(ctx: click.Context, session_id: str, force: bool) -> None:
    """Delete a session by ID."""
    sessions_dir = ctx.obj["sessions_dir"]
    full_id = _find_session(sessions_dir, session_id)

    if full_id is None:
        console.print(f"Error: Session '{session_id}' not found.")
        sys.exit(1)

    if not force:
        confirmed = click.confirm(f"Delete session {full_id!r}?")
        if not confirmed:
            console.print("Aborted.")
            return

    session_dir = sessions_dir / full_id
    shutil.rmtree(session_dir)
    console.print(f"Deleted session {full_id!r}.")


# -- cleanup ------------------------------------------------------------------


@session_group.command(name="cleanup")
@click.option("--days", "-d", default=30, help="Remove sessions older than N days.")
@click.option("--force", "-f", is_flag=True, help="Skip confirmation.")
@click.pass_context
def session_cleanup(ctx: click.Context, days: int, force: bool) -> None:
    """Remove sessions older than N days."""
    sessions_dir = ctx.obj["sessions_dir"]
    if not sessions_dir.exists():
        console.print("No sessions found.")
        return

    if not force:
        confirmed = click.confirm(f"Remove sessions older than {days} day(s)?")
        if not confirmed:
            console.print("Aborted.")
            return

    cutoff = time.time() - (days * 86400)
    removed = 0

    for session_dir in sessions_dir.iterdir():
        if not session_dir.is_dir():
            continue
        try:
            mtime = session_dir.stat().st_mtime
            if mtime < cutoff:
                shutil.rmtree(session_dir)
                removed += 1
        except OSError:
            continue

    console.print(f"Removed {removed} session(s).")
```

### Step 4: Run the tests

Run: `cd amplifier-ipc/amplifier-ipc-cli && python -m pytest tests/test_commands/test_session.py -v`
Expected: All tests PASS.

### Step 5: Commit

```bash
cd amplifier-ipc/amplifier-ipc-cli && git add -A && git commit -m "feat(cli): session management commands — list, show, delete, cleanup

Works against JSONL persistence layer (transcript.jsonl + metadata.json).
No dependency on amplifier_lite.session.store — uses direct filesystem ops."
```

---

## Task 7: Fork Command

Add `fork` subcommand to session_group. Snapshots a session's transcript and creates a new session ID.

**Files:**
- Modify: `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/commands/session.py`
- Modify: `amplifier-ipc/amplifier-ipc-cli/tests/test_commands/test_session.py`

### Step 1: Write the failing tests

Append to `amplifier-ipc/amplifier-ipc-cli/tests/test_commands/test_session.py`:

```python
# ---------------------------------------------------------------------------
# session fork
# ---------------------------------------------------------------------------


def test_session_fork_creates_new_session(tmp_path: Path) -> None:
    """session fork <id> creates a new session with copied transcript."""
    _create_session(
        tmp_path,
        "fork_source_12345678",
        messages=[
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
            {"role": "user", "content": "what is 2+2?"},
            {"role": "assistant", "content": "4"},
        ],
        metadata={
            "session_id": "fork_source_12345678",
            "name": "Fork Source",
            "status": "completed",
        },
    )

    runner = CliRunner()
    result = runner.invoke(
        session_group,
        ["fork", "fork_sou", "--sessions-dir", str(tmp_path)],
    )

    assert result.exit_code == 0
    assert "Forked" in result.output

    # A new session directory should exist
    session_dirs = [d for d in tmp_path.iterdir() if d.is_dir()]
    assert len(session_dirs) == 2  # original + fork


def test_session_fork_at_turn(tmp_path: Path) -> None:
    """session fork --at-turn N copies only messages up to turn N."""
    _create_session(
        tmp_path,
        "forkturnsrc12345",
        messages=[
            {"role": "user", "content": "turn 1"},
            {"role": "assistant", "content": "response 1"},
            {"role": "user", "content": "turn 2"},
            {"role": "assistant", "content": "response 2"},
        ],
        metadata={"session_id": "forkturnsrc12345", "status": "completed"},
    )

    runner = CliRunner()
    result = runner.invoke(
        session_group,
        ["fork", "forkturn", "--at-turn", "1", "--sessions-dir", str(tmp_path)],
    )

    assert result.exit_code == 0
    assert "Forked" in result.output

    # Find the new session
    session_dirs = [
        d for d in tmp_path.iterdir()
        if d.is_dir() and d.name != "forkturnsrc12345"
    ]
    assert len(session_dirs) == 1

    # Check the forked transcript has only 2 messages (1 user turn = 1 user + 1 assistant)
    new_dir = session_dirs[0]
    transcript = (new_dir / "transcript.jsonl").read_text().strip().split("\n")
    assert len(transcript) == 2


def test_session_fork_unknown_id(tmp_path: Path) -> None:
    """session fork <unknown_id> shows an error."""
    runner = CliRunner()
    result = runner.invoke(
        session_group,
        ["fork", "nonexistent", "--sessions-dir", str(tmp_path)],
    )

    assert "not found" in result.output.lower() or "Error" in result.output
```

### Step 2: Run tests to verify the new fork tests fail

Run: `cd amplifier-ipc/amplifier-ipc-cli && python -m pytest tests/test_commands/test_session.py -v -k fork`
Expected: FAIL (fork subcommand not yet defined)

### Step 3: Add the fork subcommand to session.py

Add the following to the end of `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/commands/session.py`, after the `session_cleanup` command:

```python
# -- fork ---------------------------------------------------------------------


def _fork_session(
    sessions_dir: Path,
    source_id: str,
    *,
    turn: int | None = None,
) -> tuple[str, int]:
    """Fork a session, returning (new_session_id, message_count).

    Copies transcript.jsonl (up to the specified turn) and metadata.json
    into a new session directory.

    Args:
        sessions_dir: Base directory for all sessions.
        source_id: Full session ID to fork from.
        turn: Fork at this user turn number (1-indexed). None = all.

    Returns:
        Tuple of (new_session_id, message_count_in_fork).

    Raises:
        FileNotFoundError: If the source session doesn't exist.
        ValueError: If turn is invalid.
    """
    import uuid as uuid_mod

    source_dir = sessions_dir / source_id
    if not source_dir.is_dir():
        raise FileNotFoundError(f"Session '{source_id}' not found.")

    # Read source transcript
    transcript_path = source_dir / "transcript.jsonl"
    messages: list[dict] = []
    if transcript_path.exists():
        for line in transcript_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                messages.append(json.loads(line))

    # Truncate at turn if specified
    if turn is not None:
        if turn < 1:
            raise ValueError("Turn number must be >= 1")
        # Count user turns
        user_count = 0
        cutoff = len(messages)
        for i, msg in enumerate(messages):
            if msg.get("role") == "user":
                user_count += 1
                if user_count > turn:
                    cutoff = i
                    break
        messages = messages[:cutoff]

    # Create new session
    new_id = f"fork_{uuid_mod.uuid4().hex[:12]}"
    new_dir = sessions_dir / new_id
    new_dir.mkdir(parents=True)

    # Write forked transcript
    new_transcript = new_dir / "transcript.jsonl"
    with new_transcript.open("w", encoding="utf-8") as f:
        for msg in messages:
            f.write(json.dumps(msg, separators=(",", ":")) + "\n")

    # Copy and update metadata
    source_meta = _load_metadata(source_dir)
    fork_meta = {
        "session_id": new_id,
        "name": source_meta.get("name", "") + " (fork)",
        "forked_from": source_id,
        "forked_at_turn": turn or "latest",
        "status": "active",
    }
    with (new_dir / "metadata.json").open("w", encoding="utf-8") as f:
        json.dump(fork_meta, f, indent=2)

    return new_id, len(messages)


@session_group.command(name="fork")
@click.argument("session_id")
@click.option(
    "--at-turn",
    "-t",
    "turn",
    default=None,
    type=int,
    help="Fork at this turn number (default: latest).",
)
@click.pass_context
def session_fork(ctx: click.Context, session_id: str, turn: int | None) -> None:
    """Fork a session at a specific turn."""
    sessions_dir = ctx.obj["sessions_dir"]
    full_id = _find_session(sessions_dir, session_id)

    if full_id is None:
        console.print(f"Error: Session '{session_id}' not found.")
        sys.exit(1)

    try:
        new_id, msg_count = _fork_session(sessions_dir, full_id, turn=turn)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"Error: {exc}")
        sys.exit(1)

    console.print(f"Forked session {full_id!r}.")
    console.print(f"New session ID: {new_id}")
    console.print(f"Messages:       {msg_count}")
    console.print(f"\nTo resume:  {_CLI_NAME} run --session {new_id[:8]}")
```

### Step 4: Run all session tests

Run: `cd amplifier-ipc/amplifier-ipc-cli && python -m pytest tests/test_commands/test_session.py -v`
Expected: All tests PASS (including the new fork tests).

### Step 5: Commit

```bash
cd amplifier-ipc/amplifier-ipc-cli && git add -A && git commit -m "feat(cli): session fork command — snapshot transcript at a turn

amplifier-ipc session fork <id> [--at-turn N]
Copies transcript.jsonl (truncated at turn N) and metadata into a new session."
```

---

## Task 8: Adapted Commands and Wiring

Wire all new commands (discover, register, install, update, session) into `main.py`'s Click group. Adapt `provider.py`, `routing.py`, and `reset.py` for IPC paths.

**Files:**
- Modify: `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/main.py`
- Create: `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/commands/provider.py`
- Create: `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/commands/routing.py`
- Create: `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/commands/reset.py`
- Test: `amplifier-ipc/amplifier-ipc-cli/tests/test_commands/test_wiring.py`

### Step 1: Write the failing tests

Create `amplifier-ipc/amplifier-ipc-cli/tests/test_commands/test_wiring.py`:

```python
"""Tests for command wiring — verify all commands are registered in the CLI group."""

from __future__ import annotations

from click.testing import CliRunner

from amplifier_ipc_cli.main import cli


def test_help_lists_all_commands() -> None:
    """The --help output includes all expected commands."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])

    assert result.exit_code == 0
    output = result.output.lower()

    # Core commands
    assert "run" in output
    assert "version" in output

    # Management commands (Phase 2)
    assert "discover" in output
    assert "register" in output
    assert "install" in output
    assert "update" in output
    assert "session" in output

    # Adapted commands
    assert "provider" in output
    assert "routing" in output
    assert "reset" in output


def test_discover_help() -> None:
    """discover --help works."""
    runner = CliRunner()
    result = runner.invoke(cli, ["discover", "--help"])
    assert result.exit_code == 0
    assert "location" in result.output.lower() or "LOCATION" in result.output


def test_register_help() -> None:
    """register --help works."""
    runner = CliRunner()
    result = runner.invoke(cli, ["register", "--help"])
    assert result.exit_code == 0


def test_install_help() -> None:
    """install --help works."""
    runner = CliRunner()
    result = runner.invoke(cli, ["install", "--help"])
    assert result.exit_code == 0


def test_update_help() -> None:
    """update --help works."""
    runner = CliRunner()
    result = runner.invoke(cli, ["update", "--help"])
    assert result.exit_code == 0


def test_session_help() -> None:
    """session --help works."""
    runner = CliRunner()
    result = runner.invoke(cli, ["session", "--help"])
    assert result.exit_code == 0
    output = result.output.lower()
    assert "list" in output
    assert "show" in output
    assert "delete" in output
    assert "fork" in output


def test_provider_help() -> None:
    """provider --help works."""
    runner = CliRunner()
    result = runner.invoke(cli, ["provider", "--help"])
    assert result.exit_code == 0


def test_routing_help() -> None:
    """routing --help works."""
    runner = CliRunner()
    result = runner.invoke(cli, ["routing", "--help"])
    assert result.exit_code == 0


def test_reset_help() -> None:
    """reset --help works."""
    runner = CliRunner()
    result = runner.invoke(cli, ["reset", "--help"])
    assert result.exit_code == 0
```

### Step 2: Run tests to verify they fail

Run: `cd amplifier-ipc/amplifier-ipc-cli && python -m pytest tests/test_commands/test_wiring.py -v`
Expected: FAIL (new commands not wired yet)

### Step 3: Create the adapted provider command

Create `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/commands/provider.py`:

```python
"""Provider management commands for amplifier-ipc-cli."""

from __future__ import annotations

import click

from amplifier_ipc_cli.console import console
from amplifier_ipc_cli.key_manager import KeyManager
from amplifier_ipc_cli.settings import AppSettings, get_settings


def _get_settings() -> AppSettings:
    """Return an AppSettings instance (patchable for tests)."""
    return get_settings()


def _get_key_manager() -> KeyManager:
    """Return a KeyManager instance (patchable for tests)."""
    return KeyManager()


@click.group(name="provider", invoke_without_command=True)
@click.pass_context
def provider_group(ctx: click.Context) -> None:
    """Manage LLM providers."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@provider_group.command(name="list")
def provider_list() -> None:
    """Show the current provider and any overrides."""
    settings = _get_settings()
    provider = settings.get_provider()
    overrides = settings.get_provider_overrides()

    if not provider and not overrides:
        console.print("No provider configured.")
        return

    if provider:
        console.print(f"Provider: {provider}")

    if overrides:
        console.print("Overrides:")
        for override in overrides:
            console.print(f"  {override}")


@provider_group.command(name="set-key")
@click.argument("key_name")
def provider_set_key(key_name: str) -> None:
    """Save an API key (e.g. ANTHROPIC_API_KEY) to the key store."""
    value = click.prompt(key_name, hide_input=True)
    km = _get_key_manager()
    km.save_key(key_name, value)
    console.print("Key saved")


@provider_group.command(name="use")
@click.argument("name")
@click.option("--model", "-m", default=None, help="Model to use.")
def provider_use(name: str, model: str | None) -> None:
    """Set the default provider (and optionally the model)."""
    settings = _get_settings()
    settings.set_provider(name)
    if model:
        settings.set_model(model)
    console.print(f"Provider set to: {name}" + (f" (model: {model})" if model else ""))
```

### Step 4: Create the adapted routing command

Create `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/commands/routing.py`:

```python
"""Routing matrix management commands for amplifier-ipc-cli."""

from __future__ import annotations

import sys
from pathlib import Path

import click
import yaml

from amplifier_ipc_cli.console import console
from amplifier_ipc_cli.settings import AppSettings, get_settings


def _get_settings() -> AppSettings:
    """Return an AppSettings instance (patchable for tests)."""
    return get_settings()


def _get_routing_dir() -> Path:
    """Return the routing matrices directory (patchable for tests)."""
    return Path.home() / ".amplifier" / "routing"


@click.group(name="routing", invoke_without_command=True)
@click.pass_context
def routing_group(ctx: click.Context) -> None:
    """Manage routing matrices."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@routing_group.command(name="list")
def routing_list() -> None:
    """List available routing matrices."""
    routing_dir = _get_routing_dir()
    settings = _get_settings()
    active = settings.get_routing_config().get("active_matrix")

    yaml_files = sorted(routing_dir.glob("*.yaml")) if routing_dir.exists() else []

    if not yaml_files:
        console.print("No routing matrices found.")
        return

    for path in yaml_files:
        name = path.stem
        marker = " (active)" if name == active else ""
        console.print(f"{name}{marker}")


@routing_group.command(name="show")
@click.argument("name")
def routing_show(name: str) -> None:
    """Show the roles defined in a routing matrix."""
    routing_dir = _get_routing_dir()
    matrix_file = routing_dir / f"{name}.yaml"

    if not matrix_file.exists():
        console.print(f"Routing matrix '{name}' not found.")
        sys.exit(1)

    try:
        data = yaml.safe_load(matrix_file.read_text()) or {}
    except yaml.YAMLError as exc:
        console.print(f"Error reading '{name}': {exc}")
        sys.exit(1)

    roles = data.get("roles", {})
    if not roles:
        console.print(f"No roles defined in '{name}'.")
        return

    for role, config in roles.items():
        provider = config.get("provider", "")
        model = config.get("model", "")
        console.print(f"  {role}: {provider}/{model}")


@routing_group.command(name="use")
@click.argument("name")
def routing_use(name: str) -> None:
    """Set the active routing matrix."""
    routing_dir = _get_routing_dir()
    matrix_file = routing_dir / f"{name}.yaml"

    if not matrix_file.exists():
        console.print(f"Routing matrix '{name}' not found.")
        sys.exit(1)

    settings = _get_settings()
    settings.set_routing_matrix(name)
    console.print(f"Active routing matrix set to: {name}")
```

### Step 5: Create the adapted reset command

Create `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/commands/reset.py`:

```python
"""Reset command — clears CLI state (environments, definitions, sessions, keys, or all)."""

from __future__ import annotations

import shutil
from pathlib import Path

import click

from amplifier_ipc_cli.console import console

_AMPLIFIER_DIR = ".amplifier"

_REMOVE_TARGETS = ("environments", "definitions", "sessions", "keys", "all")


def _get_base_dir() -> Path:
    """Return the base directory (patchable for tests)."""
    return Path.home()


def _get_target_paths(target: str, amp_dir: Path) -> list[Path]:
    """Return paths to remove for the given target."""
    paths: list[Path] = []
    if target in ("environments", "all"):
        paths.append(amp_dir / "environments")
    if target in ("definitions", "all"):
        paths.append(amp_dir / "definitions")
        paths.append(amp_dir / "agents.yaml")
        paths.append(amp_dir / "behaviors.yaml")
    if target in ("sessions", "all"):
        paths.append(amp_dir / "sessions")
        paths.append(amp_dir / "projects")
    if target in ("keys", "all"):
        paths.append(amp_dir / "keys.env")
    return paths


def _remove_path(path: Path) -> None:
    """Remove a file or directory tree."""
    try:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
    except OSError as exc:
        console.print(f"Error removing {path}: {exc}")
        raise


@click.command(name="reset")
@click.option(
    "--remove",
    type=click.Choice(_REMOVE_TARGETS),
    default=None,
    help="What to remove: environments, definitions, sessions, keys, or all.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Show what would be removed without removing.",
)
def reset_cmd(remove: str | None, dry_run: bool) -> None:
    """Reset CLI state by removing stored data."""
    if remove is None:
        console.print("Usage: reset --remove <target>")
        console.print("")
        console.print("Available targets:")
        for target in _REMOVE_TARGETS:
            console.print(f"  {target}")
        return

    base_dir = _get_base_dir()
    amp_dir = base_dir / _AMPLIFIER_DIR
    paths = _get_target_paths(remove, amp_dir)

    for path in paths:
        if path.exists():
            if dry_run:
                console.print(f"Would remove: {path}")
            else:
                _remove_path(path)
                console.print(f"Removed: {path}")
        else:
            if dry_run:
                console.print(f"not present: {path}")

    if dry_run:
        console.print("Dry run -- nothing was removed.")
```

### Step 6: Update main.py with all commands

Replace `amplifier-ipc/amplifier-ipc-cli/src/amplifier_ipc_cli/main.py`:

```python
"""Main entry point for the amplifier-ipc CLI."""

from __future__ import annotations

import click

from amplifier_ipc_cli.commands.allowed_dirs import allowed_dirs_group
from amplifier_ipc_cli.commands.denied_dirs import denied_dirs_group
from amplifier_ipc_cli.commands.discover import discover
from amplifier_ipc_cli.commands.install import install
from amplifier_ipc_cli.commands.notify import notify_group
from amplifier_ipc_cli.commands.provider import provider_group
from amplifier_ipc_cli.commands.register import register
from amplifier_ipc_cli.commands.reset import reset_cmd
from amplifier_ipc_cli.commands.routing import routing_group
from amplifier_ipc_cli.commands.run import run
from amplifier_ipc_cli.commands.session import session_group
from amplifier_ipc_cli.commands.update import update
from amplifier_ipc_cli.commands.version import version


@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx: click.Context) -> None:
    """amplifier-ipc — interact with amplifier-ipc sessions."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


# Core
cli.add_command(run)
cli.add_command(version)

# Management (Phase 2)
cli.add_command(discover)
cli.add_command(register)
cli.add_command(install)
cli.add_command(update)
cli.add_command(session_group, name="session")

# Adapted from lite-cli
cli.add_command(provider_group, name="provider")
cli.add_command(routing_group, name="routing")
cli.add_command(reset_cmd, name="reset")

# Wholesale from lite-cli
cli.add_command(allowed_dirs_group, name="allowed-dirs")
cli.add_command(denied_dirs_group, name="denied-dirs")
cli.add_command(notify_group, name="notify")


def main() -> None:
    """Main entry point — delegates to the cli Click group."""
    cli()


if __name__ == "__main__":
    main()
```

### Step 7: Run the wiring tests

Run: `cd amplifier-ipc/amplifier-ipc-cli && python -m pytest tests/test_commands/test_wiring.py -v`
Expected: All tests PASS.

### Step 8: Run all tests to verify nothing broke

Run: `cd amplifier-ipc/amplifier-ipc-cli && python -m pytest tests/ -v`
Expected: All tests PASS.

### Step 9: Commit

```bash
cd amplifier-ipc/amplifier-ipc-cli && git add -A && git commit -m "feat(cli): wire all Phase 2 commands into Click group

main.py now registers: discover, register, install, update, session,
provider, routing, reset. Adapted provider/routing/reset for IPC paths."
```

---

## Task 9: Management Integration Tests

End-to-end tests for the management flow: discover → register → install → update → session lifecycle.

**Files:**
- Test: `amplifier-ipc/amplifier-ipc-cli/tests/test_management_integration.py`

### Step 1: Write the integration tests

Create `amplifier-ipc/amplifier-ipc-cli/tests/test_management_integration.py`:

```python
"""Integration tests for the management flow.

Tests the full lifecycle:
1. discover a local directory → definitions found
2. register a definition → alias created
3. install a definition → venv created (mocked)
4. update --check → reports status
5. Session lifecycle: create session data, list, show, delete
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from amplifier_ipc_cli.main import cli


# ---------------------------------------------------------------------------
# Sample definitions
# ---------------------------------------------------------------------------

_AGENT_YAML = """\
type: agent
local_ref: integration-agent
uuid: aaaa1111-bbbb-2222-3333-444455556666
version: "1.0"
orchestrator: streaming
context_manager: simple
behaviors:
  - name: integration-beh
services:
  - name: integration-service
    installer: pip
    source: integration-pkg
"""

_BEHAVIOR_YAML = """\
type: behavior
local_ref: integration-beh
uuid: cccc3333-dddd-4444-5555-666677778888
version: "1.0"
tools:
  - name: bash
services:
  - name: integration-service
    installer: pip
    source: integration-pkg
"""


# ---------------------------------------------------------------------------
# discover → register flow
# ---------------------------------------------------------------------------


def test_discover_and_register_local_directory(tmp_path: Path) -> None:
    """Discover a local directory, register definitions, verify aliases."""
    # Create definition files
    defs_dir = tmp_path / "definitions"
    defs_dir.mkdir()
    (defs_dir / "agent.yaml").write_text(_AGENT_YAML)
    (defs_dir / "behavior.yaml").write_text(_BEHAVIOR_YAML)

    home = tmp_path / "amp_home"

    runner = CliRunner()
    result = runner.invoke(
        cli, ["discover", str(defs_dir), "--register", "--home", str(home)]
    )

    assert result.exit_code == 0
    assert "Found 2" in result.output
    assert "Registered" in result.output

    # Verify aliases were created
    import yaml

    agents = yaml.safe_load((home / "agents.yaml").read_text())
    assert "integration-agent" in agents

    behaviors = yaml.safe_load((home / "behaviors.yaml").read_text())
    assert "integration-beh" in behaviors


# ---------------------------------------------------------------------------
# register single file
# ---------------------------------------------------------------------------


def test_register_single_behavior(tmp_path: Path) -> None:
    """Register a single behavior file and verify the alias appears."""
    beh_file = tmp_path / "beh.yaml"
    beh_file.write_text(_BEHAVIOR_YAML)

    home = tmp_path / "amp_home"

    runner = CliRunner()
    result = runner.invoke(
        cli, ["register", str(beh_file), "--home", str(home)]
    )

    assert result.exit_code == 0
    assert "Registered" in result.output

    import yaml

    behaviors = yaml.safe_load((home / "behaviors.yaml").read_text())
    assert "integration-beh" in behaviors


# ---------------------------------------------------------------------------
# install (mocked uv)
# ---------------------------------------------------------------------------


def test_install_agent_with_mocked_uv(tmp_path: Path) -> None:
    """Install an agent — verify uv is called (mocked)."""
    home = tmp_path / "amp_home"

    # First register the agent
    agent_file = tmp_path / "agent.yaml"
    agent_file.write_text(_AGENT_YAML)

    runner = CliRunner()
    runner.invoke(cli, ["register", str(agent_file), "--home", str(home)])

    # Now install with mocked uv
    with patch("amplifier_ipc_cli.commands.install._run_uv"):
        result = runner.invoke(
            cli, ["install", "integration-agent", "--home", str(home)]
        )

    assert result.exit_code == 0
    assert "install" in result.output.lower() or "Install" in result.output


# ---------------------------------------------------------------------------
# update --check
# ---------------------------------------------------------------------------


def test_update_check_after_register(tmp_path: Path) -> None:
    """update --check reports no upstream changes for locally-registered definitions."""
    home = tmp_path / "amp_home"

    # Register agent and behavior
    agent_file = tmp_path / "agent.yaml"
    agent_file.write_text(_AGENT_YAML)
    beh_file = tmp_path / "beh.yaml"
    beh_file.write_text(_BEHAVIOR_YAML)

    runner = CliRunner()
    runner.invoke(cli, ["register", str(agent_file), "--home", str(home)])
    runner.invoke(cli, ["register", str(beh_file), "--home", str(home)])

    # Update check — no _meta blocks → no behaviors with remote sources
    result = runner.invoke(
        cli, ["update", "integration-agent", "--check", "--home", str(home)]
    )

    assert result.exit_code == 0
    assert "No behaviors with remote sources" in result.output


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------


def _create_test_session(sessions_dir: Path, session_id: str) -> None:
    """Create a test session with transcript and metadata."""
    session_dir = sessions_dir / session_id
    session_dir.mkdir(parents=True)

    with (session_dir / "transcript.jsonl").open("w") as f:
        f.write(json.dumps({"role": "user", "content": "hello"}) + "\n")
        f.write(json.dumps({"role": "assistant", "content": "hi"}) + "\n")

    with (session_dir / "metadata.json").open("w") as f:
        json.dump({"session_id": session_id, "name": "Test", "status": "completed"}, f)


def test_session_lifecycle(tmp_path: Path) -> None:
    """Full session lifecycle: create → list → show → delete."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()

    _create_test_session(sessions_dir, "lifecycle_test_12345678")

    runner = CliRunner()

    # List
    result = runner.invoke(
        cli, ["session", "--sessions-dir", str(sessions_dir), "list"]
    )
    assert result.exit_code == 0
    assert "lifecycl" in result.output  # truncated ID

    # Show
    result = runner.invoke(
        cli, ["session", "--sessions-dir", str(sessions_dir), "show", "lifecycle"]
    )
    assert result.exit_code == 0
    assert "lifecycle_test_12345678" in result.output

    # Delete
    result = runner.invoke(
        cli,
        ["session", "--sessions-dir", str(sessions_dir), "delete", "lifecycle", "--force"],
    )
    assert result.exit_code == 0
    assert "Deleted" in result.output
    assert not (sessions_dir / "lifecycle_test_12345678").exists()
```

### Step 2: Run the integration tests

Run: `cd amplifier-ipc/amplifier-ipc-cli && python -m pytest tests/test_management_integration.py -v`
Expected: All tests PASS.

### Step 3: Run the full test suite

Run: `cd amplifier-ipc/amplifier-ipc-cli && python -m pytest tests/ -v`
Expected: All tests PASS — Phase 1 and Phase 2 tests.

### Step 4: Commit

```bash
cd amplifier-ipc/amplifier-ipc-cli && git add -A && git commit -m "test(cli): management integration tests — discover/register/install/update/session lifecycle

End-to-end tests for the full management flow. Verifies command chaining:
discover → register → install → update --check → session list/show/delete."
```

---

## Summary

| Task | What | Key Files |
|------|------|-----------|
| 1 | Discover command | `commands/discover.py` — scan locations for definitions |
| 2 | Register command | `commands/register.py` — cache single definition |
| 3 | Install command | `commands/install.py` — create venvs via uv |
| 4 | Update command | `commands/update.py` — re-fetch URLs, compare hashes |
| 5 | Session spawner | `session_spawner.py` — child Host for delegation |
| 6 | Session management | `commands/session.py` — list, show, delete, cleanup |
| 7 | Fork command | `commands/session.py` — fork at turn |
| 8 | Adapted commands + wiring | `main.py`, `commands/provider.py`, `commands/routing.py`, `commands/reset.py` |
| 9 | Integration tests | `tests/test_management_integration.py` — full lifecycle |
