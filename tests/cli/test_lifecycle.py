"""Integration tests for the full discover -> register -> install lifecycle.

Tests:
1. test_discover_finds_definitions -- discover services/ finds agents and behaviors
2. test_discover_register_creates_alias_files -- after --register, alias files populated
3. test_registered_definitions_are_valid -- stored defs have correct nested structure
"""

from __future__ import annotations

from pathlib import Path

import yaml
from click.testing import CliRunner

from amplifier_ipc.cli.main import cli

SERVICES_DIR = Path(__file__).parent.parent.parent / "services"  # -> repo_root/services


def test_discover_finds_definitions() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["discover", str(SERVICES_DIR)])
    assert result.exit_code == 0, result.output
    assert "Found" in result.output
    assert "[agent]" in result.output
    assert "[behavior]" in result.output


def test_discover_register_creates_alias_files(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli, ["discover", str(SERVICES_DIR), "--register", "--home", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    agents = yaml.safe_load((tmp_path / "agents.yaml").read_text()) or {}
    assert len(agents) > 0, "agents.yaml should have at least one entry"
    behaviors = yaml.safe_load((tmp_path / "behaviors.yaml").read_text()) or {}
    assert len(behaviors) > 0, "behaviors.yaml should have at least one entry"


def test_registered_definitions_are_valid(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli, ["discover", str(SERVICES_DIR), "--register", "--home", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    defs_dir = tmp_path / "definitions"
    for def_file in sorted(defs_dir.glob("*.yaml")):
        stored = yaml.safe_load(def_file.read_text()) or {}
        top_keys = {k for k in stored if not k.startswith("_")}
        assert top_keys & {"agent", "behavior"}, (
            f"{def_file.name}: no agent: or behavior: key found. Keys: {top_keys}"
        )
