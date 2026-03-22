"""Proxy for BashTool — enables discovery via scan_package().

scan_package() only finds *.py files directly in tools/ (not subdirectories).
This proxy creates a module-local subclass with the @tool decorator so that
scan_package() discovers it (obj.__module__ == mod.__name__).
"""

from __future__ import annotations

from amplifier_ipc.protocol import tool

from amplifier_foundation.tools.bash import BashTool as _BashTool


@tool
class BashTool(_BashTool):
    """BashTool — discoverable proxy for scan_package()."""

    pass
