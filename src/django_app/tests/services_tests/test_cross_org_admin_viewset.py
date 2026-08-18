import pytest

from tables.services.rbac.permissions import HasResourcePermissionAnywhere, IsSuperadmin
from tables.services.rbac.rbac_exceptions import OrgContextRequiredError
from tables.views.cross_org_admin import CrossOrgAdminViewSet


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
