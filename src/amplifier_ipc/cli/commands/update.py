"""Update command — re-fetch behavior URLs and update cached definitions."""

from __future__ import annotations

import hashlib
import urllib.request
from pathlib import Path
from typing import Any

import click
import yaml

from amplifier_ipc.host.definition_registry import Registry

_FETCH_TIMEOUT_SECS: int = 30


def _fetch_url_sync(url: str) -> str:
    """Fetch a URL synchronously and return its content as a string.

    Args:
        url: The HTTP/HTTPS URL to fetch.

    Returns:
        The response body decoded as UTF-8 text.

    Raises:
        OSError: If the request fails or times out.
    """
    with urllib.request.urlopen(url, timeout=_FETCH_TIMEOUT_SECS) as response:  # noqa: S310
        return response.read().decode("utf-8")


def check_for_updates(registry: Any, agent_name: str) -> list[dict[str, Any]]:
    """Check if behavior definitions have been updated at their source URLs.

    Resolves the agent, walks its behavior tree, and for each behavior with a
    ``_meta.source_url`` block, fetches the current content and compares the
    SHA-256 hash against the stored ``_meta.source_hash``.

    Uses a ``visited`` set to avoid infinite loops from cyclic behavior trees.

    Args:
        registry: Registry instance used to resolve agent and behavior paths.
        agent_name: The local_ref alias of the agent to check.

    Returns:
        List of dicts for every behavior that had a ``_meta.source_url``. Each
        dict has the following keys:

        - ``definition_id`` (str): The stem of the behavior definition file.
        - ``local_ref`` (str | None): The behavior's ``local_ref`` field.
        - ``source_url`` (str): The URL stored in ``_meta.source_url``.
        - ``changed`` (bool): True if the remote content hash differs.
        - ``old_hash`` (str): The hash stored in ``_meta.source_hash``.
        - ``new_hash`` (str): The freshly computed ``sha256:<hex>`` hash.
        - ``new_content`` (str): Present only when ``changed`` is True — the
          fetched content that should replace the current definition.
    """
    agent_path = registry.resolve_agent(agent_name)
    agent_def: dict[str, Any] = yaml.safe_load(agent_path.read_text()) or {}
    top_level_behaviors: list[str] = list(agent_def.get("behaviors") or [])

    results: list[dict[str, Any]] = []
    visited: set[str] = set()

    def _walk_behavior(behavior_name: str) -> None:
        if behavior_name in visited:
            return
        visited.add(behavior_name)

        try:
            behavior_path: Path = registry.resolve_behavior(behavior_name)
        except FileNotFoundError:
            return

        behavior_def: dict[str, Any] = yaml.safe_load(behavior_path.read_text()) or {}
        meta = behavior_def.get("_meta")

        if meta and isinstance(meta, dict) and meta.get("source_url"):
            source_url: str = meta["source_url"]
            old_hash: str = meta.get("source_hash", "")
            definition_id: str = behavior_path.stem
            local_ref: str | None = behavior_def.get("local_ref")

            try:
                new_content = _fetch_url_sync(source_url)
                new_hash = (
                    "sha256:" + hashlib.sha256(new_content.encode("utf-8")).hexdigest()
                )

                entry: dict[str, Any] = {
                    "definition_id": definition_id,
                    "local_ref": local_ref,
                    "source_url": source_url,
                    "changed": new_hash != old_hash,
                    "old_hash": old_hash,
                    "new_hash": new_hash,
                }
                if new_hash != old_hash:
                    entry["new_content"] = new_content

                results.append(entry)
            except OSError as exc:
                results.append(
                    {
                        "definition_id": definition_id,
                        "local_ref": local_ref,
                        "source_url": source_url,
                        "changed": False,
                        "old_hash": old_hash,
                        "new_hash": "",
                        "fetch_error": str(exc),
                    }
                )

        # Recurse into nested behaviors
        for nested in list(behavior_def.get("behaviors") or []):
            _walk_behavior(nested)

    for behavior_name in top_level_behaviors:
        _walk_behavior(behavior_name)

    return results


@click.command()
@click.argument("agent")
@click.option(
    "--check",
    is_flag=True,
    default=False,
    help="Dry-run: report available updates without applying them.",
)
@click.option(
    "--home",
    default=None,
    help="Override $AMPLIFIER_HOME path (useful for testing).",
)
def update(agent: str, check: bool, home: str | None) -> None:
    """Re-fetch behavior URLs and update cached definitions for AGENT.

    Walks the agent's behavior tree and checks each behavior whose definition
    contains a ``_meta.source_url``. Reports whether the remote content has
    changed since it was last registered.

    With ``--check``, only reports status without applying any changes.
    Without ``--check``, re-registers changed behaviors via the registry.
    """
    home_path = Path(home) if home else None
    registry = Registry(home=home_path)

    try:
        updates = check_for_updates(registry, agent)
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc

    if not updates:
        click.echo("No behaviors with source URLs found.")
        return

    changed_count = sum(1 for u in updates if u["changed"])

    for entry in updates:
        if "fetch_error" in entry:
            status = f"ERROR ({entry['fetch_error']})"
        elif entry["changed"]:
            status = "CHANGED"
        else:
            status = "up-to-date"
        click.echo(f"  {entry['definition_id']}: {status}")

    if check:
        click.echo(
            f"\n{changed_count} behavior(s) have updates available "
            "(--check mode, not applied)."
        )
        return

    # Apply updates
    applied = 0
    for entry in updates:
        if entry["changed"]:
            try:
                registry.register_definition(
                    entry["new_content"], source_url=entry["source_url"]
                )
                click.echo(f"Updated: {entry['definition_id']}")
                applied += 1
            except (ValueError, OSError) as exc:
                click.echo(f"Error updating {entry['definition_id']}: {exc}")

    click.echo(f"\nApplied {applied} update(s).")
