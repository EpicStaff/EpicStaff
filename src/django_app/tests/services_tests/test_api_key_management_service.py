import pytest
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from rbac.models import ApiKey, OrganizationUser
from rbac.models.enums import Permission, ResourceType
from rbac.governance.api_keys import ApiKeyManagementService
from rbac.validation.api_key import ApiKeyValidationService
from rbac.exceptions import (
    ApiKeyNotFoundError,
    FormValidationError,
)

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


@pytest.fixture
def service():
    return ApiKeyManagementService()


@pytest.fixture
def make_key(issue_api_key):
    def _make(owner, org, name="k", **overrides):
        _, key = issue_api_key(user=owner, org=org, name=name, **overrides)
        return key

    return _make


@pytest.fixture
def acme_member(db, django_user_model, acme, role_member):
    user = django_user_model.objects.create_user(
        email="acme-member@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=acme, role=role_member)
    return user


@pytest.fixture
def member_of_both(db, django_user_model, acme, beta, role_member):
    user = django_user_model.objects.create_user(
        email="in-both@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=acme, role=role_member)
    OrganizationUser.objects.create(user=user, org=beta, role=role_member)
    return user


@pytest.fixture
def admin_beta(db, django_user_model, beta, role_org_admin):
    user = django_user_model.objects.create_user(
        email="admin-beta@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=beta, role=role_org_admin)
    return user


@pytest.mark.django_db
def test_list_returns_keys_of_readable_orgs(service, admin_acme, acme_member, acme, make_key):
    make_key(acme_member, acme, name="mine")

    names = [k.name for k in service.list_keys(actor=admin_acme, org_ids=None)]

    assert names == ["mine"]


@pytest.mark.django_db
def test_admin_lists_only_keys_of_their_org(
    service, admin_acme, member_of_both, acme, beta, make_key
):
    make_key(member_of_both, acme, name="acme-key")
    make_key(member_of_both, beta, name="beta-key")

    names = [k.name for k in service.list_keys(actor=admin_acme, org_ids=None)]

    assert names == ["acme-key"]


@pytest.mark.django_db
def test_admin_of_two_orgs_lists_each_key_once(
    service, django_user_model, role_org_admin, acme, beta, member_of_both, make_key
):
    admin_both = django_user_model.objects.create_user(
        email="admin-both@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=admin_both, org=acme, role=role_org_admin)
    OrganizationUser.objects.create(user=admin_both, org=beta, role=role_org_admin)
    make_key(member_of_both, acme, name="acme-key")
    make_key(member_of_both, beta, name="beta-key")

    rows = list(service.list_keys(actor=admin_both, org_ids=None))

    assert sorted((k.name, k.org_id) for k in rows) == [
        ("acme-key", acme.id),
        ("beta-key", beta.id),
    ]


@pytest.mark.django_db
def test_explicit_org_filter_narrows_to_that_org(
    service, django_user_model, role_org_admin, acme, beta, member_of_both, make_key
):
    admin_both = django_user_model.objects.create_user(
        email="admin-both-filter@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=admin_both, org=acme, role=role_org_admin)
    OrganizationUser.objects.create(user=admin_both, org=beta, role=role_org_admin)
    make_key(member_of_both, acme, name="acme-key")
    make_key(member_of_both, beta, name="beta-key")

    names = [k.name for k in service.list_keys(actor=admin_both, org_ids=[beta.id])]

    assert names == ["beta-key"]


@pytest.mark.django_db
def test_list_excludes_superadmin_owned_keys_for_delegated_callers(
    service, admin_acme, superadmin, acme, role_org_admin, make_key
):
    OrganizationUser.objects.create(user=superadmin, org=acme, role=role_org_admin)
    make_key(superadmin, acme, name="platform")

    names = [k.name for k in service.list_keys(actor=admin_acme, org_ids=None)]

    assert "platform" not in names


@pytest.mark.django_db
def test_superadmin_caller_sees_superadmin_owned_keys(
    service, superadmin, django_user_model, acme, make_key
):
    other = django_user_model.objects.create_user(
        email="other-sa@example.com", password="StrongPass123!", is_superadmin=True
    )
    make_key(other, acme, name="peer-platform")

    names = [k.name for k in service.list_keys(actor=superadmin, org_ids=None)]

    assert "peer-platform" in names


@pytest.mark.django_db
def test_list_excludes_system_keys(service, admin_acme, acme_member, acme, make_key):
    ApiKey.objects.create(
        name="system", key_type=ApiKey.KeyType.SYSTEM, prefix="es-sys", key_hash="sys"
    )
    make_key(acme_member, acme, name="user-key")

    names = [k.name for k in service.list_keys(actor=admin_acme, org_ids=None)]

    assert names == ["user-key"]


@pytest.mark.django_db
def test_superadmin_list_still_excludes_system_keys(
    service, superadmin, acme_member, acme, make_key
):
    ApiKey.objects.create(
        name="system",
        key_type=ApiKey.KeyType.SYSTEM,
        prefix="es-sys",
        key_hash="sys-superadmin-path",
    )
    make_key(acme_member, acme, name="user-key-sa")

    names = [k.name for k in service.list_keys(actor=superadmin, org_ids=None)]

    assert "system" not in names
    assert "user-key-sa" in names


@pytest.mark.django_db
def test_revoke_sets_revoked_at_and_is_idempotent(
    service, admin_acme, acme_member, acme, make_key
):
    key = make_key(acme_member, acme, name="target")

    first = service.revoke_key(actor=admin_acme, key_id=key.pk)
    stamp = first.revoked_at
    second = service.revoke_key(actor=admin_acme, key_id=key.pk)

    assert stamp is not None
    assert second.revoked_at == stamp


@pytest.mark.django_db
def test_delete_removes_the_row(service, admin_acme, acme_member, acme, make_key):
    key = make_key(acme_member, acme, name="doomed")

    service.delete_key(actor=admin_acme, key_id=key.pk)

    assert not ApiKey.objects.filter(pk=key.pk).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("operation", ["revoke_key", "delete_key"])
def test_admin_of_another_org_cannot_revoke_after_adding_the_owner(
    service, admin_beta, acme_member, acme, beta, role_member, make_key, operation
):
    key = make_key(acme_member, acme, name="acme-integration")
    OrganizationUser.objects.create(user=acme_member, org=beta, role=role_member)

    with pytest.raises(ApiKeyNotFoundError):
        getattr(service, operation)(actor=admin_beta, key_id=key.pk)

    key.refresh_from_db()
    assert key.revoked_at is None


@pytest.mark.django_db
def test_key_in_an_unreachable_org_is_not_found(
    service, admin_acme, member_of_both, beta, make_key
):
    key = make_key(member_of_both, beta, name="far")

    with pytest.raises(ApiKeyNotFoundError):
        service.revoke_key(actor=admin_acme, key_id=key.pk)


@pytest.mark.django_db
@pytest.mark.parametrize("operation", ["revoke_key", "delete_key"])
def test_superadmin_owned_key_is_not_found_for_delegated_caller(
    service, admin_acme, superadmin, acme, role_org_admin, make_key, operation
):
    OrganizationUser.objects.create(user=superadmin, org=acme, role=role_org_admin)
    key = make_key(superadmin, acme, name="platform")

    with pytest.raises(ApiKeyNotFoundError):
        getattr(service, operation)(actor=admin_acme, key_id=key.pk)


@pytest.mark.django_db
def test_superadmin_caller_may_revoke_a_superadmin_owned_key(
    service, superadmin, django_user_model, acme, make_key
):
    other = django_user_model.objects.create_user(
        email="peer-sa@example.com", password="StrongPass123!", is_superadmin=True
    )
    key = make_key(other, acme, name="peer")

    assert service.revoke_key(actor=superadmin, key_id=key.pk).revoked_at is not None


@pytest.mark.django_db
def test_reader_without_delete_in_key_org_gets_403(
    service, custom_role_user, acme, acme_member, make_key
):
    key = make_key(acme_member, acme, name="guarded")
    reader = custom_role_user(
        acme, "api-key-reader@example.com", {ResourceType.API_KEYS: Permission.READ}
    )

    with pytest.raises(PermissionDenied):
        service.revoke_key(actor=reader, key_id=key.pk)


@pytest.mark.django_db
def test_member_without_api_keys_bits_gets_404(service, member_only, acme_member, acme, make_key):
    key = make_key(acme_member, acme, name="hidden")

    with pytest.raises(ApiKeyNotFoundError):
        service.revoke_key(actor=member_only, key_id=key.pk)


@pytest.mark.django_db
def test_system_key_id_is_not_found(service, admin_acme):
    system = ApiKey.objects.create(
        name="system", key_type=ApiKey.KeyType.SYSTEM, prefix="es-sys", key_hash="sys2"
    )

    with pytest.raises(ApiKeyNotFoundError):
        service.revoke_key(actor=admin_acme, key_id=system.pk)


@pytest.mark.django_db
def test_status_filter_selects_revoked(service, admin_acme, acme_member, acme, make_key):
    make_key(acme_member, acme, name="live")
    make_key(acme_member, acme, name="dead", revoked_at=timezone.now())

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
