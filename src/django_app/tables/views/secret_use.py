from collections.abc import Callable

from rbac.exceptions import (
    OrganizationNotFoundError,
    OrgContextRequiredError,
    OrgMembershipRequiredError,
)
from rbac.scoping.fields import resolve_active_org_id
from rbac.scoping.mixins import OrgScopedChildViewSetMixin
from rest_framework import serializers
from tables.services.secrets import SecretActor, SecretUseDeniedError

SecretUseCheck = Callable[[SecretActor | None, object, dict], None]


def actor_from_request(request) -> SecretActor | None:
    """Return who is writing and in which org their secrets:USE is looked up.

    Returns None when there is no request or no authenticated user, which the
    secret Use service denies whenever a write needs Use.

    The org is resolved here, before anyone knows whether the write needs Use, so
    a request without a usable active org must not fail a write that needs none:
    the actor then carries `org_id=None`, which the service treats as "no Use"
    unless the user is a superadmin. Writes that need an org still fail on their
    own org resolution with the usual 400/403/404.
    """
    if request is None:
        return None
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    try:
        org_id = resolve_active_org_id(request)
    except (OrgContextRequiredError, OrgMembershipRequiredError, OrganizationNotFoundError):
        org_id = None
    return SecretActor(user=user, org_id=org_id)


def denial_as_validation_error(denial: SecretUseDeniedError) -> serializers.ValidationError:
    """Turn a domain denial into the ValidationError a serializer would raise for that field.

    The detail is nested along `denial.field_path`, so `("python_code", "secret_ids")`
    renders like an error from the nested PythonCode serializer and the 400
    envelope's message keeps naming the field.
    """
    detail = [denial.message]
    for segment in reversed(denial.field_path):
        detail = {segment: detail}
    return serializers.ValidationError(detail)


class SecretUseCheckedViewSetMixin:
    """Runs the viewset's secret Use check after validation and before the write.

    Set `secret_use_check` to a `check_<entity>_write(actor, instance, data)`
    function. It is read from the class, so a plain function needs no
    `staticmethod`. A viewset that leaves it unset fails on its first write
    instead of writing unchecked.

    Place this BEFORE `OrgScopedViewSetMixin` / `OrgScopedChildViewSetMixin` /
    `OrgScopedHybridViewSetMixin` in the base list: those `perform_create`
    overrides call `serializer.save()` without calling `super()`, so a mixin
    placed after them would never run.

    On a child viewset the parent-in-active-org check runs before the secret
    check, so a write under another org's parent is a 404 (cross-org access is
    never reported as anything else), not a secret Use 400. The child mixin runs
    the same check again afterwards; it is idempotent.

    Custom write paths that bypass `perform_create` / `perform_update` (an upsert
    branch, an overridden `update`) call `run_secret_use_check` themselves.
    """

    secret_use_check: SecretUseCheck | None = None

    def perform_create(self, serializer):
        self._assert_child_parent_in_active_org(serializer)
        self.run_secret_use_check(None, serializer.validated_data)
        super().perform_create(serializer)

    def perform_update(self, serializer):
        self._assert_child_parent_in_active_org(serializer)
        self.run_secret_use_check(serializer.instance, serializer.validated_data)
        super().perform_update(serializer)

    def run_secret_use_check(self, instance, data) -> None:
        """Run the secret Use check for a write of `data` over `instance` (None on create).

        Raises:
            serializers.ValidationError: The write needs secrets:USE and the caller lacks it.
        """
        # Read from the class: an instance lookup would bind a plain function as a method.
        check = type(self).secret_use_check
        if check is None:
            raise NotImplementedError(f"{type(self).__name__} must set secret_use_check.")
        try:
            check(actor_from_request(self.request), instance, data)
        except SecretUseDeniedError as denial:
            raise denial_as_validation_error(denial) from denial

    def _assert_child_parent_in_active_org(self, serializer) -> None:
        if isinstance(self, OrgScopedChildViewSetMixin):
            self._assert_parent_in_active_org(serializer)
