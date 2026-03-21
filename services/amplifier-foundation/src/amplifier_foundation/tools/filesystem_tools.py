"""Proxy for filesystem tools — enables discovery via scan_package().

scan_package() only finds *.py files directly in tools/ (not subdirectories).
This proxy creates module-local subclasses with the @tool decorator so that
scan_package() discovers them (obj.__module__ == mod.__name__).
"""

from __future__ import annotations

from amplifier_ipc_protocol import tool

from amplifier_foundation.tools.filesystem.edit import EditTool as _EditTool
from amplifier_foundation.tools.filesystem.read import ReadTool as _ReadTool
from amplifier_foundation.tools.filesystem.write import WriteTool as _WriteTool


@tool
class ReadTool(_ReadTool):
    """ReadTool — discoverable proxy for scan_package()."""

    pass


@tool
class WriteTool(_WriteTool):
    """WriteTool — discoverable proxy for scan_package()."""

    pass


@tool
class EditTool(_EditTool):
    """EditTool — discoverable proxy for scan_package()."""

    pass
