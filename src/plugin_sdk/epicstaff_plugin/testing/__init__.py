"""Test helpers for plugin backends: forged gateway contexts, hook calls and runtime files.

Never import this in a plugin's production code: it signs with keys no EpicStaff trusts.
"""

from epicstaff_plugin.testing.context_signer import (
    DEFAULT_ORGANIZATION,
    DEFAULT_USER,
    ContextSigner,
)
from epicstaff_plugin.testing.hook_signer import HookCall, HookSigner
from epicstaff_plugin.testing.runtime_file import service_account_key, write_runtime_file

__all__ = [
    "DEFAULT_ORGANIZATION",
    "DEFAULT_USER",
    "ContextSigner",
    "HookCall",
    "HookSigner",
    "service_account_key",
    "write_runtime_file",
]
