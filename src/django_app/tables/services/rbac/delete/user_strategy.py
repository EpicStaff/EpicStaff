from typing import Optional

from tables.models.rbac_models import User
from tables.services.rbac.delete.strategy import DeleteStrategy
from tables.services.rbac.rbac_exceptions import (
    LastSuperadminError,
    SelfAccountDeletionError,
    UserNotFoundError,
)
from tables.services.rbac.utils.session_invalidation_service import (
    SessionInvalidationService,
)


class UserDeleteStrategy(DeleteStrategy):
    """Permanent delete of a user account."""

    target_type = "user"

    def __init__(
        self, session_invalidator: Optional[SessionInvalidationService] = None
    ):
        self._session_invalidator = session_invalidator or SessionInvalidationService()

    def get_instance(self, target_id: int):
        """Load the user, or raise 404."""
        try:
            return User.objects.get(pk=target_id)
        except User.DoesNotExist as exc:
            raise UserNotFoundError() from exc

    def validate(self, instance, *, actor) -> None:
        """Refuse self-deletion and removal of the last active superadmin."""
        if getattr(actor, "pk", None) == instance.pk:
            raise SelfAccountDeletionError()
        if instance.is_superadmin:
            others_remain = (
                User.objects.filter(is_superadmin=True, is_active=True)
                .exclude(pk=instance.pk)
                .exists()
            )
            if not others_remain:
                raise LastSuperadminError()

    def validate_locked(self, instance, *, actor) -> None:
        """Re-check the last-active-superadmin guard while holding a lock on every superadmin row."""
        if not instance.is_superadmin:
            return
        locked_pks = set(
            User.objects.filter(is_superadmin=True, is_active=True)
            .order_by("pk")
            .select_for_update()
            .values_list("pk", flat=True)
        )
        others_remain = bool(locked_pks - {instance.pk})
        if not others_remain:
            raise LastSuperadminError()

    def describe(self, instance) -> dict:
        """Return the user's identity for the report."""
        return {
            "type": self.target_type,
            "id": instance.pk,
            "email": instance.email,
        }

    def external_artifacts(self, instance) -> list[dict]:
        """Report the avatar file, which lives on local disk, not in MinIO."""
        if not instance.avatar:
            return []
        return [{"kind": "avatar", "path": instance.avatar.name}]

    def snapshot(self, instance) -> dict:
        """Capture the avatar's storage backend and name before deletion."""
        if not instance.avatar:
            return {}
        return {
            "avatar_storage": instance.avatar.storage,
            "avatar_name": instance.avatar.name,
        }

    def pre_delete(self, instance) -> None:
        """Blacklist outstanding refresh tokens while they still link to the user."""
        self._session_invalidator.blacklist_all_for_user(instance)

    def cleanup_external(self, snapshot: dict) -> None:
        """Delete the orphaned avatar file."""
        name = snapshot.get("avatar_name")
        if not name:
            return
        snapshot["avatar_storage"].delete(name)
