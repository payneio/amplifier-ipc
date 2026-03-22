"""End-to-end smoke test using the mock provider.

Exercises the full chain with no API key required:
  Host → spawn services → describe → registry → router →
  orchestrator.execute → request.provider_complete (mock) → response → events

Requires amplifier-foundation and amplifier-providers service packages to be
installed in their local venvs (services/amplifier-foundation/.venv and
services/amplifier-providers/.venv), AND the protocol Server must handle
orchestrator.execute (i.e., the full IPC orchestrator protocol must be
implemented in the installed protocol package).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from amplifier_ipc_host.config import HostSettings, ServiceOverride, SessionConfig
from amplifier_ipc_host.events import CompleteEvent, HostEvent
from amplifier_ipc_host.host import Host

# ---------------------------------------------------------------------------
# Service directory constants
# ---------------------------------------------------------------------------

FOUNDATION_SERVICE_DIR = (
    Path(__file__).resolve().parents[2] / "services" / "amplifier-foundation"
)
PROVIDERS_SERVICE_DIR = (
    Path(__file__).resolve().parents[2] / "services" / "amplifier-providers"
)

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _service_override(service_dir: Path) -> ServiceOverride:
    """Build a ServiceOverride that runs the service from its local source venv.

    Uses the entry point script installed in the service's .venv so the
    service runs from local source without requiring a global install.

    Args:
        service_dir: Root directory of the service (e.g., services/amplifier-foundation).

    Returns:
        ServiceOverride with command pointing to the venv entry point.
    """
    script_name = service_dir.name + "-serve"  # e.g. "amplifier-foundation-serve"
    venv_script = service_dir / ".venv" / "bin" / script_name
    return ServiceOverride(
        command=[str(venv_script)],
        working_dir=str(service_dir),
    )


def _make_mock_session_config() -> SessionConfig:
    """Return a SessionConfig that exercises the full chain using the mock provider."""
    return SessionConfig(
        services=["amplifier-foundation-serve", "amplifier-providers-serve"],
        orchestrator="streaming",
        context_manager="simple",
        provider="mock",
    )


def _make_settings() -> HostSettings:
    """Return HostSettings with service overrides pointing to local source directories."""
    return HostSettings(
        service_overrides={
            "amplifier-foundation-serve": _service_override(FOUNDATION_SERVICE_DIR),
            "amplifier-providers-serve": _service_override(PROVIDERS_SERVICE_DIR),
        }
    )


def _protocol_server_supports_orchestrator() -> bool:
    """Return True if the installed protocol Server handles orchestrator.execute.

    The full e2e chain requires the protocol Server (in the foundation service's
    venv) to dispatch ``orchestrator.execute`` to the orchestrator component.
    This checks whether that handler is present in the installed server.py.
    """
    try:
        lib_dir = FOUNDATION_SERVICE_DIR / ".venv" / "lib"
        # Find the python version directory (e.g. python3.13)
        python_dirs = list(lib_dir.iterdir()) if lib_dir.exists() else []
        if not python_dirs:
            return False
        server_py = (
            python_dirs[0] / "site-packages" / "amplifier_ipc_protocol" / "server.py"
        )
        if not server_py.exists():
            return False
        return "orchestrator.execute" in server_py.read_text()
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# Availability check
# ---------------------------------------------------------------------------

_SERVICES_AVAILABLE = (
    FOUNDATION_SERVICE_DIR.exists()
    and PROVIDERS_SERVICE_DIR.exists()
    and (
        FOUNDATION_SERVICE_DIR / ".venv" / "bin" / "amplifier-foundation-serve"
    ).exists()
    and (PROVIDERS_SERVICE_DIR / ".venv" / "bin" / "amplifier-providers-serve").exists()
    and _protocol_server_supports_orchestrator()
)

_SKIP_REASON = (
    "Services not installed or protocol Server does not handle orchestrator.execute. "
    "Run `uv sync` in services/amplifier-foundation and services/amplifier-providers, "
    "and ensure the installed amplifier-ipc-protocol Server dispatches orchestrator.execute."
)


# ---------------------------------------------------------------------------
# End-to-end smoke test
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.skipif(not _SERVICES_AVAILABLE, reason=_SKIP_REASON)
async def test_e2e_mock_provider_completes() -> None:
    """Full chain smoke test: Host spawns services, orchestrator runs, mock provider responds.

    Proves:
      - host spawns services → describe works → orchestrator runs →
        mock provider returns a response → events flow correctly.

    No API key is required because the mock provider is used.
    """
    config = _make_mock_session_config()
    settings = _make_settings()
    host = Host(config=config, settings=settings)

    events: list[HostEvent] = []
    async for event in host.run("Say hello"):
        events.append(event)

    complete_events = [e for e in events if isinstance(e, CompleteEvent)]

    assert len(complete_events) >= 1, (
        f"Expected at least one CompleteEvent; got events: {[type(e).__name__ for e in events]}"
    )

    complete = complete_events[0]
    assert complete.result is not None, "CompleteEvent.result must not be None"
