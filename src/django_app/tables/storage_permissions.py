from loguru import logger
from rest_framework.permissions import BasePermission


class StoragePermission(BasePermission):
    """
    Stub permission class for storage operations.
    Logs the check and always allows. Will be replaced with real
    authorization logic when permissions are implemented.
    """

    def has_permission(self, request, view):
        action = getattr(view, "storage_action", view.__class__.__name__)
        path = (
            request.query_params.get("path")
            or request.data.get("path")
            or request.data.get("from")
        )
        user = getattr(request, "user", "anonymous")
        logger.info(
            f"[STUB] StoragePermission: action={action}, path={path}, user={user}"
        )
        return True
