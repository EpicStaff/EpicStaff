from .storage import (
    EpicStaffStorage,
    StorageLineEditMismatchError,
    StoragePermissionError,
    StorageSizeLimitError,
    clear_mutations,
    get_mutations,
)

storage = EpicStaffStorage()

__all__ = [
    "StorageLineEditMismatchError",
    "StoragePermissionError",
    "StorageSizeLimitError",
    "clear_mutations",
    "get_mutations",
    "storage",
]
