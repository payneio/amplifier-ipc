"""Integration tests for the full discover -> register -> install -> run lifecycle.

Tests:
1. test_discover_finds_definitions
   -- discover services/ finds agents and behaviors
2. test_discover_register_creates_alias_files
   -- after --register, alias files are populated
3. test_registered_definitions_are_valid
   -- stored definitions have correct nested structure (agent:/behavior: wrapper)
4. test_service_source_paths_have_no_leading_slash
   -- all service source: fields use correct git subdirectory format (no leading /)
5. test_install_reads_service_from_definition
   -- install reads service.source from the registered nested-format definition
6. test_resolve_agent_url_behaviors_resolve_via_local_alias
   -- after discover --register, URL-referenced behaviors resolve via local alias
7. test_settings_nested_format_applies_overrides
   -- the nested agent→service settings.yaml format is applied during session launch
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml
from click.testing import CliRunner

from amplifier_ipc.cli.main import cli
from amplifier_ipc.host.definition_registry import Registry
from amplifier_ipc.host.definitions import resolve_agent

SERVICES_DIR = Path(__file__).parent.parent.parent / "services"  # -> repo_root/services


# ---------------------------------------------------------------------------
# 1. Discover finds definitions
# ---------------------------------------------------------------------------


def test_discover_finds_definitions() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["discover", str(SERVICES_DIR)])
    assert result.exit_code == 0, result.output
    assert "Found" in result.output
    assert "[agent]" in result.output
    assert "[behavior]" in result.output


# ---------------------------------------------------------------------------
# 2. discover --register creates alias files
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# 3. Registered definitions are valid (nested format)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# 4. Service source paths have no leading slash in git subdirectory
# ---------------------------------------------------------------------------


def test_service_source_paths_have_no_leading_slash() -> None:
    """All service source: URLs use valid git subdirectory format (no leading /).

    pip/uv VCS URLs require a relative subdirectory path:
      git+https://...@main#subdirectory=services/X   ← correct
      git+https://...@main#subdirectory=/services/X  ← wrong (leading slash)

    This test scans all YAML files in services/ and verifies none has the invalid
    leading-slash form, preventing install failures.
    """
    bad_files = []
    for yaml_path in sorted(SERVICES_DIR.rglob("*.yaml")):
        # Skip generated or vendored files
        if ".venv" in yaml_path.parts or "src" in yaml_path.parts:
            continue
        try:
            content = yaml_path.read_text()
        except OSError:
            continue
        if "#subdirectory=/" in content:
            bad_files.append(str(yaml_path.relative_to(SERVICES_DIR.parent)))

    assert not bad_files, (
        "These definition files have a leading slash in #subdirectory= "
        "(invalid for uv/pip VCS installs):\n" + "\n".join(f"  {f}" for f in bad_files)
    )


# ---------------------------------------------------------------------------
# 5. Install reads service from registered nested-format definition
# ---------------------------------------------------------------------------


def test_install_reads_service_from_definition(tmp_path: Path) -> None:
    """install reads service.source from a registered agent definition.

    After discover --register, the stored definition uses the nested format:
      agent:
        ref: ...
        service:
          source: git+https://...
    The install command must parse this and find the source field.
    """
    registry = Registry(home=tmp_path / "amplifier_home")
    registry.ensure_home()

    # Register a minimal agent with a service (new nested format)
    agent_yaml = """\
agent:
  ref: install-test-agent
  uuid: dddddddd-0000-0000-0000-000000000001
  service:
    stack: uv
    source: git+https://example.com/mypackage@main#subdirectory=services/mypackage
    command: mypackage-serve
