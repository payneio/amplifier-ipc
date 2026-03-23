"""End-to-end smoke test using the real Anthropic API.

Exercises the full chain with a real LLM API call:
  Host → spawn services → describe → registry → router →
  orchestrator.execute → request.provider_complete (anthropic) → response → events

Requires ANTHROPIC_API_KEY to be set in the environment.
Skipped automatically when the key is absent (e.g. in CI).

Run manually:
    ANTHROPIC_API_KEY=sk-ant-... python -m pytest tests/test_e2e_anthropic.py -v -s --timeout=120

Verify skip (no key):
    python -m pytest tests/test_e2e_anthropic.py -v
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from amplifier_ipc.host.config import HostSettings, ServiceOverride, SessionConfig
from amplifier_ipc.host.events import CompleteEvent, HostEvent, StreamTokenEvent  # noqa: F401
from amplifier_ipc.host.host import Host

# ---------------------------------------------------------------------------
# Environment / service directory constants
# ---------------------------------------------------------------------------

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

FOUNDATION_SERVICE_DIR = (
    Path(__file__).resolve().parents[1] / "services" / "amplifier-foundation"
)
PROVIDERS_SERVICE_DIR = (
    Path(__file__).resolve().parents[1] / "services" / "amplifier-providers"
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


def _make_anthropic_session_config() -> SessionConfig:
    """Return a SessionConfig that exercises the full chain using the Anthropic provider."""
    return SessionConfig(
        services=["amplifier-foundation-serve", "amplifier-providers-serve"],
        orchestrator="streaming",
        context_manager="simple",
        provider="anthropic",
        component_config={
            "anthropic": {
                "api_key": ANTHROPIC_API_KEY,
                "model": "claude-sonnet-4-20250514",
            }
        },
    )


def _make_settings() -> HostSettings:
    """Return HostSettings with service overrides pointing to local source directories."""
    return HostSettings(
        service_overrides={
            "amplifier-foundation-serve": _service_override(FOUNDATION_SERVICE_DIR),
            "amplifier-providers-serve": _service_override(PROVIDERS_SERVICE_DIR),
        }
    )


# ---------------------------------------------------------------------------
# End-to-end smoke test
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not ANTHROPIC_API_KEY or not FOUNDATION_SERVICE_DIR.exists(),
    reason="ANTHROPIC_API_KEY not set or service binary not installed",
)
@pytest.mark.slow
async def test_e2e_anthropic_real_api() -> None:
    """Full chain smoke test using the real Anthropic API.

    Proves:
      - Host spawns services → describe works → orchestrator runs →
        Anthropic provider calls real API → response arrives →
        events flow correctly.

    Requires ANTHROPIC_API_KEY to be set in the environment.
    """
    config = _make_anthropic_session_config()
    settings = _make_settings()
    host = Host(config=config, settings=settings)

    events: list[HostEvent] = []
    token_events: list[StreamTokenEvent] = []

    async for event in host.run("What is 2 + 2? Reply with just the number."):
        events.append(event)
        if isinstance(event, StreamTokenEvent):
            token_events.append(event)
            print(event.token, end="", flush=True)

    print()  # newline after streamed tokens

    complete_events = [e for e in events if isinstance(e, CompleteEvent)]

    assert len(complete_events) >= 1, (
        f"Expected at least one CompleteEvent; got events: {[type(e).__name__ for e in events]}"
    )

    complete = complete_events[0]
    assert complete.result is not None, "CompleteEvent.result must not be None"

    print(f"\nFull response   : {complete.result!r}")
    print(f"Streaming tokens: {len(token_events)}")
    print(f"Total events    : {len(events)}")
