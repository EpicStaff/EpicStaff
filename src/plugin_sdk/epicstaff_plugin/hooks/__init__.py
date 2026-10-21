"""The plugin side of EpicStaff's lifecycle hooks: registering handlers, verifying calls.

A plugin backend registers one async handler per hook kind on `hook_registry`, at import
time of its entrypoint module; `python -m epicstaff_plugin.serve` answers EpicStaff's hook
calls with them (`HookDispatchMiddleware`).
"""

from epicstaff_plugin.hooks.assertion_verifier import (
    HookAssertionRejected,
    HookAssertionVerifier,
    VerifiedHook,
    verify_hook_assertion,
)
from epicstaff_plugin.hooks.hook_dispatch import HookDispatchMiddleware
from epicstaff_plugin.hooks.hook_registry import HookHandler, HookRegistry, hook_registry

__all__ = [
    "HookAssertionRejected",
    "HookAssertionVerifier",
    "HookDispatchMiddleware",
    "HookHandler",
    "HookRegistry",
    "VerifiedHook",
    "hook_registry",
    "verify_hook_assertion",
]
