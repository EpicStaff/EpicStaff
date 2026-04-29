from .storage import (
    EpicStaffStorage,
    StoragePermissionError,
    get_mutations,
    clear_mutations,
)

storage = EpicStaffStorage()

__all__ = ["storage", "StoragePermissionError", "get_mutations", "clear_mutations"]
