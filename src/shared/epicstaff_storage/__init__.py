from .storage import (
    EpicStaffStorage,
    StoragePermissionError,
    StorageSizeLimitError,
    StorageLineEditMismatchError,
    get_mutations,
    clear_mutations,
)

storage = EpicStaffStorage()

__all__ = [
    "storage",
    "StoragePermissionError",
    "StorageSizeLimitError",
    "StorageLineEditMismatchError",
    "get_mutations",
    "clear_mutations",
]
