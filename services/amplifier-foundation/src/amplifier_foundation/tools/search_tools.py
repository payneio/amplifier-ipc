"""Proxy for search tools — enables discovery via scan_package().

scan_package() only finds *.py files directly in tools/ (not subdirectories).
This proxy creates module-local subclasses with the @tool decorator so that
scan_package() discovers them (obj.__module__ == mod.__name__).
"""

from __future__ import annotations

from amplifier_ipc.protocol import tool

from amplifier_foundation.tools.search.glob import GlobTool as _GlobTool
from amplifier_foundation.tools.search.grep import GrepTool as _GrepTool


@tool
class GrepTool(_GrepTool):
    """GrepTool — discoverable proxy for scan_package()."""

    pass


@tool
class GlobTool(_GlobTool):
    """GlobTool — discoverable proxy for scan_package()."""

    pass
