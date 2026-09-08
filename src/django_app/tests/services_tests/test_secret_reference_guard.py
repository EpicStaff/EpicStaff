"""The guard consults secrets:USE only when a payload changes the referenced set."""

import pytest
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIRequestFactory

from tables.models import Secret
from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import Permission, ResourceType
from tables.serializers.org_scoped_fields import OrgScopedPrimaryKeyRelatedField
from tables.serializers.utils.secret_reference_guard import SecretReferenceGuardMixin
from tables.services.secrets import secret_service


class _Holder:
    """A stand-in for a model instance carrying one secret FK."""

    def __init__(self, api_key_secret=None):
        self.api_key_secret = api_key_secret


class _GuardedSerializer(SecretReferenceGuardMixin, serializers.Serializer):
    secret_reference_fields = ("api_key_secret_id",)

    api_key_secret_id = OrgScopedPrimaryKeyRelatedField(
        queryset=Secret.objects.all(),
        source="api_key_secret",
        required=False,
        allow_null=True,
    )


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org Guard")


@pytest.fixture
def secret_a(org):
    return secret_service.create(text="sk-a", org=org, name="GUARD_A")


@pytest.fixture
def secret_b(org):
    return secret_service.create(text="sk-b", org=org, name="GUARD_B")


def _request_for(django_user_model, org, *, secrets_bitmask, email):
    """An authenticated request whose role holds exactly `secrets_bitmask` on secrets."""
    from tables.models.rbac_models import RolePermission

    role = Role.objects.create(name=f"role-{email}", org=org, is_built_in=False)
    RolePermission.objects.create(
        role=role,
        resource_type=ResourceType.SECRETS.value,
        permissions=secrets_bitmask,
    )
    user = django_user_model.objects.create_user(email=email, password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=org, role=role)
    request = APIRequestFactory().post("/")
    request.user = user
    request.META["HTTP_X_ORGANIZATION_ID"] = str(org.id)
    return request


@pytest.fixture
def user_with_use(db, django_user_model, org):
    return _request_for(
        django_user_model,
        org,
        secrets_bitmask=int(Permission.READ | Permission.USE),
        email="guard_use@example.com",
    )


@pytest.fixture
def user_without_use(db, django_user_model, org):
    return _request_for(
        django_user_model,
        org,
        secrets_bitmask=int(Permission.READ),
        email="guard_nouse@example.com",
    )


@pytest.mark.django_db
class TestTheDeltaRule:
    def test_omitted_field_needs_no_permission(self, user_without_use, secret_a):
        serializer = _GuardedSerializer(
            _Holder(api_key_secret=secret_a),
            data={},
            context={"request": user_without_use},
        )
        assert serializer.is_valid(), serializer.errors

    def test_resending_the_same_value_needs_no_permission(
        self, user_without_use, secret_a
    ):
        serializer = _GuardedSerializer(
            _Holder(api_key_secret=secret_a),
            data={"api_key_secret_id": secret_a.id},
            context={"request": user_without_use},
        )
        assert serializer.is_valid(), serializer.errors

    def test_changing_the_value_without_use_is_rejected(
        self, user_without_use, secret_a, secret_b
    ):
        serializer = _GuardedSerializer(
            _Holder(api_key_secret=secret_a),
            data={"api_key_secret_id": secret_b.id},
            context={"request": user_without_use},
        )
        assert not serializer.is_valid()
        assert "api_key_secret_id" in serializer.errors

    def test_removing_the_value_without_use_is_rejected(
        self, user_without_use, secret_a
    ):
        serializer = _GuardedSerializer(
            _Holder(api_key_secret=secret_a),
            data={"api_key_secret_id": None},
            context={"request": user_without_use},
        )
        assert not serializer.is_valid()
        assert "api_key_secret_id" in serializer.errors

    def test_adding_on_create_without_use_is_rejected(self, user_without_use, secret_a):
        serializer = _GuardedSerializer(
            data={"api_key_secret_id": secret_a.id},
            context={"request": user_without_use},
        )
        assert not serializer.is_valid()
        assert "api_key_secret_id" in serializer.errors

    def test_creating_with_nothing_attached_is_allowed(self, user_without_use):
        serializer = _GuardedSerializer(data={}, context={"request": user_without_use})
        assert serializer.is_valid(), serializer.errors

    def test_changing_the_value_with_use_is_allowed(
        self, user_with_use, secret_a, secret_b
    ):
        serializer = _GuardedSerializer(
            _Holder(api_key_secret=secret_a),
            data={"api_key_secret_id": secret_b.id},
            context={"request": user_with_use},
        )
        assert serializer.is_valid(), serializer.errors


@pytest.mark.django_db
class TestFailSafe:
    def test_no_request_in_context_denies_the_change(self, secret_a):
        serializer = _GuardedSerializer(
            _Holder(), data={"api_key_secret_id": secret_a.id}
        )
        assert not serializer.is_valid()
