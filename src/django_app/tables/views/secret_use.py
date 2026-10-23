from contextlib import nullcontext

from django.db import transaction
from rbac.scoping.mixins import OrgScopedChildViewSetMixin
from tables.services.secrets.request_actor import actor_from_request
from tables.services.secrets.secret_use_checks import SecretUseCheck


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

    Set `secret_use_check_locks_rows` when the check locks rows it reads
    (`select_for_update`): the check and the save then run in one transaction, so
    the locks hold until the write commits and a concurrent write that takes the
    same lock sees this one. It is off by default because the transaction would
    also wrap the save's side effects: a TelegramTriggerNode's post_save pushes the
    tunnel configs to the webhook service and calls the Telegram API, which must not
    run inside an open transaction.
    """

    secret_use_check: SecretUseCheck | None = None
    secret_use_check_locks_rows: bool = False

    def perform_create(self, serializer):
        self._assert_child_parent_in_active_org(serializer)
        with self._secret_use_transaction():
            self.run_secret_use_check(None, serializer.validated_data)
            super().perform_create(serializer)

    def perform_update(self, serializer):
        self._assert_child_parent_in_active_org(serializer)
        with self._secret_use_transaction():
            self.run_secret_use_check(serializer.instance, serializer.validated_data)
            super().perform_update(serializer)

    def run_secret_use_check(self, instance, data) -> None:
        """Run the secret Use check for a write of `data` over `instance` (None on create).

        Raises:
            SecretUseDeniedError: The write needs secrets:USE and the caller lacks it;
                the project exception handler renders it as a 400 naming the field.
        """
        # Read from the class: an instance lookup would bind a plain function as a method.
        check = type(self).secret_use_check
        if check is None:
            raise NotImplementedError(f"{type(self).__name__} must set secret_use_check.")
        check(actor_from_request(self.request), instance, data)

    def _secret_use_transaction(self):
        return transaction.atomic() if self.secret_use_check_locks_rows else nullcontext()

    def _assert_child_parent_in_active_org(self, serializer) -> None:
        if isinstance(self, OrgScopedChildViewSetMixin):
            self._assert_parent_in_active_org(serializer)
