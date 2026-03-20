"""Content resolution — resolve @namespace:path mentions and assemble system prompts.

Provides two async functions:

* :func:`resolve_mention` — fetches the content of a single ``@namespace:path``
  mention from the service that owns that namespace.
* :func:`assemble_system_prompt` — gathers all ``context/``-prefixed files from
  every registered service, optionally adds resolved ``@mention`` extras, and
  deduplicates by SHA-256 hash before formatting as XML context-file blocks.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def resolve_mention(mention: str, registry: Any, services: dict[str, Any]) -> str:
    """Resolve a ``@namespace:path`` mention via the ``content.read`` RPC.

    Args:
        mention: The mention string, with or without a leading ``@``.
        registry: A :class:`~amplifier_ipc_host.registry.CapabilityRegistry`
            instance used to look up which service owns *namespace*.
        services: Mapping of service key → service object (must expose a
            ``.client.request(method, params)`` coroutine).

    Returns:
        The content string returned by the service.

    Raises:
        ValueError: With message ``"Invalid mention format"`` if *mention*
            contains no ``:`` separator after stripping the leading ``@``.
        ValueError: With message ``"Unknown content namespace"`` if the
            namespace portion is not registered in *registry*.
    """
    # Strip leading @
    raw = mention.lstrip("@")

    if ":" not in raw:
        raise ValueError("Invalid mention format")

    namespace, path = raw.split(":", 1)

    content_services = registry.get_content_services()
    if namespace not in content_services:
        raise ValueError("Unknown content namespace")

    service = services[namespace]
    result = await service.client.request("content.read", {"path": path})
    return result["content"]


async def assemble_system_prompt(
    registry: Any,
    services: dict[str, Any],
    *,
    mentions: list[str] | None = None,
) -> str:
    """Assemble a deduplicated system prompt from service context files.

    Gathers every path whose name starts with ``context/`` from all services
    registered in *registry*, resolves any extra *mentions*, deduplicates
    content by SHA-256 hash, and wraps each unique piece of content in an XML
    ``<context_file>`` block.

    Args:
        registry: Capability registry mapping service keys to their content paths.
        services: Mapping of service key → service object.
        mentions: Optional list of extra ``@namespace:path`` mentions to resolve
            and include.

    Returns:
        A newline-joined string of ``<context_file path="…">…</context_file>``
        blocks, one per unique content item.
    """
    seen_hashes: set[str] = set()
    parts: list[str] = []

    content_services = registry.get_content_services()

    # 1. Gather context/ files from all registered services
    for service_key, paths in content_services.items():
        service = services.get(service_key)
        if service is None:
            continue

        for path in paths:
            if not path.startswith("context/"):
                continue

            try:
                result = await service.client.request("content.read", {"path": path})
                content: str = result["content"]
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Failed to read content %r from service %r: %s",
                    path,
                    service_key,
                    exc,
                )
                continue

            content_hash = hashlib.sha256(content.encode()).hexdigest()
            if content_hash in seen_hashes:
                continue

            seen_hashes.add(content_hash)
            key = f"{service_key}:{path}"
            parts.append(f'<context_file path="{key}">\n{content}\n</context_file>')

    # 2. Resolve extra @mentions and include unique content
    for mention in mentions or []:
        try:
            content = await resolve_mention(mention, registry, services)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to resolve mention %r: %s", mention, exc)
            continue

        content_hash = hashlib.sha256(content.encode()).hexdigest()
        if content_hash in seen_hashes:
            continue

        seen_hashes.add(content_hash)
        key = mention.lstrip("@")
        parts.append(f'<context_file path="{key}">\n{content}\n</context_file>')

    return "\n".join(parts)
