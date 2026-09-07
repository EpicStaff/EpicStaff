import pytest
from rest_framework.exceptions import PermissionDenied

from tables.models.rbac_models.rbac_enums import Permission, ResourceType
from tables.services.rbac.cross_org_service import CrossOrgResourceService
from tables.services.rbac.rbac_exceptions import RoleNotFoundError

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


class _Svc(CrossOrgResourceService):
    rbac_resource_type = ResourceType.ROLES
    not_found_exception = RoleNotFoundError


@pytest.mark.django_db
def test_readable_org_ids_superadmin_is_none(superadmin):
    assert _Svc().resolve_readable_org_ids(superadmin) is None


@pytest.mark.django_db
def test_readable_org_ids_member_only_where_read(admin_acme, acme):
    # Org Admin has ROLES.read in acme; nowhere else.
    assert _Svc().resolve_readable_org_ids(admin_acme) == {acme.id}


@pytest.mark.django_db
def test_readable_org_ids_plain_member_is_empty(member_only):
    assert _Svc().resolve_readable_org_ids(member_only) == set()


@pytest.mark.django_db
def test_resolve_for_write_non_member_raises_not_found(member_only, beta):
    with pytest.raises(RoleNotFoundError):
        _Svc().resolve_for_write(member_only, beta.id)


@pytest.mark.django_db
def test_apply_org_scope_forbidden_org_ids_fails_loud(admin_acme, beta):
    from tables.models.rbac_models import Role

    with pytest.raises(PermissionDenied):
        _Svc().apply_org_scope(
            actor=admin_acme,
            org_ids=[beta.id],
            base_qs=Role.objects.filter(is_built_in=False),
            org_field="org_id",
        )


@pytest.mark.django_db
def test_apply_org_scope_superadmin_no_filter(superadmin, acme, beta, role_member):
    from tables.models.rbac_models import Role

    Role.objects.create(name="A", org=acme, is_built_in=False)
    Role.objects.create(name="B", org=beta, is_built_in=False)
    qs = _Svc().apply_org_scope(
        actor=superadmin,
        org_ids=None,
        base_qs=Role.objects.filter(is_built_in=False),
        org_field="org_id",
    )
    assert qs.count() == 2  # sees both orgs' custom roles
