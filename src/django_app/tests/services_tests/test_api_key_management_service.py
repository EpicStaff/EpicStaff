import pytest
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from tables.models.rbac_models import ApiKey, OrganizationUser
from tables.services.rbac.api_key.management_service import ApiKeyManagementService
from tables.services.rbac.api_key.validation import ApiKeyValidationService
from tables.services.rbac.rbac_exceptions import (
    ApiKeyNotFoundError,
    FormValidationError,
)

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


@pytest.fixture
def service():
    return ApiKeyManagementService()


@pytest.fixture
def make_key(db):
    def _make(owner, name="k", revoked_at=None, expires_at=None):
        return ApiKey.objects.create(
            name=name,
            key_type=ApiKey.KeyType.USER,
            prefix="es-000000000",
            key_hash=f"hash-{owner.id}-{name}",
            created_by=owner,
            revoked_at=revoked_at,
            expires_at=expires_at,
        )

    return _make


@pytest.fixture
def acme_member(db, django_user_model, acme, role_member):
    user = django_user_model.objects.create_user(
        email="acme-member@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=acme, role=role_member)
    return user


@pytest.mark.django_db
def test_list_returns_keys_of_members_of_readable_orgs(
    service, admin_acme, acme_member, make_key
):
    make_key(acme_member, name="mine")

    names = [k.name for k in service.list_keys(actor=admin_acme, org_ids=None)]

    assert names == ["mine"]


@pytest.mark.django_db
def test_list_excludes_keys_from_unreadable_orgs(
    service, admin_acme, django_user_model, beta, role_member, make_key
):
    outsider = django_user_model.objects.create_user(
        email="beta-only-key@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=outsider, org=beta, role=role_member)
    make_key(outsider, name="hidden")

    names = [k.name for k in service.list_keys(actor=admin_acme, org_ids=None)]

    assert "hidden" not in names


@pytest.mark.django_db
def test_list_excludes_superadmin_owned_keys_for_delegated_callers(
    service, admin_acme, superadmin, acme, role_org_admin, make_key
):
    OrganizationUser.objects.create(user=superadmin, org=acme, role=role_org_admin)
    make_key(superadmin, name="platform")

    names = [k.name for k in service.list_keys(actor=admin_acme, org_ids=None)]

    assert "platform" not in names


@pytest.mark.django_db
def test_superadmin_caller_sees_superadmin_owned_keys(
    service, superadmin, django_user_model, make_key
):
    other = django_user_model.objects.create_user(
        email="other-sa@example.com", password="StrongPass123!", is_superadmin=True
    )
    make_key(other, name="peer-platform")

    names = [k.name for k in service.list_keys(actor=superadmin, org_ids=None)]

    assert "peer-platform" in names


@pytest.mark.django_db
def test_owner_in_two_readable_orgs_yields_one_row(
    service, django_user_model, role_org_admin, role_member, acme, beta, make_key
):
    admin_both = django_user_model.objects.create_user(
        email="admin-both@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=admin_both, org=acme, role=role_org_admin)
    OrganizationUser.objects.create(user=admin_both, org=beta, role=role_org_admin)
    owner = django_user_model.objects.create_user(
        email="in-both@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=owner, org=acme, role=role_member)
    OrganizationUser.objects.create(user=owner, org=beta, role=role_member)
    make_key(owner, name="once")

    rows = list(service.list_keys(actor=admin_both, org_ids=None))

    assert [k.name for k in rows] == ["once"]


@pytest.mark.django_db
def test_list_excludes_system_keys(service, admin_acme, acme_member, make_key):
    ApiKey.objects.create(
        name="system", key_type=ApiKey.KeyType.SYSTEM, prefix="es-sys", key_hash="sys"
    )
    make_key(acme_member, name="user-key")

    names = [k.name for k in service.list_keys(actor=admin_acme, org_ids=None)]

    assert names == ["user-key"]


@pytest.mark.django_db
def test_superadmin_list_still_excludes_system_keys(
    service, superadmin, django_user_model, make_key
):
    ApiKey.objects.create(
        name="system",
        key_type=ApiKey.KeyType.SYSTEM,
        prefix="es-sys",
        key_hash="sys-superadmin-path",
    )
    owner = django_user_model.objects.create_user(
        email="sa-visible@example.com", password="StrongPass123!"
    )
    make_key(owner, name="user-key-sa")

    names = [k.name for k in service.list_keys(actor=superadmin, org_ids=None)]

    assert "system" not in names
    assert "user-key-sa" in names


@pytest.mark.django_db
def test_orphan_owner_keys_are_invisible_to_delegated_callers(
    service, admin_acme, django_user_model, make_key
):
    orphan = django_user_model.objects.create_user(
        email="orphan@example.com", password="StrongPass123!"
    )
    make_key(orphan, name="orphan-key")

    names = [k.name for k in service.list_keys(actor=admin_acme, org_ids=None)]

    assert "orphan-key" not in names


@pytest.mark.django_db
def test_revoke_sets_revoked_at_and_is_idempotent(
    service, admin_acme, acme_member, make_key
):
    key = make_key(acme_member, name="target")

    first = service.revoke_key(actor=admin_acme, key_id=key.pk)
    stamp = first.revoked_at
    second = service.revoke_key(actor=admin_acme, key_id=key.pk)

    assert stamp is not None
    assert second.revoked_at == stamp


@pytest.mark.django_db
def test_delete_removes_the_row(service, admin_acme, acme_member, make_key):
    key = make_key(acme_member, name="doomed")

    service.delete_key(actor=admin_acme, key_id=key.pk)

    assert not ApiKey.objects.filter(pk=key.pk).exists()


@pytest.mark.django_db
def test_unreachable_key_is_not_found(
    service, admin_acme, django_user_model, beta, role_member, make_key
):
    outsider = django_user_model.objects.create_user(
        email="unreachable@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=outsider, org=beta, role=role_member)
    key = make_key(outsider, name="far")

    with pytest.raises(ApiKeyNotFoundError):
        service.revoke_key(actor=admin_acme, key_id=key.pk)


@pytest.mark.django_db
def test_superadmin_owned_key_is_not_found_for_delegated_caller(
    service, admin_acme, superadmin, acme, role_org_admin, make_key
):
    OrganizationUser.objects.create(user=superadmin, org=acme, role=role_org_admin)
    key = make_key(superadmin, name="platform")

    with pytest.raises(ApiKeyNotFoundError):
        service.revoke_key(actor=admin_acme, key_id=key.pk)


@pytest.mark.django_db
def test_superadmin_caller_may_revoke_a_superadmin_owned_key(
    service, superadmin, django_user_model, make_key
):
    other = django_user_model.objects.create_user(
        email="peer-sa@example.com", password="StrongPass123!", is_superadmin=True
    )
    key = make_key(other, name="peer")

    assert service.revoke_key(actor=superadmin, key_id=key.pk).revoked_at is not None


@pytest.mark.django_db
def test_member_without_the_bit_is_denied(service, member_only, acme_member, make_key):
    key = make_key(acme_member, name="guarded")

    with pytest.raises(PermissionDenied):
        service.revoke_key(actor=member_only, key_id=key.pk)


@pytest.mark.django_db
def test_system_key_id_is_not_found(service, admin_acme):
    system = ApiKey.objects.create(
        name="system", key_type=ApiKey.KeyType.SYSTEM, prefix="es-sys", key_hash="sys2"
    )

    with pytest.raises(ApiKeyNotFoundError):
        service.revoke_key(actor=admin_acme, key_id=system.pk)


@pytest.mark.django_db
def test_attach_visible_orgs_limits_to_readable_orgs(
    service, admin_acme, django_user_model, acme, beta, role_member, make_key
):
    owner = django_user_model.objects.create_user(
        email="two-orgs@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=owner, org=acme, role=role_member)
    OrganizationUser.objects.create(user=owner, org=beta, role=role_member)
    key = make_key(owner, name="spanning")

    service.attach_visible_orgs(keys=[key], actor=admin_acme)

    assert key._visible_org_ids == [acme.id]


@pytest.mark.django_db
def test_status_filter_selects_revoked(service, admin_acme, acme_member, make_key):
    make_key(acme_member, name="live")
    make_key(acme_member, name="dead", revoked_at=timezone.now())

    names = [
        k.name
        for k in service.list_keys(
            actor=admin_acme, org_ids=None, status_value="revoked"
        )
    ]

    assert names == ["dead"]


def test_validate_list_keys_query_passes_valid_filters():
    cleaned = ApiKeyValidationService().validate_list_keys_query(
        {"status": "active", "user": "7", "search": "laptop"}
    )

    assert cleaned == {
        "owner_id": 7,
        "status_value": "active",
        "search": "laptop",
    }


def test_validate_list_keys_query_defaults_absent_filters_to_none():
    cleaned = ApiKeyValidationService().validate_list_keys_query({})

    assert cleaned == {"owner_id": None, "status_value": None, "search": None}


def test_validate_list_keys_query_rejects_unknown_status():
    with pytest.raises(FormValidationError):
        ApiKeyValidationService().validate_list_keys_query({"status": "bogus"})


def test_validate_list_keys_query_rejects_non_integer_user():
    with pytest.raises(FormValidationError):
        ApiKeyValidationService().validate_list_keys_query({"user": "abc"})
