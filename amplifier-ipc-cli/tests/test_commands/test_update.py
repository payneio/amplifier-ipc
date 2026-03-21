"""Tests for commands/update.py — re-fetch behavior URLs and update cached definitions."""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def agent_yaml_with_behaviors() -> str:
    return """\
type: agent
local_ref: my-agent
uuid: 12345678-abcd-efgh-ijkl-mnopqrstuvwx
name: My Test Agent
description: A test agent
behaviors:
  - my-behavior
"""


@pytest.fixture()
def behavior_content() -> str:
    """Raw behavior YAML content (without _meta) used as the upstream source."""
    return """\
type: behavior
local_ref: my-behavior
uuid: 87654321-dcba-hgfe-lkji-xwvutsrqponm
name: My Test Behavior
description: A behavior with source URL
"""


# ---------------------------------------------------------------------------
# Tests for check_for_updates() — no _meta blocks
# ---------------------------------------------------------------------------


class TestCheckForUpdatesNoMeta:
    def test_check_for_updates_no_meta(
        self, tmp_path: Path, agent_yaml_with_behaviors: str
    ) -> None:
        """check_for_updates returns empty list when behaviors have no _meta blocks."""
        from amplifier_ipc_cli.commands.update import check_for_updates

        # Agent file with one behavior reference
        agent_file = tmp_path / "agent_definition.yaml"
        agent_file.write_text(agent_yaml_with_behaviors)

        # Behavior without any _meta block
        behavior_yaml_no_meta = """\
type: behavior
local_ref: my-behavior
uuid: 87654321-dcba-hgfe-lkji-xwvutsrqponm
name: My Test Behavior
description: A behavior without source URL
"""
        behavior_file = tmp_path / "behavior_no_meta.yaml"
        behavior_file.write_text(behavior_yaml_no_meta)

        mock_registry = MagicMock()
        mock_registry.resolve_agent.return_value = agent_file
        mock_registry.resolve_behavior.return_value = behavior_file

        results = check_for_updates(mock_registry, "my-agent")

        assert results == [], (
            f"Expected empty list for behaviors with no _meta, got: {results}"
        )


# ---------------------------------------------------------------------------
# Tests for check_for_updates() — _meta with unchanged hash
# ---------------------------------------------------------------------------


class TestCheckForUpdatesUnchangedMeta:
    def test_check_for_updates_with_unchanged_meta(
        self,
        tmp_path: Path,
        agent_yaml_with_behaviors: str,
        behavior_content: str,
    ) -> None:
        """check_for_updates returns changed=False when fetched content hash matches stored hash."""
        from amplifier_ipc_cli.commands.update import check_for_updates

        # Create agent file
        agent_file = tmp_path / "agent_definition.yaml"
        agent_file.write_text(agent_yaml_with_behaviors)

        # Compute hash of the upstream content
        source_url = "https://example.com/my-behavior.yaml"
        content_bytes = behavior_content.encode("utf-8")
        sha256_hex = hashlib.sha256(content_bytes).hexdigest()

        # Build behavior YAML with a _meta block whose hash matches the upstream
        parsed = yaml.safe_load(behavior_content)
        parsed["_meta"] = {
            "source_url": source_url,
            "source_hash": f"sha256:{sha256_hex}",
            "fetched_at": "2024-01-01T00:00:00+00:00",
        }
        behavior_with_meta = yaml.dump(parsed, default_flow_style=False)

        behavior_file = tmp_path / "behavior_abcd1234.yaml"
        behavior_file.write_text(behavior_with_meta)

        mock_registry = MagicMock()
        mock_registry.resolve_agent.return_value = agent_file
        mock_registry.resolve_behavior.return_value = behavior_file

        # _fetch_url_sync returns the same content → hashes will match
        with patch(
            "amplifier_ipc_cli.commands.update._fetch_url_sync",
            return_value=behavior_content,
        ):
            results = check_for_updates(mock_registry, "my-agent")

        assert len(results) == 1, f"Expected 1 result, got: {results}"
        result = results[0]
        assert result["changed"] is False, (
            f"Expected changed=False when hashes match, got: {result['changed']}"
        )
        assert result["source_url"] == source_url
        assert result["old_hash"] == f"sha256:{sha256_hex}"
        assert result["new_hash"] == f"sha256:{sha256_hex}"
        # new_content should not be present when unchanged
        assert "new_content" not in result, (
            f"new_content should not be set when changed=False, got: {result}"
        )


# ---------------------------------------------------------------------------
# Tests for check_for_updates() — _meta with changed hash
# ---------------------------------------------------------------------------


class TestCheckForUpdatesChangedMeta:
    def test_check_for_updates_with_changed_meta(
        self,
        tmp_path: Path,
        agent_yaml_with_behaviors: str,
        behavior_content: str,
    ) -> None:
        """check_for_updates returns changed=True when URL content differs from stored hash."""
        from amplifier_ipc_cli.commands.update import check_for_updates

        # Create agent file
        agent_file = tmp_path / "agent_definition.yaml"
        agent_file.write_text(agent_yaml_with_behaviors)

        # Hash of the *old* upstream content (stored in _meta)
        source_url = "https://example.com/my-behavior.yaml"
        old_content = behavior_content
        old_sha256_hex = hashlib.sha256(old_content.encode("utf-8")).hexdigest()

        # Build behavior YAML with _meta using the old hash
        parsed = yaml.safe_load(old_content)
        parsed["_meta"] = {
            "source_url": source_url,
            "source_hash": f"sha256:{old_sha256_hex}",
            "fetched_at": "2024-01-01T00:00:00+00:00",
        }
        behavior_with_meta = yaml.dump(parsed, default_flow_style=False)

        behavior_file = tmp_path / "behavior_abcd1234.yaml"
        behavior_file.write_text(behavior_with_meta)

        mock_registry = MagicMock()
        mock_registry.resolve_agent.return_value = agent_file
        mock_registry.resolve_behavior.return_value = behavior_file

        # New upstream content is different
        new_content = old_content + "extra: new_field\n"
        new_sha256_hex = hashlib.sha256(new_content.encode("utf-8")).hexdigest()

        # _fetch_url_sync returns different (updated) content
        with patch(
            "amplifier_ipc_cli.commands.update._fetch_url_sync",
            return_value=new_content,
        ):
            results = check_for_updates(mock_registry, "my-agent")

        assert len(results) == 1, f"Expected 1 result, got: {results}"
        result = results[0]
        assert result["changed"] is True, (
            f"Expected changed=True when hashes differ, got: {result['changed']}"
        )
        assert result["source_url"] == source_url
        assert result["old_hash"] == f"sha256:{old_sha256_hex}"
        assert result["new_hash"] == f"sha256:{new_sha256_hex}"
        assert result["new_content"] == new_content, (
            "new_content should contain the fetched content when changed=True"
        )
