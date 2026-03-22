"""Proxy for SkillsTool discovery — scan_package only checks top-level .py files.

scan_package filters by obj.__module__ == mod.__name__, so a plain re-import
won't work. We define a thin subclass here so __module__ matches this file.
"""

from amplifier_ipc.protocol import tool

from amplifier_skills.tools.skills.tool import SkillsTool as _SkillsToolBase


@tool
class SkillsTool(_SkillsToolBase):
    """SkillsTool proxy for IPC discovery."""

    pass


__all__ = ["SkillsTool"]
