import pytest
from rest_framework.exceptions import PermissionDenied

from tables.models.rbac_models import OrganizationUser, Role, RolePermission
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
        _Svc().resolve_for_write(member_only, beta.id, action=Permission.UPDATE)


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


# ---- visibility rule: a row the caller can neither READ nor act on is 404 ----
#
# `resolve_for_write` decides whether the row is *visible* before the caller's
# `assert_can` decides whether the verb is held. Visibility is "READ or the
# action being attempted", so a 403 is never returned for a row the read
# surface reports as missing (which would confirm the id), while the deliberate
# verb-without-READ path keeps working.


def _role_with(org, name, bits):
    role = Role.objects.create(name=name, org=org, is_built_in=False)
    RolePermission.objects.create(
        role=role, resource_type=ResourceType.ROLES.value, permissions=int(bits)
    )
    return role


def _member_of(django_user_model, org, role, email):
    user = django_user_model.objects.create_user(email=email, password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=org, role=role)
    return user


@pytest.mark.django_db
def test_resolve_for_write_member_without_read_or_verb_is_not_found(member_only, acme):
    with pytest.raises(RoleNotFoundError):
        _Svc().resolve_for_write(member_only, acme.id, action=Permission.UPDATE)


@pytest.mark.django_db
def test_resolve_for_write_read_without_verb_stays_visible(django_user_model, acme):
    reader = _role_with(acme, "ReaderOnly-xorg-vis", Permission.READ)
    user = _member_of(django_user_model, acme, reader, "read-no-update-vis@example.com")

    effective = _Svc().resolve_for_write(user, acme.id, action=Permission.UPDATE)

    assert effective.can(ResourceType.ROLES.value, Permission.READ)
    assert not effective.can(ResourceType.ROLES.value, Permission.UPDATE)


@pytest.mark.django_db
def test_resolve_for_write_verb_without_read_stays_visible(django_user_model, acme):
    updater = _role_with(acme, "UpdaterOnly-xorg-vis", Permission.UPDATE)
    user = _member_of(
        django_user_model, acme, updater, "update-no-read-vis@example.com"
    )

    effective = _Svc().resolve_for_write(user, acme.id, action=Permission.UPDATE)

    assert effective.can(ResourceType.ROLES.value, Permission.UPDATE)
    assert not effective.can(ResourceType.ROLES.value, Permission.READ)


@pytest.mark.django_db
def test_resolve_for_write_superadmin_stays_visible(superadmin, acme):
    effective = _Svc().resolve_for_write(superadmin, acme.id, action=Permission.UPDATE)

    assert effective.is_superadmin
