from .storage import (
    EpicStaffStorage,
    StorageLineEditMismatchError,
    StoragePermissionError,
    StorageSizeLimitError,
    check_storage_permission,
    clear_mutations,
    get_mutations,
)

storage = EpicStaffStorage()

__all__ = [
    "StorageLineEditMismatchError",
    "StoragePermissionError",
    "StorageSizeLimitError",
    "check_storage_permission",
    "clear_mutations",
    "get_mutations",
    "storage",
]
