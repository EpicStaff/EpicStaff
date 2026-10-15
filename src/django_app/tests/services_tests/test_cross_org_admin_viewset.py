from types import SimpleNamespace

import pytest
from django.urls import URLResolver, get_resolver
from rest_framework.permissions import AllowAny, IsAuthenticated

from rbac.access.gates import (
    DenyApiKeyAuth,
    HasResourcePermissionAnywhere,
    IsSuperadmin,
    RestrictApiKeyToUserKeyReads,
)
from rbac.exceptions import OrgContextRequiredError
from rbac.models import ApiKey
from rbac.views.api_keys_admin import ApiKeyAdminViewSet
from rbac.views.cross_org_base import CrossOrgAdminViewSet
from rbac.views.memberships import MembershipAdminViewSet
from rbac.views.organizations import OrganizationAdminViewSet
from rbac.views.roles import RoleAdminViewSet
from rbac.views.users import UserAdminViewSet


class _V(CrossOrgAdminViewSet):
    superadmin_actions = frozenset({"create", "deactivate"})


def test_superadmin_action_uses_is_superadmin():
    v = _V()
    v.action = "create"
    assert any(isinstance(p, IsSuperadmin) for p in v.get_permissions())


def test_normal_action_uses_door_gate():
    v = _V()
    v.action = "list"
    assert any(isinstance(p, HasResourcePermissionAnywhere) for p in v.get_permissions())


def test_parse_org_ids_parses_and_defaults():
    assert _V.parse_org_ids("1,2,3") == [1, 2, 3]
    assert _V.parse_org_ids(None) is None
    assert _V.parse_org_ids("") is None


def test_parse_org_ids_rejects_non_integer():
    with pytest.raises(OrgContextRequiredError):
        _V.parse_org_ids("1,abc")


def test_cross_org_surfaces_share_one_paginator():
    from rbac.views.cross_org_base import CrossOrgAdminPagination
    from rbac.views.memberships import MembershipAdminViewSet
    from rbac.views.organizations import OrganizationAdminViewSet
    from rbac.views.roles import RoleAdminViewSet

    assert CrossOrgAdminPagination.page_size == 50
    assert CrossOrgAdminPagination.max_page_size == 200
    assert CrossOrgAdminPagination.page_size_query_param == "page_size"
    for viewset in (RoleAdminViewSet, MembershipAdminViewSet, OrganizationAdminViewSet):
        assert viewset.pagination_class is CrossOrgAdminPagination


# Every action each admin viewset exposes. Written out by hand so a new action
# shows up as a failing comparison against the viewset, not as silent coverage.
ADMIN_VIEWSET_ACTIONS = [
    (RoleAdminViewSet, ["list", "retrieve", "create", "partial_update", "destroy"]),
    (
        MembershipAdminViewSet,
        ["list", "assignable_users", "create", "partial_update", "destroy"],
    ),
    (
        OrganizationAdminViewSet,
        [
            "list",
            "retrieve",
            "create",
            "partial_update",
            "deactivate",
            "reactivate",
            "destroy",
        ],
    ),
    (ApiKeyAdminViewSet, ["list", "revoke", "destroy"]),
    (
        UserAdminViewSet,
        [
            "list",
            "create",
            "grant_superadmin",
            "revoke_superadmin",
            "deactivate",
            "reactivate",
            "destroy",
        ],
    ),
]


_STANDARD_VIEWSET_ACTIONS = (
    "list",
    "create",
    "retrieve",
    "update",
    "partial_update",
    "destroy",
)


def _actions_the_viewset_defines(viewset_class):
    """Standard CRUD methods the class has, plus every @action and its extra
    method mappings (`@x.mapping.delete`)."""
    actions = {name for name in _STANDARD_VIEWSET_ACTIONS if hasattr(viewset_class, name)}
    for extra_action in viewset_class.get_extra_actions():
        actions.update(extra_action.mapping.values())
    return actions


def _actions_the_urlconf_routes_to(viewset_class):
    """Actions wired to this class anywhere in the URLconf — catches a plain
    method mapped by hand with `as_view({"get": "assignable_users"})`."""
    actions = set()
    pending = list(get_resolver().url_patterns)
    while pending:
        pattern = pending.pop()
        if isinstance(pattern, URLResolver):
            pending.extend(pattern.url_patterns)
        elif getattr(pattern.callback, "cls", None) is viewset_class:
            actions.update((getattr(pattern.callback, "actions", None) or {}).values())
    return actions


def _reachable_actions(viewset_class):
    return _actions_the_viewset_defines(viewset_class) | _actions_the_urlconf_routes_to(
        viewset_class
    )


def _permissions_for(viewset_class, action, **initkwargs):
    view = viewset_class(**initkwargs)
    view.action = action
    return view.get_permissions()


