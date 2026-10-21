"""secrets:USE is required only when a write changes which secret reaches where.

Three seams, each tested on its own terms:

- SecretReferenceGuard: actor + changes in, SecretUseDeniedError out.
- SecretPolicy.changes: a RowWrite in, the changes it describes out.
- SecretReferenceGuardMixin: a serializer payload in, a field-keyed 400 out.
"""

import pytest
from rest_framework import serializers
from rest_framework.test import APIRequestFactory

from rbac.models import Organization, OrganizationUser, Role, RolePermission
from rbac.models.enums import Permission, ResourceType
from rbac.scoping.fields import OrgScopedPrimaryKeyRelatedField
from tables.models import Secret
from tables.serializers.utils.secret_reference_guard_mixin import SecretReferenceGuardMixin
from tables.services.secrets import SecretUseDeniedError, secret_service
from tables.services.secrets.policies import LLM_CONFIG_SECRET_POLICY, RowWrite, SecretPolicy
from tables.services.secrets.reference_guard import (
    SecretActor,
    SecretDestinationChange,
    SecretReferenceChange,
    secret_reference_guard,
)

REFERENCE_DENIED = (
    'Changing the secrets referenced here requires the "Use" permission on '
    "Secrets. The existing selection was left unchanged. Ask an organization "
    "admin to grant it."
)
DESTINATION_DENIED = (
    'Changing where this sends its secrets requires the "Use" permission on '
    "Secrets. The existing value was left unchanged. Ask an organization admin "
    "to grant it."
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


def _actor(request, org):
    return SecretActor(user=request.user, org_id=org.id)


# ---------------------------------------------------------------------------
# SecretReferenceGuard -- plain data in, SecretUseDeniedError out
# ---------------------------------------------------------------------------


UNCHANGED = [
    [],
    [SecretReferenceChange(field_name="api_key_secret_id", incoming=frozenset({1}), current=frozenset({1}))],
    [SecretReferenceChange(field_name="secret_ids", incoming=frozenset(), current=frozenset())],
    [
        SecretDestinationChange(
            incoming={"base_url": "https://a.example"}, current={"base_url": "https://a.example"}
        )
    ],
]


@pytest.mark.django_db
class TestGuard:
    @pytest.mark.parametrize("changes", UNCHANGED)
    def test_an_unchanged_write_needs_no_actor_at_all(self, changes):
        assert secret_reference_guard.requires_use(changes) is False
        secret_reference_guard.assert_permitted(actor=None, changes=changes)

    @pytest.mark.parametrize(
        "changes,expected_field,expected_message",
        [
            (
                [SecretReferenceChange(field_name="api_key_secret_id", incoming=frozenset({2}), current=frozenset({1}))],
                "api_key_secret_id",
                REFERENCE_DENIED,
            ),
            (
                [SecretReferenceChange(field_name="extra_headers", incoming=frozenset({"A"}), current=frozenset())],
                "extra_headers",
                REFERENCE_DENIED,
            ),
            (
                [
                    SecretDestinationChange(
                        incoming={"model": 7, "base_url": "https://b.example"},
                        current={"model": 7, "base_url": "https://a.example"},
                    )
                ],
                "base_url",
                DESTINATION_DENIED,
            ),
            # The first change that changes anything names the error, in list order.
            (
                [
                    SecretReferenceChange(field_name="unchanged", incoming=frozenset({1}), current=frozenset({1})),
                    SecretReferenceChange(field_name="second", incoming=frozenset(), current=frozenset({1})),
                    SecretDestinationChange(incoming={"base_url": "b"}, current={"base_url": "a"}),
                ],
                "second",
                REFERENCE_DENIED,
            ),
        ],
    )
    def test_a_change_without_use_is_denied_on_its_field(
        self, user_without_use, org, changes, expected_field, expected_message
    ):
        assert secret_reference_guard.requires_use(changes) is True
        with pytest.raises(SecretUseDeniedError) as denial:
            secret_reference_guard.assert_permitted(actor=_actor(user_without_use, org), changes=changes)

        assert denial.value.field_name == expected_field
        assert denial.value.message == expected_message

    def test_a_change_with_use_is_permitted(self, user_with_use, org):
        changes = [
            SecretReferenceChange(field_name="api_key_secret_id", incoming=frozenset({2}), current=frozenset({1}))
        ]

        secret_reference_guard.assert_permitted(actor=_actor(user_with_use, org), changes=changes)

    def test_a_change_with_no_actor_is_denied(self):
        changes = [
            SecretReferenceChange(field_name="api_key_secret_id", incoming=frozenset({2}), current=frozenset())
        ]

        with pytest.raises(SecretUseDeniedError) as denial:
            secret_reference_guard.assert_permitted(actor=None, changes=changes)

        assert denial.value.field_name == "api_key_secret_id"

    def test_use_held_in_another_org_does_not_count(self, user_with_use):
        # The same user holds USE in `org`, and only READ here.
        other_org = Organization.objects.create(name="Org Elsewhere")
        read_only_role = Role.objects.create(name="read-only-elsewhere", org=other_org, is_built_in=False)
        RolePermission.objects.create(
            role=read_only_role, resource_type=ResourceType.SECRETS.value, permissions=int(Permission.READ)
        )
        OrganizationUser.objects.create(user=user_with_use.user, org=other_org, role=read_only_role)
        changes = [
            SecretReferenceChange(field_name="api_key_secret_id", incoming=frozenset({2}), current=frozenset())
        ]

        with pytest.raises(SecretUseDeniedError):
            secret_reference_guard.assert_permitted(
                actor=SecretActor(user=user_with_use.user, org_id=other_org.id), changes=changes
            )


# ---------------------------------------------------------------------------
# SecretPolicy.changes -- a RowWrite in, changes out, no DRF
# ---------------------------------------------------------------------------


class _Row:
    """A stand-in for a persisted row."""

    def __init__(self, **values):
        self.__dict__.update(values)


class _BaseUrlPolicy(SecretPolicy):
    """Sends a secret to its own base_url when `carries` says so."""

    reference_fields = ("api_key_secret_id",)

    def __init__(self, *, carries: bool):
        self.carries = carries

    def destination(self, write):
        return {"base_url": write.value_after_save("base_url")}

    def carries_secret(self, write):
        return self.carries


def _write(instance, attrs, writable_fields):
    return RowWrite(
        instance=instance,
        attrs=attrs,
        writable_fields=writable_fields,
        persisted_value=lambda source: getattr(instance, source, None),
    )


class TestPolicyChanges:
    def test_reference_fields_compare_by_linked_pk(self):
        persisted = _Row(api_key_secret=_Row(pk=1), base_url="https://a.example")
        write = _write(persisted, {"api_key_secret": _Row(pk=2)}, {"api_key_secret_id": "api_key_secret"})

        assert _BaseUrlPolicy(carries=True).changes(write) == [
            SecretReferenceChange(field_name="api_key_secret_id", incoming=frozenset({2}), current=frozenset({1}))
        ]

    @pytest.mark.parametrize(
        "writable_fields",
        [
            # The writer does not expose the field at all.
            {},
            # The writer exposes it, but the payload omits it.
            {"retired_secret_id": "retired_secret"},
        ],
    )
    def test_a_field_the_write_does_not_set_yields_no_change(self, writable_fields):
        write = _write(_Row(api_key_secret=None), {"api_key_secret": _Row(pk=2)}, writable_fields)

        assert SecretPolicy().changes(write) == []

    def test_a_moved_destination_that_carries_a_secret_is_a_change(self):
        persisted = _Row(base_url="https://a.example")
        write = _write(persisted, {"base_url": "https://b.example"}, {"base_url": "base_url"})

        assert _BaseUrlPolicy(carries=True).changes(write) == [
            SecretDestinationChange(
                incoming={"base_url": "https://b.example"}, current={"base_url": "https://a.example"}
            )
        ]

    def test_a_moved_destination_that_carries_no_secret_is_no_change(self):
        persisted = _Row(base_url="https://a.example")
        write = _write(persisted, {"base_url": "https://b.example"}, {"base_url": "base_url"})

        assert _BaseUrlPolicy(carries=False).changes(write) == []

    def test_the_destination_of_a_new_row_is_never_a_change(self):
        write = RowWrite.for_new_row({"base_url": "https://b.example"})

        assert _BaseUrlPolicy(carries=True).changes(write) == []

    def test_a_blank_and_a_null_routing_value_are_the_same_destination(self):
        persisted = _Row(base_url=None, name="model")
        write = _write(persisted, {"base_url": ""}, {"base_url": "base_url", "name": "name"})

        assert write.writable_values_after_save(exclude=frozenset()) == write.persisted().writable_values_after_save(
            exclude=frozenset()
        )


@pytest.mark.django_db
class TestImportedHeaderMarkers:
    """An import creates the row, so any marker in its headers is a change."""

    def _assert_import(self, actor, headers):
        changes = LLM_CONFIG_SECRET_POLICY.changes(RowWrite.for_new_row({"extra_headers": headers}))
        secret_reference_guard.assert_permitted(actor=actor, changes=changes)

    def test_markers_without_use_are_denied(self, user_without_use, org):
        with pytest.raises(SecretUseDeniedError) as denial:
            self._assert_import(_actor(user_without_use, org), {"X-K": "epicstaff_secret(GUARD_A)"})

        assert denial.value.field_name == "extra_headers"

    def test_markers_with_use_are_permitted(self, user_with_use, org):
        self._assert_import(_actor(user_with_use, org), {"X-K": "epicstaff_secret(GUARD_A)"})

    @pytest.mark.parametrize("headers", [None, {}, {"X-Trace": "1"}, ["X-K"], "X-K: value"])
    def test_headers_without_markers_need_no_permission(self, user_without_use, org, headers):
        self._assert_import(_actor(user_without_use, org), headers)

    def test_no_user_denies_markers(self):
        with pytest.raises(SecretUseDeniedError):
            self._assert_import(None, {"X-K": "epicstaff_secret(GUARD_A)"})


# ---------------------------------------------------------------------------
# SecretReferenceGuardMixin -- the serializer adapter
# ---------------------------------------------------------------------------


class _ApiKeyPolicy(SecretPolicy):
    reference_fields = ("api_key_secret_id",)


class _GuardedSerializer(SecretReferenceGuardMixin, serializers.Serializer):
    secret_policy = _ApiKeyPolicy()

    api_key_secret_id = OrgScopedPrimaryKeyRelatedField(
        queryset=Secret.objects.all(),
        source="api_key_secret",
        required=False,
        allow_null=True,
    )


class _ReadOnlyFieldSerializer(SecretReferenceGuardMixin, serializers.Serializer):
    """A narrowed variant whose guarded field is read_only, so it never carries an incoming change."""

    secret_policy = _ApiKeyPolicy()

    api_key_secret_id = OrgScopedPrimaryKeyRelatedField(read_only=True, source="api_key_secret")


class _PerPathUnguardedSerializer(_GuardedSerializer):
    """A per-path subclass that opts its own path out without touching its base."""

    secret_policy = SecretPolicy()


@pytest.mark.django_db
class TestAdapterDeltaRule:
    def test_omitted_field_needs_no_permission(self, user_without_use, secret_a):
        serializer = _GuardedSerializer(
            _Row(api_key_secret=secret_a), data={}, context={"request": user_without_use}
        )
        assert serializer.is_valid(), serializer.errors

    def test_resending_the_same_value_needs_no_permission(self, user_without_use, secret_a):
        serializer = _GuardedSerializer(
            _Row(api_key_secret=secret_a),
            data={"api_key_secret_id": secret_a.id},
            context={"request": user_without_use},
        )
        assert serializer.is_valid(), serializer.errors

    def test_changing_the_value_without_use_is_a_400_on_that_field(
        self, user_without_use, secret_a, secret_b
    ):
        serializer = _GuardedSerializer(
            _Row(api_key_secret=secret_a),
            data={"api_key_secret_id": secret_b.id},
            context={"request": user_without_use},
        )
        assert not serializer.is_valid()
        assert serializer.errors == {"api_key_secret_id": [REFERENCE_DENIED]}

    def test_removing_the_value_without_use_is_rejected(self, user_without_use, secret_a):
        serializer = _GuardedSerializer(
            _Row(api_key_secret=secret_a),
            data={"api_key_secret_id": None},
            context={"request": user_without_use},
        )
        assert not serializer.is_valid()
        assert "api_key_secret_id" in serializer.errors

    def test_adding_on_create_without_use_is_rejected(self, user_without_use, secret_a):
        serializer = _GuardedSerializer(
            data={"api_key_secret_id": secret_a.id}, context={"request": user_without_use}
        )
        assert not serializer.is_valid()
        assert "api_key_secret_id" in serializer.errors

    def test_creating_with_nothing_attached_is_allowed(self, user_without_use):
        serializer = _GuardedSerializer(data={}, context={"request": user_without_use})
        assert serializer.is_valid(), serializer.errors

    def test_changing_the_value_with_use_is_allowed(self, user_with_use, secret_a, secret_b):
        serializer = _GuardedSerializer(
            _Row(api_key_secret=secret_a),
            data={"api_key_secret_id": secret_b.id},
            context={"request": user_with_use},
        )
        assert serializer.is_valid(), serializer.errors

    def test_no_request_in_context_denies_the_change(self, secret_a):
        serializer = _GuardedSerializer(_Row(api_key_secret=None), data={"api_key_secret_id": secret_a.id})
        assert not serializer.is_valid()
        assert "api_key_secret_id" in serializer.errors

    def test_a_read_only_field_is_skipped(self, user_without_use, secret_a):
        # `attrs` carries the source on purpose: with it empty, the skip would be untested.
        serializer = _ReadOnlyFieldSerializer(context={"request": user_without_use})
        assert serializer.validate({"api_key_secret": secret_a}) == {"api_key_secret": secret_a}


@pytest.mark.django_db
class TestPerPathPolicy:
    def test_a_subclass_may_opt_its_own_path_out(self, user_without_use, secret_a):
        serializer = _PerPathUnguardedSerializer(
            _Row(api_key_secret=None),
            data={"api_key_secret_id": secret_a.id},
            context={"request": user_without_use},
        )
        assert serializer.is_valid(), serializer.errors

    def test_the_base_class_stays_guarded(self, user_without_use, secret_a):
        serializer = _GuardedSerializer(
            _Row(api_key_secret=None),
            data={"api_key_secret_id": secret_a.id},
            context={"request": user_without_use},
        )
        assert not serializer.is_valid()
        assert "api_key_secret_id" in serializer.errors


class _HeaderPolicy(SecretPolicy):
    header_fields = ("extra_headers",)


class _HeaderGuardedSerializer(SecretReferenceGuardMixin, serializers.Serializer):
    secret_policy = _HeaderPolicy()

    extra_headers = serializers.JSONField(required=False)


@pytest.mark.django_db
class TestAdapterHeaderMarkers:
    """Only the set of marker names counts; the rest of a header's text is free to change."""

    @pytest.mark.parametrize(
        "persisted,incoming",
        [
            ({"X-K": "epicstaff_secret(GUARD_A)"}, {"X-K": "epicstaff_secret(GUARD_A)"}),
            ({"X-K": "epicstaff_secret(GUARD_A)"}, {"X-K": "Bearer epicstaff_secret( GUARD_A )"}),
            (
                {"X-K": "epicstaff_secret(GUARD_A)"},
                {"X-Other": "epicstaff_secret(GUARD_A)", "X-Trace": "1"},
            ),
            ({}, {"X-Trace": "1"}),
            (None, {"X-Trace": "1"}),
        ],
    )
    def test_same_marker_names_need_no_permission(self, user_without_use, persisted, incoming):
        serializer = _HeaderGuardedSerializer(
            _Row(extra_headers=persisted),
            data={"extra_headers": incoming},
            context={"request": user_without_use},
        )
        assert serializer.is_valid(), serializer.errors

    @pytest.mark.parametrize(
        "persisted,incoming",
        [
            ({}, {"X-K": "epicstaff_secret(GUARD_A)"}),
            ({"X-K": "epicstaff_secret(GUARD_A)"}, {"X-K": "epicstaff_secret(GUARD_B)"}),
            (
                {"X-K": "epicstaff_secret(GUARD_A)"},
                {"X-K": "epicstaff_secret(GUARD_A)", "X-L": "epicstaff_secret(GUARD_B)"},
            ),
            ({"X-K": "epicstaff_secret(GUARD_A)"}, {}),
        ],
    )
    def test_changed_marker_names_without_use_are_rejected(self, user_without_use, persisted, incoming):
        serializer = _HeaderGuardedSerializer(
            _Row(extra_headers=persisted),
            data={"extra_headers": incoming},
            context={"request": user_without_use},
        )
        assert not serializer.is_valid()
        assert serializer.errors == {"extra_headers": [REFERENCE_DENIED]}

    def test_an_unchanged_write_never_resolves_the_active_org(self, user_without_use):
        # Without the header the active org cannot be resolved at all; a resend must
        # still pass, because it changes nothing.
        del user_without_use.META["HTTP_X_ORGANIZATION_ID"]
        serializer = _HeaderGuardedSerializer(
            _Row(extra_headers={"X-K": "epicstaff_secret(GUARD_A)"}),
            data={"extra_headers": {"X-K": "epicstaff_secret(GUARD_A)"}},
            context={"request": user_without_use},
        )
        assert serializer.is_valid(), serializer.errors

    def test_changed_marker_names_with_use_are_allowed(self, user_with_use):
        serializer = _HeaderGuardedSerializer(
            _Row(extra_headers={"X-K": "epicstaff_secret(GUARD_A)"}),
            data={"extra_headers": {"X-K": "epicstaff_secret(GUARD_B)"}},
            context={"request": user_with_use},
        )
        assert serializer.is_valid(), serializer.errors


class _DestinationGuardedSerializer(SecretReferenceGuardMixin, serializers.Serializer):
    secret_policy = _BaseUrlPolicy(carries=True)

    base_url = serializers.CharField(required=False, allow_null=True)


@pytest.mark.django_db
class TestAdapterDestination:
    def test_moving_a_secret_bearing_destination_without_use_is_a_400_on_that_field(
        self, user_without_use
    ):
        serializer = _DestinationGuardedSerializer(
            _Row(base_url="https://api.example.com"),
            data={"base_url": "https://attacker.example"},
            context={"request": user_without_use},
        )
        assert not serializer.is_valid()
        assert serializer.errors == {"base_url": [DESTINATION_DENIED]}

    def test_moving_a_secret_bearing_destination_with_use_is_allowed(self, user_with_use):
        serializer = _DestinationGuardedSerializer(
            _Row(base_url="https://api.example.com"),
            data={"base_url": "https://attacker.example"},
            context={"request": user_with_use},
        )
        assert serializer.is_valid(), serializer.errors

    def test_create_is_not_gated_by_the_destination(self, user_without_use):
        serializer = _DestinationGuardedSerializer(
            data={"base_url": "https://attacker.example"}, context={"request": user_without_use}
        )
        assert serializer.is_valid(), serializer.errors
