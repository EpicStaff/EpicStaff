from rbac.models.enums import Permission
from rest_framework.exceptions import PermissionDenied
from src.shared.models.storage_scope import StorageAction
from tables.services.storage_grants.actor import GrantActor, permissions_behind

PERMISSION_LABELS = {
    Permission.READ: "Files: Read",
    Permission.CREATE: "Files: Create",
    Permission.UPDATE: "Files: Update",
    Permission.DELETE: "Files: Delete",
}


def describe_permissions(permissions) -> str:
    """The role permissions as the user sees them: "Files: Create, Files: Update"."""
    return ", ".join(PERMISSION_LABELS[permission] for permission in permissions)


class StorageGrantDeniedError(PermissionDenied):
    """A write needs a Files permission the actor does not hold.

    Rendered as a 403 whose message names every missing role permission (Read, Create,
    Update, Delete); the grant actions they stand for are also in `missing_grants` of the
    body for a client that wants them as data.
    """

    default_code = "storage_grant_denied"

    @classmethod
    def for_actor(
        cls, actor: GrantActor | None, missing, *, change: bool = False
    ) -> "StorageGrantDeniedError":
        """The refusal of `actor` lacking a permission behind each of the actions `missing`."""
        permissions = (
            permissions_behind(missing) if actor is None else actor.missing_permissions(missing)
        )
        return cls(missing, permissions, change=change)

    def __init__(self, missing, missing_permissions, *, change: bool = False):
        self.missing = frozenset(missing)
        self.missing_permissions = list(missing_permissions)
        labels = describe_permissions(self.missing_permissions)
        if change:
            message = (
                f"Changing the files this code can access requires {labels}, which you "
                "don't have. Contact an admin to change it."
            )
        else:
            message = (
                f"This code runs with {labels}, which you don't have. "
                "Contact an admin to change it."
            )
        super().__init__(detail=message)
        self.extra_response_data = {
            "missing_grants": [action.value for action in StorageAction if action in self.missing]
        }
