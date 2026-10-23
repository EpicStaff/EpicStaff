"""The DRF views of the URLconf a plugin's service-account key can authenticate on."""

from dataclasses import dataclass

from django.urls import URLPattern, URLResolver, get_resolver
from plugins.identity.service_account_authentication import PluginServiceAccountAuthentication
from rest_framework.views import APIView


@dataclass(frozen=True)
class RoutedView:
    """One routed DRF view, with what it runs for that route (a viewset action's own included).

    `permission_classes_by_action` maps each action of the route (None for a plain view) to
    the permission classes `get_permissions()` returns for it, so a gate a view adds in code
    counts like a declared one.
    """

    dotted_path: str
    route: str
    view_class: type
    authentication_classes: tuple
    permission_classes_by_action: dict
    throttle_classes: tuple
    explicit_throttle_classes: bool


def _patterns(patterns, prefix=""):
    for pattern in patterns:
        if isinstance(pattern, URLResolver):
            yield from _patterns(pattern.url_patterns, prefix + str(pattern.pattern))
        elif isinstance(pattern, URLPattern):
            yield prefix + str(pattern.pattern), pattern.callback


def _permission_classes(view_class, initkwargs: dict, action: str | None) -> tuple:
    view = view_class(**{key: value for key, value in initkwargs.items() if hasattr(view_class, key)})
    view.action = action
    view.kwargs = {}
    return tuple(type(permission) for permission in view.get_permissions())


def drf_views():
    """Every routed DRF view, one entry per route."""
    for route, callback in _patterns(get_resolver().url_patterns):
        view_class = getattr(callback, "cls", None)
        if view_class is None or not issubclass(view_class, APIView):
            continue
        initkwargs = getattr(callback, "initkwargs", {}) or {}
        actions = sorted(set((getattr(callback, "actions", None) or {}).values())) or [None]
        yield RoutedView(
            dotted_path=f"{view_class.__module__}.{view_class.__qualname__}",
            route=route,
            view_class=view_class,
            authentication_classes=tuple(initkwargs.get("authentication_classes", view_class.authentication_classes)),
            permission_classes_by_action={action: _permission_classes(view_class, initkwargs, action) for action in actions},
            throttle_classes=tuple(initkwargs.get("throttle_classes", view_class.throttle_classes)),
            explicit_throttle_classes="throttle_classes" in initkwargs
            or any("throttle_classes" in vars(klass) for klass in view_class.__mro__ if klass is not APIView),
        )


def plugin_reachable_views():
    """The routed DRF views whose authenticators include the service-account class."""
    return [
        view
        for view in drf_views()
        if any(issubclass(authenticator, PluginServiceAccountAuthentication) for authenticator in view.authentication_classes)
    ]
