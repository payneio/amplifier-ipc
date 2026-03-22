"""Verify that after unification, CLI and host symbols are directly accessible.

After merging into amplifier_ipc, the CLI shims (definitions.py, registry.py)
are gone. These tests verify the merged package structure is correct.
"""

from __future__ import annotations


class TestRegistryAccessible:
    def test_registry_importable_from_host(self) -> None:
        """Registry must be importable from amplifier_ipc.host.definition_registry."""
        from amplifier_ipc.host.definition_registry import Registry

        assert Registry is not None

    def test_registry_importable_via_host_init(self) -> None:
        """Registry must be accessible via amplifier_ipc.host."""
        from amplifier_ipc.host import Registry

        assert Registry is not None


class TestDefinitionsAccessible:
    def test_resolved_agent_importable_from_host(self) -> None:
        """ResolvedAgent must be importable from amplifier_ipc.host.definitions."""
        from amplifier_ipc.host.definitions import ResolvedAgent

        assert ResolvedAgent is not None

    def test_service_entry_importable_from_host(self) -> None:
        """ServiceEntry must be importable from amplifier_ipc.host.definitions."""
        from amplifier_ipc.host.definitions import ServiceEntry

        assert ServiceEntry is not None

    def test_parse_agent_definition_importable(self) -> None:
        """parse_agent_definition must be importable from amplifier_ipc.host.definitions."""
        from amplifier_ipc.host.definitions import parse_agent_definition

        assert callable(parse_agent_definition)

    def test_resolve_agent_importable(self) -> None:
        """resolve_agent must be importable from amplifier_ipc.host.definitions."""
        from amplifier_ipc.host.definitions import resolve_agent

        assert callable(resolve_agent)


class TestSessionLauncherImportsFromHost:
    def test_session_launcher_registry_import_is_from_host(self) -> None:
        """session_launcher.py must import Registry directly from amplifier_ipc.host."""
        import importlib.util

        spec = importlib.util.find_spec("amplifier_ipc.cli.session_launcher")
        assert spec is not None
        source_path = spec.origin
        assert source_path is not None

        with open(source_path) as f:
            content = f.read()

        assert "amplifier_ipc.host.definition_registry" in content, (
            "session_launcher.py must import Registry from amplifier_ipc.host.definition_registry"
        )

    def test_session_launcher_definitions_import_is_from_host(self) -> None:
        """session_launcher.py must import ResolvedAgent/resolve_agent from amplifier_ipc.host."""
        import importlib.util

        spec = importlib.util.find_spec("amplifier_ipc.cli.session_launcher")
        assert spec is not None
        source_path = spec.origin
        assert source_path is not None

        with open(source_path) as f:
            content = f.read()

        assert "amplifier_ipc.host.definitions" in content, (
            "session_launcher.py must import from amplifier_ipc.host.definitions"
        )
        # Must NOT import from amplifier_ipc.cli.definitions or amplifier_ipc.cli.registry
        assert "from amplifier_ipc.cli.definitions" not in content, (
            "session_launcher.py must not import from amplifier_ipc.cli.definitions"
        )
        assert "from amplifier_ipc.cli.registry" not in content, (
            "session_launcher.py must not import from amplifier_ipc.cli.registry"
        )
