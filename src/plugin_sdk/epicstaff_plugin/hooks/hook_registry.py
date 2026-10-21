"""Where a plugin backend registers the code that runs for each lifecycle hook."""

import inspect
from collections.abc import Awaitable, Callable

from epicstaff_plugin.client.epicstaff_client import OrgClient
from epicstaff_plugin.contracts.hook_api import HOOK_KINDS, HookKind, HookRequest

HookHandler = Callable[[HookRequest, OrgClient], Awaitable[None]]


class HookRegistry:
    """The handler for each hook kind: at most one per kind.

    A handler is a coroutine function taking the verified `HookRequest` and an `OrgClient`
    for the hook's organization, acting as the plugin alone (hooks never act for a person).
    Returning succeeds the hook; raising fails it with the exception's first line as the
    message the SuperAdmin sees. A failed hook is retried with the same `job_id`, so a
    handler does its work at most once per job: look up what an earlier attempt made before
    making it again.

    Register at import time of the module the manifest's `backend.entrypoint` names, on the
    process-wide `hook_registry`:

        from epicstaff_plugin.hooks import hook_registry

        @hook_registry.on_install
        async def install(request, epicstaff):
            ...
    """

    def __init__(self) -> None:
        self._handlers: dict[str, HookHandler] = {}

    def register(self, kind: HookKind, handler: HookHandler) -> HookHandler:
        """Register `handler` for `kind` and return it.

        Raises:
            ValueError: `kind` is not a hook kind, or it already has a handler.
            TypeError: `handler` is neither a coroutine function nor an object whose
                `__call__` is one.
        """
        if kind not in HOOK_KINDS:
            raise ValueError(f"{kind!r} is not a hook kind: one of {', '.join(HOOK_KINDS)}")
        if not _is_async_callable(handler):
            raise TypeError("a hook handler is an async function")
        if kind in self._handlers:
            raise ValueError(f"the {kind} hook already has a handler")
        self._handlers[kind] = handler
        return handler

    def on_install(self, handler: HookHandler) -> HookHandler:
        """Register the install hook: an organization was granted the plugin."""
        return self.register("install", handler)

    def on_upgrade(self, handler: HookHandler) -> HookHandler:
        """Register the upgrade hook: an organization moves to a new version of the plugin."""
        return self.register("upgrade", handler)

    def on_org_removed(self, handler: HookHandler) -> HookHandler:
        """Register the org-removed hook: an organization's grant is being purged."""
        return self.register("org_removed", handler)

    def handler(self, kind: str) -> HookHandler | None:
        """Return the handler registered for `kind`, or None."""
        return self._handlers.get(kind)


def _is_async_callable(handler: object) -> bool:
    return inspect.iscoroutinefunction(handler) or (
        callable(handler) and inspect.iscoroutinefunction(type(handler).__call__)
    )


hook_registry = HookRegistry()
"""This process's hook handlers; `python -m epicstaff_plugin.serve` dispatches to them."""
