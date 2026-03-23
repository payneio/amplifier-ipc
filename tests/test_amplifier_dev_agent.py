"""
Validation tests for the rewritten amplifier-dev agent definition.
The file must have: agent: top-level key with ref, uuid, orchestrator, provider,
3 behaviors as {alias: url} dicts, and a service block with command.
"""

from __future__ import annotations

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).parent.parent
AGENT_FILE = (
    PROJECT_ROOT / "services" / "amplifier-foundation" / "agents" / "amplifier-dev.yaml"
)


def load_yaml(path: Path) -> dict:
    with path.open() as f:
        return yaml.safe_load(f)


def test_amplifier_dev_agent_spec() -> None:
    """amplifier-dev.yaml must conform to full spec format."""
    data = load_yaml(AGENT_FILE)

    # Top-level key must be 'agent'
    assert "agent" in data, "Missing top-level 'agent' key"

    inner = data["agent"]

    assert inner["ref"] == "amplifier-dev", (
        f"ref mismatch: expected 'amplifier-dev', got '{inner.get('ref')}'"
    )
    assert inner["uuid"] == "52d19e87-24ba-4291-a872-69d963b96ce9", (
        f"uuid mismatch: got '{inner.get('uuid')}'"
    )
    assert inner["orchestrator"] == "streaming", (
        f"orchestrator mismatch: expected 'streaming', got '{inner.get('orchestrator')}'"
    )
    assert inner["provider"] == "providers:anthropic", (
        f"provider mismatch: expected 'providers:anthropic', got '{inner.get('provider')}'"
    )
    assert len(inner["behaviors"]) == 3, (
        f"behaviors count mismatch: expected 3, got {len(inner.get('behaviors', []))}"
    )
    assert inner["service"]["command"] == "amplifier-foundation-serve", (
        f"service.command mismatch: expected 'amplifier-foundation-serve', "
        f"got '{inner.get('service', {}).get('command')}'"
    )
