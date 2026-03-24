"""Provider detection from environment variables for amplifier-ipc.

Scans os.environ for well-known LLM provider API key variables and returns
which providers are available without requiring any network calls.
"""

from __future__ import annotations

import os

__all__ = ["detect_all_providers_from_env", "detect_provider_from_env"]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Ordered list of (provider_name, env_var) checks.
# For providers that can be detected by multiple env vars (e.g. gemini),
# list them in priority order — the first matching var wins per provider.
_PROVIDER_ENV_CHECKS: list[tuple[str, str]] = [
    ("anthropic", "ANTHROPIC_API_KEY"),
    ("openai", "OPENAI_API_KEY"),
    ("azure-openai", "AZURE_OPENAI_API_KEY"),
    ("gemini", "GEMINI_API_KEY"),
    ("gemini", "GOOGLE_API_KEY"),
    ("github-copilot", "GITHUB_TOKEN"),
]

# Providers that require an *additional* env var to be considered fully
# configured (e.g. azure-openai needs both a key and an endpoint).
_REQUIRES_EXTRA: dict[str, str] = {
    "azure-openai": "AZURE_OPENAI_ENDPOINT",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_provider_from_env() -> tuple[str, str] | None:
    """Detect the first available LLM provider from environment variables.

    Walks ``_PROVIDER_ENV_CHECKS`` in order and returns a
    ``(provider_name, env_var_name)`` tuple for the first provider whose
    required env vars are all present and non-empty.

    For ``azure-openai`` the function additionally requires
    ``AZURE_OPENAI_ENDPOINT`` to be set; entries that only have the API key
    without the endpoint are skipped.

    Returns:
        ``(provider_name, env_var_name)`` for the first detected provider,
        or ``None`` if no provider is configured.

    Examples::

        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-..."
        detect_provider_from_env()  # → ("anthropic", "ANTHROPIC_API_KEY")
    """
    for provider, env_var in _PROVIDER_ENV_CHECKS:
        if not os.environ.get(env_var):
            continue
        extra = _REQUIRES_EXTRA.get(provider)
        if extra and not os.environ.get(extra):
            continue
        return (provider, env_var)
    return None


def detect_all_providers_from_env() -> list[tuple[str, str]]:
    """Detect every available LLM provider from environment variables.

    Similar to :func:`detect_provider_from_env` but returns *all* configured
    providers instead of stopping at the first match.  Duplicate provider
    names are deduplicated: only the first matching env var for each provider
    is included (e.g. if both ``GEMINI_API_KEY`` and ``GOOGLE_API_KEY`` are
    set, ``gemini`` is reported only once, using ``GEMINI_API_KEY``).

    Returns:
        A list of ``(provider_name, env_var_name)`` tuples, in the same
        priority order as ``_PROVIDER_ENV_CHECKS``.  Empty list if no
        providers are configured.

    Examples::

        os.environ["OPENAI_API_KEY"] = "sk-..."
        os.environ["GEMINI_API_KEY"] = "AIza..."
        detect_all_providers_from_env()
        # → [("openai", "OPENAI_API_KEY"), ("gemini", "GEMINI_API_KEY")]
    """
    seen: set[str] = set()
    results: list[tuple[str, str]] = []

    for provider, env_var in _PROVIDER_ENV_CHECKS:
        if provider in seen:
            # Already found a var for this provider — skip duplicates.
            continue
        if not os.environ.get(env_var):
            continue
        extra = _REQUIRES_EXTRA.get(provider)
        if extra and not os.environ.get(extra):
            continue
        seen.add(provider)
        results.append((provider, env_var))

    return results
