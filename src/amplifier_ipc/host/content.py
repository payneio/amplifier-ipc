"""Content resolution — resolve @namespace:path mentions and assemble system prompts.

Provides:

* :func:`assemble_system_prompt` — gathers all ``context/``-prefixed files from
  every registered service, optionally resolves ``@mention`` references found
  within the gathered content via *resolver_chain*, and deduplicates by SHA-256
  hash before formatting as XML context-file blocks.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from amplifier_ipc.host.mentions import MentionResolverChain, resolve_and_load

logger = logging.getLogger(__name__)


def _append_if_unique(
    content: str,
    key: str,
    seen_hashes: set[str],
    parts: list[str],
) -> None:
    """Append a ``<context_file>`` block only if its content hasn't been seen before.

    Args:
        content: The file content to deduplicate and format.
        key: The path identifier used in the ``<context_file path="…">`` attribute.
        seen_hashes: Mutable set of SHA-256 hex digests already added to *parts*.
        parts: Mutable list of formatted XML blocks being assembled.
    """
    h = hashlib.sha256(content.encode()).hexdigest()
    if h not in seen_hashes:
        seen_hashes.add(h)
        parts.append(f'<context_file path="{key}">\n{content}\n</context_file>')


async def assemble_system_prompt(
    registry: Any,
    services: dict[str, Any],
    *,
    resolver_chain: MentionResolverChain | None = None,
) -> str:
    """Assemble a deduplicated system prompt from service context files.

    Gathers every path whose name starts with ``context/`` from all services
    registered in *registry*, optionally resolves ``@mention`` references found
    within each gathered file via *resolver_chain*, deduplicates content by
    SHA-256 hash, and wraps each unique piece of content in an XML
    ``<context_file>`` block.

    Args:
        registry: Service index mapping service keys to their content paths.
        services: Mapping of service key → service object.
        resolver_chain: Optional resolver chain used to resolve ``@mention``
            references found within gathered context files.  When provided,
            :func:`~amplifier_ipc.host.mentions.resolve_and_load` is called on
            each context file's content and the resolved items are appended as
            additional ``<context_file>`` blocks (deduplicated by SHA-256 hash).

    Returns:
        A newline-joined string of ``<context_file path="…">…</context_file>``
        blocks, one per unique content item.
    """
    seen_hashes: set[str] = set()
    parts: list[str] = []

    content_services = registry.get_content_services()

    # Gather context/ files from all registered services
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

            _append_if_unique(content, f"{service_key}:{path}", seen_hashes, parts)

            if resolver_chain is not None:
                resolved_items = resolve_and_load(
                    content, resolver_chain, seen_hashes=seen_hashes
                )
                for item in resolved_items:
                    parts.append(
                        f'<context_file path="{item.key}">\n{item.content}\n</context_file>'
                    )

    return "\n".join(parts)
