import functools

from tables.services.storage_service.enums import StorageAction


def check_permission(method):
    """
    Decorator for single-org StorageManager methods.

    Expects the method signature to be (self, user_name, org_id, path_or_prefix, ...).
    Resolves the StorageAction from the method name at decoration time — a ValueError
    is raised on import if the method name has no matching StorageAction member.

    Calls self._require_permission(user_name, org_id, action, path) before the method
    body, where path is the first positional argument after org_id (empty string for
    methods that take no path, such as list with a default prefix).

    All future permission logic lives inside _require_permission. This decorator
    never needs to change.
    """
    action = StorageAction(method.__name__)

    @functools.wraps(method)
    def wrapper(self, user_name: str, org_id: int, *args, **kwargs):
        path = args[0] if args else ""
        self._require_permission(user_name, org_id, action=action, path=path)
        return method(self, user_name, org_id, *args, **kwargs)

    return wrapper  # type: ignore[return-value]
