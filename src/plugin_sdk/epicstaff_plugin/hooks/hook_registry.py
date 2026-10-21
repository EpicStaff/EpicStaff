"""Where a plugin backend registers the code that runs for each lifecycle hook."""

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from epicstaff_plugin.client.epicstaff_client import EpicStaffClient, OrgClient
from epicstaff_plugin.contracts.hook_api import HOOK_KINDS, HookKind, HookRequest

OrgHookHandler = Callable[[HookRequest, OrgClient], Awaitable[None]]
"""An install or upgrade handler: the verified request, and a client for its organization."""

OrgRemovedHookHandler = Callable[[HookRequest], Awaitable[None]]
"""An organization removed handler: the verified request alone. The organization has no service
account any more, so there is no client to call EpicStaff with."""

HookHandler = OrgHookHandler | OrgRemovedHookHandler

# The kinds whose handler gets no EpicStaff client: their organization holds no key any more.
# Every other kind's handler gets the request and an `OrgClient` for its organization.
_KINDS_WITHOUT_CLIENT = frozenset({"org_removed"})


@dataclass(frozen=True)
class _Registration:
    handler: HookHandler
    takes_client: bool

    async def run(self, request: HookRequest, epicstaff: EpicStaffClient) -> None:
        if self.takes_client:
            await self.handler(request, epicstaff.for_org(request.org.id))
        else:
            await self.handler(request)


class HookRegistry:
    """The handler for each hook kind: at most one per kind.

    A handler is a coroutine function. An install or upgrade handler takes the verified
    `HookRequest` and an `OrgClient` for the hook's organization, acting as the plugin alone
    (hooks never act for a person). An organization removed handler takes the `HookRequest`
    alone: the organization's service account is gone, so it deletes the plugin's own data and
    never calls EpicStaff.

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

        @hook_registry.on_org_removed
        async def org_removed(request):
            ...
    """

    def __init__(self) -> None:
        self._registrations: dict[str, _Registration] = {}

    def register[Handler: HookHandler](self, kind: HookKind, handler: Handler) -> Handler:
        """Register `handler` for `kind` and return it.

        Raises:
            ValueError: `kind` is not a hook kind, or it already has a handler.
            TypeError: `handler` is neither a coroutine function nor an object whose
                `__call__` is one, or it cannot be called with the arguments its kind gets:
                `(request)` for `org_removed`, `(request, epicstaff)` for every other kind.
        """
        if kind not in HOOK_KINDS:
            raise ValueError(f"{kind!r} is not a hook kind: one of {', '.join(HOOK_KINDS)}")
        if not _is_async_callable(handler):
            raise TypeError("a hook handler is an async function")
        takes_client = kind not in _KINDS_WITHOUT_CLIENT
        if not _accepts(handler, 2 if takes_client else 1):
            arguments = "(request, epicstaff)" if takes_client else "(request)"
            raise TypeError(f"the {kind} hook's handler is called with {arguments}")
        if kind in self._registrations:
            raise ValueError(f"the {kind} hook already has a handler")
        self._registrations[kind] = _Registration(handler, takes_client)
        return handler

    def on_install(self, handler: OrgHookHandler) -> OrgHookHandler:
        """Register the install hook: an organization was granted the plugin."""
        return self.register("install", handler)

    def on_upgrade(self, handler: OrgHookHandler) -> OrgHookHandler:
        """Register the upgrade hook: an organization moves to a new version of the plugin."""
        return self.register("upgrade", handler)

    def on_org_removed(self, handler: OrgRemovedHookHandler) -> OrgRemovedHookHandler:
        """Register the organization removed hook: delete the plugin's data for an organization.

        EpicStaff calls it when an organization's data is deleted after its grace period or by
        a SuperAdmin, when the organization is deleted, and when the plugin is deleted.
        """
        return self.register("org_removed", handler)

    def handler(self, kind: str) -> HookHandler | None:
        """Return the handler registered for `kind`, or None."""
        registration = self._registrations.get(kind)
        return None if registration is None else registration.handler

    async def run(self, request: HookRequest, epicstaff: EpicStaffClient) -> None:
        """Run the handler for `request.kind`, with the arguments its kind gets.

        `epicstaff.for_org` is called only for a kind whose handler takes a client.

        Raises:
            LookupError: `request.kind` has no handler.
        """
        registration = self._registrations.get(request.kind)
        if registration is None:
            raise LookupError(f"the {request.kind} hook has no handler")
        await registration.run(request, epicstaff)


def _is_async_callable(handler: object) -> bool:
    return inspect.iscoroutinefunction(handler) or (
        callable(handler) and inspect.iscoroutinefunction(type(handler).__call__)
    )


def _accepts(handler: object, positional_count: int) -> bool:
    try:
        signature = inspect.signature(handler)
    except (TypeError, ValueError):
        # Nothing to check against: the call itself will say what is wrong.
        return True
    try:
        signature.bind(*([None] * positional_count))
    except TypeError:
        return False
    return True


hook_registry = HookRegistry()
"""This process's hook handlers; `python -m epicstaff_plugin.serve` dispatches to them."""