"""
    registry.register_definition(agent_yaml)

    # Resolve the definition path
    def_path = registry.resolve_agent("install-test-agent")

    # Parse the definition — must extract service.source without error
    definition = yaml.safe_load(def_path.read_text()) or {}
    inner = definition.get("agent", {})
    service = inner.get("service")

    assert service is not None, "Definition must have a service block"
    assert isinstance(service, dict), "service must be a dict"
    source = service.get("source")
    assert source is not None, "service must have a source field"
    assert "#subdirectory=/" not in source, (
        f"source '{source}' has a leading slash in subdirectory — "
        "this will cause uv pip install to fail"
    )
    assert "subdirectory=" in source


# ---------------------------------------------------------------------------
# 6. URL-referenced behaviors resolve via local alias after discover --register
# ---------------------------------------------------------------------------


def test_resolve_agent_url_behaviors_resolve_via_local_alias(
    tmp_path: Path,
) -> None:
    """After discover --register, URL-referenced behaviors resolve via local alias.

    The amplifier-dev agent references behaviors like:
      behaviors:
        - modes: https://raw.githubusercontent.com/.../modes.yaml

    After 'discover services/ --register', 'modes' is registered locally
    (by ref).  resolve_agent() must find 'modes' via the local alias fallback,
    not try to fetch from the URL and fail.
    """
    registry = Registry(home=tmp_path / "amplifier_home")
    registry.ensure_home()

    # Register a behavior by ref (as discover --register does)
    modes_yaml = """\
behavior:
  ref: test-modes
  uuid: eeeeeeee-0000-0000-0000-000000000001
  description: Test modes behavior
  service:
    stack: uv
    command: test-modes-serve
"""
    registry.register_definition(modes_yaml)

    # Register an agent that references the behavior by URL (not ref)
    agent_yaml = """\
agent:
  ref: test-url-agent
  uuid: ffffffff-0000-0000-0000-000000000001
  orchestrator: streaming
  context_manager: simple
  provider: anthropic
  behaviors:
    - test-modes: https://example.invalid/test-modes.yaml
"""
    registry.register_definition(agent_yaml)

    # resolve_agent must find test-modes via local alias fallback
    result = asyncio.run(resolve_agent(registry, "test-url-agent"))

    service_refs = [ref for ref, _ in result.services]
    assert "test-modes" in service_refs, (
        f"Expected 'test-modes' service in resolved agent {service_refs}. "
        "URL-referenced behaviors must resolve via local alias."
    )


# ---------------------------------------------------------------------------
# 7. Nested settings.yaml format applies overrides during session launch
# ---------------------------------------------------------------------------


def test_settings_nested_format_applies_overrides(tmp_path: Path) -> None:
    """The nested agent→service settings.yaml format is applied during session launch.

    The .amplifier/settings.yaml now uses a nested format:
      amplifier_ipc:
        service_overrides:
          <agent_name>:
            <service_ref>:
              command: [...]
              working_dir: ...

    launch_session() must pass agent_name= to load_settings() so that the
    per-agent service overrides are extracted, not treated as flat service names.
    """
    from amplifier_ipc.cli.session_launcher import launch_session

    registry = Registry(home=tmp_path / "amplifier_home")
    registry.ensure_home()

    agent_yaml = """\
agent:
  ref: settings-test-agent
  uuid: aaaaaaaa-1111-0000-0000-000000000001
  orchestrator: streaming
  context_manager: simple
  provider: anthropic
  service:
    stack: uv
    command: default-serve
"""
    registry.register_definition(agent_yaml)

    # Settings file using the new nested format
    project_settings_dir = tmp_path / ".amplifier"
    project_settings_dir.mkdir()
    project_settings_path = project_settings_dir / "settings.yaml"
    project_settings_path.write_text(
        "amplifier_ipc:\n"
        "  service_overrides:\n"
        "    settings-test-agent:\n"  # agent name
        "      settings-test-agent:\n"  # service ref = agent ref
        "        command: [uv, run, --directory, ./services/test, test-serve]\n"
        "        working_dir: ./services/test\n"
    )

    mock_host_instance = MagicMock()

    with patch("amplifier_ipc.cli.session_launcher.Host") as mock_host_class:
        mock_host_class.return_value = mock_host_instance

        asyncio.run(
            launch_session(
                "settings-test-agent",
                registry=registry,
                project_settings_path=project_settings_path,
            )
        )

    call_args = mock_host_class.call_args
    host_settings = call_args[0][1]  # second positional arg

    # The nested-format override must have been applied (service ref = agent ref)
    assert "settings-test-agent" in host_settings.service_overrides, (
        "Nested settings.yaml service overrides were not applied. "
        "Expected 'settings-test-agent' in service_overrides."
    )
    override = host_settings.service_overrides["settings-test-agent"]
    assert override.command == [
        "uv",
        "run",
        "--directory",
        "./services/test",
        "test-serve",
    ]
    assert override.working_dir == "./services/test"
