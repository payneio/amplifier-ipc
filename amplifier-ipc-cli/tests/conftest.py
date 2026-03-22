from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Stub out amplifier_ipc_protocol so that importing amplifier_ipc_host from
# its source tree doesn't require the protocol wheel to be present in the test
# runner's Python environment.
# ---------------------------------------------------------------------------
for _mod_name in [
    "amplifier_ipc_protocol",
    "amplifier_ipc_protocol.client",
    "amplifier_ipc_protocol.errors",
    "amplifier_ipc_protocol.framing",
    "amplifier_ipc_protocol.types",
]:
    if _mod_name not in sys.modules:
        sys.modules[_mod_name] = MagicMock()

# ---------------------------------------------------------------------------
# Make amplifier_ipc_host importable from its source tree so that the CLI's
# registry.py re-export (which does `from amplifier_ipc_host.definition_registry
# import Registry`) resolves correctly when tests run under the system Python.
# ---------------------------------------------------------------------------
_host_src = Path(__file__).parent.parent.parent / "amplifier-ipc-host" / "src"
if _host_src.is_dir():
    _host_src_str = str(_host_src)
    if _host_src_str not in sys.path:
        sys.path.insert(0, _host_src_str)
