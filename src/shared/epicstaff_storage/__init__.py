from .storage import (
    EpicStaffStorage,
    StorageLineEditMismatchError,
    StoragePermissionError,
    StorageQuotaExceededError,
    StorageSizeLimitError,
    check_storage_permission,
    clear_mutations,
    get_mutations,
)

storage = EpicStaffStorage()

__all__ = [
    "StorageLineEditMismatchError",
    "StoragePermissionError",
    "StorageQuotaExceededError",
    "StorageSizeLimitError",
    "check_storage_permission",
    "clear_mutations",
    "get_mutations",
    "storage",
]
