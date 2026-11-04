from rbac.scoping.mixins import OrgScopedChildViewSetMixin
from tables.services.storage_grants.actor import GrantActor
from tables.services.storage_grants.write_checks import check_storage_grant_write


class StorageGrantCheckedViewSetMixin:
    """Refuses a write of a code-running node whose storage grant the writer's Files permissions do not cover.

    The check is `check_storage_grant_write`, for the model of the viewset's serializer.
    It runs after validation and before the write, with the secrets check, and a
    refusal is a 403 (`StorageGrantDeniedError`), never a silent lowering of the flags.

    Place it BEFORE `OrgScopedChildViewSetMixin`, whose `perform_create` does not call
    `super()`. The parent-in-active-org check runs first, so a write under another
    org's flow is a 404, not a 403.
    """

    def perform_create(self, serializer):
        self._assert_parent_in_active_org_first(serializer)
        self._check_storage_grant(None, serializer)
        super().perform_create(serializer)

    def perform_update(self, serializer):
        self._assert_parent_in_active_org_first(serializer)
        self._check_storage_grant(serializer.instance, serializer)
        super().perform_update(serializer)

    def _check_storage_grant(self, instance, serializer) -> None:
        check_storage_grant_write(
            GrantActor.for_request(self.request),
            instance,
            serializer.validated_data,
            model=serializer.Meta.model,
        )

    def _assert_parent_in_active_org_first(self, serializer) -> None:
        if isinstance(self, OrgScopedChildViewSetMixin):
            self._assert_parent_in_active_org(serializer)