@pytest.mark.parametrize(
    "viewset_class, actions",
    ADMIN_VIEWSET_ACTIONS,
    ids=[viewset_class.__name__ for viewset_class, _ in ADMIN_VIEWSET_ACTIONS],
)
def test_gate_coverage_list_names_exactly_the_actions_the_viewset_exposes(viewset_class, actions):
    assert set(actions) == _reachable_actions(viewset_class)


@pytest.mark.parametrize(
    "viewset_class, action",
    [
        (viewset_class, action)
        for viewset_class, actions in ADMIN_VIEWSET_ACTIONS
        for action in actions
    ],
)
def test_api_key_gate_runs_first_for_every_action(viewset_class, action):
    permissions = _permissions_for(viewset_class, action)
    assert isinstance(permissions[0], RestrictApiKeyToUserKeyReads)
    assert any(isinstance(p, IsAuthenticated) for p in permissions)


@pytest.mark.parametrize(
    "viewset_class",
    [viewset_class for viewset_class, _ in ADMIN_VIEWSET_ACTIONS],
    ids=[viewset_class.__name__ for viewset_class, _ in ADMIN_VIEWSET_ACTIONS],
)
def test_action_level_permission_classes_cannot_drop_the_api_key_gate(viewset_class):
    # `@action(permission_classes=...)` reaches the view as this initkwarg.
    permissions = _permissions_for(viewset_class, "list", permission_classes=[AllowAny])
    assert isinstance(permissions[0], RestrictApiKeyToUserKeyReads)
    assert any(isinstance(p, AllowAny) for p in permissions)


@pytest.mark.parametrize(
    "viewset_class",
    [viewset_class for viewset_class, _ in ADMIN_VIEWSET_ACTIONS],
    ids=[viewset_class.__name__ for viewset_class, _ in ADMIN_VIEWSET_ACTIONS],
)
def test_superadmin_actions_name_only_actions_the_viewset_exposes(viewset_class):
    superadmin_actions = set(getattr(viewset_class, "superadmin_actions", frozenset()))
    assert superadmin_actions <= _reachable_actions(viewset_class)


@pytest.mark.parametrize("action", sorted(OrganizationAdminViewSet.superadmin_actions))
def test_organization_superadmin_actions_swap_door_gate_for_is_superadmin(action):
    permissions = _permissions_for(OrganizationAdminViewSet, action)
    assert any(isinstance(p, IsSuperadmin) for p in permissions)
    assert not any(isinstance(p, HasResourcePermissionAnywhere) for p in permissions)


class _SubclassWithExtraGate(CrossOrgAdminViewSet):
    permission_classes = [IsAuthenticated, DenyApiKeyAuth, HasResourcePermissionAnywhere]
    superadmin_actions = frozenset({"create"})


def test_superadmin_action_keeps_the_declared_permission_classes():
    permissions = _permissions_for(_SubclassWithExtraGate, "create")
    assert any(isinstance(p, DenyApiKeyAuth) for p in permissions)
    assert any(isinstance(p, IsSuperadmin) for p in permissions)
    assert any(isinstance(p, RestrictApiKeyToUserKeyReads) for p in permissions)


class _SubclassWithoutTheGateInItsList(CrossOrgAdminViewSet):
    permission_classes = [IsAuthenticated]


def test_overriding_permission_classes_does_not_drop_the_api_key_gate():
    permissions = _permissions_for(_SubclassWithoutTheGateInItsList, "create")
    assert any(isinstance(p, RestrictApiKeyToUserKeyReads) for p in permissions)


# ---- RestrictApiKeyToUserKeyReads ----


def _request(method, auth):
    return SimpleNamespace(method=method, auth=auth)


def _key(key_type):
    return ApiKey(key_type=key_type)


@pytest.mark.parametrize("method", ["GET", "POST", "PATCH", "PUT", "DELETE"])
def test_gate_lets_non_key_callers_through(method):
    assert RestrictApiKeyToUserKeyReads().has_permission(_request(method, None), None)


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
def test_gate_lets_user_key_read(method):
    gate = RestrictApiKeyToUserKeyReads()
    assert gate.has_permission(_request(method, _key(ApiKey.KeyType.USER)), None)


@pytest.mark.parametrize("method", ["POST", "PATCH", "PUT", "DELETE"])
def test_gate_rejects_user_key_write(method):
    gate = RestrictApiKeyToUserKeyReads()
    assert not gate.has_permission(_request(method, _key(ApiKey.KeyType.USER)), None)
    assert gate.message == RestrictApiKeyToUserKeyReads.write_message


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS", "POST", "PATCH", "DELETE"])
def test_gate_rejects_system_key_on_every_method(method):
    gate = RestrictApiKeyToUserKeyReads()
    assert not gate.has_permission(_request(method, _key(ApiKey.KeyType.SYSTEM)), None)
    assert gate.message == RestrictApiKeyToUserKeyReads.non_user_key_message
