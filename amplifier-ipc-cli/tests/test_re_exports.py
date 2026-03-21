"""Verify CLI registry.py and definitions.py are thin re-export stubs from host."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch


class TestRegistryIsReExport:
    def test_registry_class_is_same_object_as_host(self) -> None:
        """CLI Registry must be the identical class from amplifier_ipc_host.definition_registry."""
        from amplifier_ipc_cli.registry import Registry as CLI_Registry
        from amplifier_ipc_host.definition_registry import Registry as HOST_Registry

        assert CLI_Registry is HOST_Registry, (
            "amplifier_ipc_cli.registry.Registry must be the same object as "
            "amplifier_ipc_host.definition_registry.Registry (thin re-export)"
        )


class TestDefinitionsIsReExport:
    def test_resolved_agent_is_same_class_as_host(self) -> None:
        """CLI ResolvedAgent must be the identical class from amplifier_ipc_host.definitions."""
        from amplifier_ipc_cli.definitions import ResolvedAgent as CLI_ResolvedAgent
        from amplifier_ipc_host.definitions import ResolvedAgent as HOST_ResolvedAgent

        assert CLI_ResolvedAgent is HOST_ResolvedAgent, (
            "amplifier_ipc_cli.definitions.ResolvedAgent must be the same object as "
            "amplifier_ipc_host.definitions.ResolvedAgent (thin re-export)"
        )

    def test_service_entry_is_same_class_as_host(self) -> None:
        """CLI ServiceEntry must be the identical class from amplifier_ipc_host.definitions."""
        from amplifier_ipc_cli.definitions import ServiceEntry as CLI_ServiceEntry
        from amplifier_ipc_host.definitions import ServiceEntry as HOST_ServiceEntry

        assert CLI_ServiceEntry is HOST_ServiceEntry

    def test_parse_agent_definition_is_same_function_as_host(self) -> None:
        """CLI parse_agent_definition must be identical to host's."""
        from amplifier_ipc_cli.definitions import parse_agent_definition as CLI_fn
        from amplifier_ipc_host.definitions import parse_agent_definition as HOST_fn

        assert CLI_fn is HOST_fn

    def test_resolve_agent_is_same_function_as_host(self) -> None:
        """CLI resolve_agent must be identical to host's."""
        from amplifier_ipc_cli.definitions import resolve_agent as CLI_fn
        from amplifier_ipc_host.definitions import resolve_agent as HOST_fn

        assert CLI_fn is HOST_fn

    def test_patching_cli_definitions_fetch_url_affects_host_module(self) -> None:
        """Patching amplifier_ipc_cli.definitions._fetch_url must also patch the host module.

        This is critical for the URL-fetching tests in test_definitions.py to work
        correctly after the definitions module becomes a thin re-export stub.
        """
        import amplifier_ipc_host.definitions as host_defs

        with patch(
            "amplifier_ipc_cli.definitions._fetch_url", new_callable=AsyncMock
        ) as mock_fetch:
            # The patch must affect the host module's _fetch_url since that is
            # where resolve_agent actually looks up the function at call time.
            assert host_defs._fetch_url is mock_fetch, (
                "Patching amplifier_ipc_cli.definitions._fetch_url must modify "
                "amplifier_ipc_host.definitions._fetch_url (they must be the same namespace)"
            )


class TestSessionLauncherImportsFromHost:
    def test_session_launcher_registry_import_is_from_host(self) -> None:
        """session_launcher.py must import Registry directly from amplifier_ipc_host."""
        import importlib
        import importlib.util

        spec = importlib.util.find_spec("amplifier_ipc_cli.session_launcher")
        assert spec is not None
        source_path = spec.origin
        assert source_path is not None

        with open(source_path) as f:
            content = f.read()

        assert "amplifier_ipc_host.definition_registry" in content, (
            "session_launcher.py must import Registry from amplifier_ipc_host.definition_registry"
        )

    def test_session_launcher_definitions_import_is_from_host(self) -> None:
        """session_launcher.py must import ResolvedAgent/resolve_agent from amplifier_ipc_host."""
        import importlib
        import importlib.util

        spec = importlib.util.find_spec("amplifier_ipc_cli.session_launcher")
        assert spec is not None
        source_path = spec.origin
        assert source_path is not None

        with open(source_path) as f:
            content = f.read()

        assert "amplifier_ipc_host.definitions" in content, (
            "session_launcher.py must import from amplifier_ipc_host.definitions"
        )
        # Must NOT import from amplifier_ipc_cli.definitions or amplifier_ipc_cli.registry
        assert "from amplifier_ipc_cli.definitions" not in content, (
            "session_launcher.py must not import from amplifier_ipc_cli.definitions"
        )
        assert "from amplifier_ipc_cli.registry" not in content, (
            "session_launcher.py must not import from amplifier_ipc_cli.registry"
        )
