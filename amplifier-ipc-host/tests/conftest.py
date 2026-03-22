from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock


def _make_stub(name: str) -> ModuleType:
    mod = ModuleType(name)
    # Give it magic-mock attributes so any attribute access works
    mod.__getattr__ = lambda self, item: MagicMock()  # type: ignore[assignment]
    return mod


# Stub out amplifier_ipc_protocol and its sub-modules before anything tries to
# import amplifier_ipc_host (whose __init__.py pulls in host → lifecycle →
# amplifier_ipc_protocol).  This lets the registry unit-tests run against the
# *source* tree without the full protocol wheel being installed in the test
# runner's Python environment.
for _mod_name in [
    "amplifier_ipc_protocol",
    "amplifier_ipc_protocol.client",
    "amplifier_ipc_protocol.errors",
    "amplifier_ipc_protocol.framing",
    "amplifier_ipc_protocol.types",
]:
    if _mod_name not in sys.modules:
        sys.modules[_mod_name] = MagicMock()
