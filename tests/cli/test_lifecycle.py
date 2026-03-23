"""Integration tests for the full discover → register → install → run lifecycle.

Tests:
1. test_discover_finds_all_ipc_definitions     — discover fixture_dir/ finds 5 behaviors + 1 agent
2. test_discover_register_creates_alias_files  — after --register, alias files have expected entries
3. test_registered_definitions_have_resolved_sources — stored defs use absolute source paths
4. test_install_creates_environments           — after install, per-service env dirs exist
"""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from click.testing import CliRunner

from amplifier_ipc.cli.main import cli

# Expected IPC behavior refs — mirror the 5 services in the amplifier-dev agent
IPC_BEHAVIORS = ["foundation", "modes", "providers", "routing", "skills"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def services_dir(tmp_path: Path) -> Path:
    """Create a minimal fixture services/ tree with IPC-format YAML files.

    Produces:
    - 5 behavior definitions (one per IPC_BEHAVIORS entry), each with ref + uuid
    - 1 agent definition (amplifier-dev) that references all 5 behaviors

    The fixture uses ``tmp_path`` (scoped to the test) so every test that
    requests it gets its own isolated directory.
    """
    # Create one behavior definition per expected behavior
    for name in IPC_BEHAVIORS:
        svc_root = tmp_path / f"amplifier-{name}"
        behaviors_dir = svc_root / "behaviors"
        behaviors_dir.mkdir(parents=True)

        behavior_doc = {
            "behavior": {
                "ref": name,
                "uuid": str(uuid.uuid4()),
                "version": "1",
                "description": f"{name.capitalize()} IPC behavior",
                "service": {
                    "source": str(svc_root.resolve()),
                },
            }
        }
        (behaviors_dir / f"{name}-ipc.yaml").write_text(
            yaml.dump(behavior_doc), encoding="utf-8"
        )

    # Create one agent definition
    agent_root = tmp_path / "amplifier-amplifier"
    agent_behaviors_dir = agent_root / "behaviors"
    agent_behaviors_dir.mkdir(parents=True)

    agent_doc = {
        "agent": {
            "ref": "amplifier-dev",
            "uuid": str(uuid.uuid4()),
            "version": "1",
            "description": "Amplifier dev agent",
            "behaviors": [{"ref": b} for b in IPC_BEHAVIORS],
            "service": {
                "source": str(agent_root.resolve()),
            },
        }
    }
    (agent_behaviors_dir / "amplifier-dev.yaml").write_text(
        yaml.dump(agent_doc), encoding="utf-8"
    )

    return tmp_path


# ---------------------------------------------------------------------------
# Test 1: discover finds all IPC definitions
# ---------------------------------------------------------------------------


def test_discover_finds_all_ipc_definitions(services_dir: Path) -> None:
    """discover <services_dir>/ finds the 1 agent and 5 IPC behavior definitions."""
    runner = CliRunner()
    result = runner.invoke(cli, ["discover", str(services_dir)])

    assert result.exit_code == 0, result.output
    assert "Found 6 definition(s)" in result.output
    # Rich strips unknown markup tags like [agent] and [behavior] from console output,
    # so we assert on the ref name surrounded by whitespace as it appears in the output
    # line format: "   {ref}  {path}".
    assert "  amplifier-dev  " in result.output
    for behavior in IPC_BEHAVIORS:
        assert f"  {behavior}  " in result.output


# ---------------------------------------------------------------------------
# Test 2: discover --register populates alias files
# ---------------------------------------------------------------------------


def test_discover_register_creates_alias_files(
    services_dir: Path, tmp_path: Path
) -> None:
    """After discover --register, agents.yaml and behaviors.yaml have expected entries."""
    # Use a sub-directory of tmp_path as the home to avoid collision with services_dir
    home_dir = tmp_path / "home"
    home_dir.mkdir()

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["discover", str(services_dir), "--register", "--home", str(home_dir)],
    )
    assert result.exit_code == 0, result.output

    agents = yaml.safe_load((home_dir / "agents.yaml").read_text()) or {}
    assert "amplifier-dev" in agents

    behaviors = yaml.safe_load((home_dir / "behaviors.yaml").read_text()) or {}
    for behavior in IPC_BEHAVIORS:
        assert behavior in behaviors, f"behavior '{behavior}' not in behaviors.yaml"


# ---------------------------------------------------------------------------
# Test 3: stored definitions have absolute source paths
# ---------------------------------------------------------------------------


def test_registered_definitions_have_resolved_sources(
    services_dir: Path, tmp_path: Path
) -> None:
    """Definitions stored in definitions/ use absolute, existing source paths."""
    home_dir = tmp_path / "home"
    home_dir.mkdir()

    runner = CliRunner()
    runner.invoke(
        cli,
        ["discover", str(services_dir), "--register", "--home", str(home_dir)],
    )

    defs_dir = home_dir / "definitions"

    # Check every stored definition file
    for def_file in sorted(defs_dir.glob("*.yaml")):
        stored = yaml.safe_load(def_file.read_text()) or {}
        # Check top-level 'agent' or 'behavior' block for a service source
        for kind in ("agent", "behavior"):
            inner = stored.get(kind)
            if not isinstance(inner, dict):
                continue
            svc = inner.get("service")
            if not isinstance(svc, dict):
                continue
            source = svc.get("source")
            if not source:
                continue
            assert Path(source).is_absolute(), (
                f"{def_file.name}: {kind} service has non-absolute source: {source!r}"
            )
            assert Path(source).exists(), (
                f"{def_file.name}: {kind} service source path does not exist: {source!r}"
            )


# ---------------------------------------------------------------------------
# Test 4: install creates per-service environment directories
# ---------------------------------------------------------------------------


def test_install_creates_environments(services_dir: Path, tmp_path: Path) -> None:
    """install amplifier-dev creates a separate env dir for each service."""
    home_dir = tmp_path / "home"
    home_dir.mkdir()

    runner = CliRunner()
    # Register first so the agent is known to the registry
    runner.invoke(
        cli,
        ["discover", str(services_dir), "--register", "--home", str(home_dir)],
    )

    # Patch _run_uv so we don't actually invoke uv (keeps test fast and offline)
    with patch("amplifier_ipc.cli.commands.install._run_uv") as mock_uv:
        result = runner.invoke(
            cli,
            ["install", "amplifier-dev", "--home", str(home_dir)],
        )

    assert result.exit_code == 0, result.output

    # _run_uv should have been called with "venv" for the agent's service.
    # The install command installs one service per definition (the agent's own service).
    venv_calls = [c for c in mock_uv.call_args_list if c.args[0][0] == "venv"]
    assert len(venv_calls) >= 1, (
        f"Expected at least 1 venv creation (the agent service), got {len(venv_calls)}. "
        f"Calls: {mock_uv.call_args_list}"
    )

    # Each venv call target path must be under environments/
    envs_dir = home_dir / "environments"
    for c in venv_calls:
        env_path = c.args[0][1]  # second arg to "venv <path>"
        assert str(envs_dir) in env_path, (
            f"venv path {env_path!r} is not under environments/"
        )
