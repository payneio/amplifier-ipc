"""Thin re-export stub: all definitions live in amplifier_ipc_host.definitions.

Uses sys.modules replacement so that patching amplifier_ipc_cli.definitions._fetch_url
also patches amplifier_ipc_host.definitions._fetch_url (they become the same namespace).
"""

import sys

import amplifier_ipc_host.definitions

sys.modules[__name__] = amplifier_ipc_host.definitions
