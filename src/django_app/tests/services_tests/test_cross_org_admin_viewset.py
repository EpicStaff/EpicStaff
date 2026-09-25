import pytest

from rbac.access.gates import HasResourcePermissionAnywhere, IsSuperadmin
from rbac.exceptions import OrgContextRequiredError
from rbac.views.cross_org_base import CrossOrgAdminViewSet


class _V(CrossOrgAdminViewSet):
    superadmin_actions = frozenset({"create", "deactivate"})


def test_superadmin_action_uses_is_superadmin():
    v = _V()
    v.action = "create"
    assert any(isinstance(p, IsSuperadmin) for p in v.get_permissions())


def test_normal_action_uses_door_gate():
    v = _V()
    v.action = "list"
    assert any(
        isinstance(p, HasResourcePermissionAnywhere) for p in v.get_permissions()
    )


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


def test_api_key_admin_viewset_has_empty_superadmin_actions():
    """DenyApiKeyAuth is dropped for any action later added to this set."""
    from rbac.views.api_keys_admin import ApiKeyAdminViewSet

    assert ApiKeyAdminViewSet.superadmin_actions == frozenset()
