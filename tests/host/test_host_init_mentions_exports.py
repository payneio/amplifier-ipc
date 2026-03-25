"""Tests verifying amplifier_ipc.host __init__.py exports for the mentions module."""

from __future__ import annotations


def test_mentions_symbols_importable_from_host() -> None:
    """All mentions symbols are importable directly from amplifier_ipc.host."""
    from amplifier_ipc.host import (  # noqa: F401
        MentionResolverChain,
        NamespaceResolver,
        ResolvedContent,
        WorkingDirResolver,
        parse_mentions,
        resolve_and_load,
    )


def test_mention_resolver_chain_in_all() -> None:
    """MentionResolverChain is listed in amplifier_ipc.host.__all__."""
    import amplifier_ipc.host as host

    assert "MentionResolverChain" in host.__all__


def test_namespace_resolver_in_all() -> None:
    """NamespaceResolver is listed in amplifier_ipc.host.__all__."""
    import amplifier_ipc.host as host

    assert "NamespaceResolver" in host.__all__


def test_working_dir_resolver_in_all() -> None:
    """WorkingDirResolver is listed in amplifier_ipc.host.__all__."""
    import amplifier_ipc.host as host

    assert "WorkingDirResolver" in host.__all__


def test_resolved_content_in_all() -> None:
    """ResolvedContent is listed in amplifier_ipc.host.__all__."""
    import amplifier_ipc.host as host

    assert "ResolvedContent" in host.__all__


def test_parse_mentions_in_all() -> None:
    """parse_mentions is listed in amplifier_ipc.host.__all__."""
    import amplifier_ipc.host as host

    assert "parse_mentions" in host.__all__


def test_resolve_and_load_in_all() -> None:
    """resolve_and_load is listed in amplifier_ipc.host.__all__."""
    import amplifier_ipc.host as host

    assert "resolve_and_load" in host.__all__


def test_resolve_mention_not_importable_from_host() -> None:
    """resolve_mention is NOT importable from amplifier_ipc.host (was removed)."""
    import amplifier_ipc.host as host

    assert not hasattr(host, "resolve_mention")


def test_resolve_mention_not_in_all() -> None:
    """resolve_mention is NOT listed in amplifier_ipc.host.__all__."""
    import amplifier_ipc.host as host

    assert "resolve_mention" not in host.__all__
