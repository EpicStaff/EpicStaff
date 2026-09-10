"""The guard consults secrets:USE only when a payload changes the referenced set."""

import pytest
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIRequestFactory

from tables.models import Secret
from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import Permission, ResourceType
from tables.serializers.org_scoped_fields import OrgScopedPrimaryKeyRelatedField
from tables.serializers.utils.secret_reference_guard_mixin import SecretReferenceGuardMixin
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


class _AbsentFieldSerializer(SecretReferenceGuardMixin, serializers.Serializer):
    """A narrowed subclass whose inherited secret_reference_fields names a field it does not declare."""

    secret_reference_fields = ("retired_secret_id",)


class _ReadOnlyFieldSerializer(SecretReferenceGuardMixin, serializers.Serializer):
    """A narrowed subclass whose guarded field is read_only, so it can never carry an incoming change."""

    secret_reference_fields = ("api_key_secret_id",)

    api_key_secret_id = OrgScopedPrimaryKeyRelatedField(
        read_only=True, source="api_key_secret"
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


@pytest.mark.django_db
class TestNarrowedSubclassFieldIsSkippedNotFatal:
    """A subclass that inherits a guarded field name it no longer exposes must be skipped, not crash the guard."""

    def test_field_absent_from_fields_does_not_raise_or_deny(self, user_without_use):
        serializer = _AbsentFieldSerializer(context={"request": user_without_use})
        assert serializer.validate({}) == {}

    def test_read_only_field_does_not_raise_or_deny(self, user_without_use, secret_a):
        # `attrs` must actually carry the field's source for this to discriminate:
        # with an empty `attrs`, `source not in attrs` already short-circuits the
        # pre-fix code before its missing read_only check would matter. Putting the
        # source in `attrs` drives the pre-fix code past that point and into
        # `_assert_may_use`, which denies (raises ValidationError) because
        # `user_without_use` lacks secrets:USE -- a denial here would mean the
        # read_only skip is missing.
        serializer = _ReadOnlyFieldSerializer(context={"request": user_without_use})
        assert serializer.validate({"api_key_secret": secret_a}) == {
            "api_key_secret": secret_a
        }


class _PerPathUnguardedSerializer(_GuardedSerializer):
    """A per-path subclass that opts its own path out of the guard without touching its base."""

    def get_secret_reference_fields(self):
        """No field is guarded on this path."""
        return ()


class _PerPathWidenedSerializer(SecretReferenceGuardMixin, serializers.Serializer):
    """A per-path subclass that guards a field its class attribute does not name."""

    api_key_secret_id = OrgScopedPrimaryKeyRelatedField(
        queryset=Secret.objects.all(),
        source="api_key_secret",
        required=False,
        allow_null=True,
    )

    def get_secret_reference_fields(self):
        """Guard the field on this path even though secret_reference_fields is empty."""
        return ("api_key_secret_id",)


@pytest.mark.django_db
class TestPerPathFieldOverride:
    """A subclass may diverge from its base's guarded-field list for its own request path."""

    def test_subclass_may_opt_its_own_path_out(self, user_without_use, secret_a):
        serializer = _PerPathUnguardedSerializer(
            _Holder(),
            data={"api_key_secret_id": secret_a.id},
            context={"request": user_without_use},
        )
        assert serializer.is_valid(), serializer.errors

    def test_the_base_class_stays_guarded(self, user_without_use, secret_a):
        # The point of the override is that it is scoped to the subclass: narrowing one
        # request path must not quietly relax the path the base class still serves.
        serializer = _GuardedSerializer(
            _Holder(),
            data={"api_key_secret_id": secret_a.id},
            context={"request": user_without_use},
        )
        assert not serializer.is_valid()
        assert "api_key_secret_id" in serializer.errors

    def test_subclass_may_guard_a_field_its_class_attribute_omits(
        self, user_without_use, secret_a
    ):
        serializer = _PerPathWidenedSerializer(
            _Holder(),
            data={"api_key_secret_id": secret_a.id},
            context={"request": user_without_use},
        )
        assert not serializer.is_valid()
        assert "api_key_secret_id" in serializer.errors
