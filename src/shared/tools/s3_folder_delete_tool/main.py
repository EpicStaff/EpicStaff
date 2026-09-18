def main(folder_path: str) -> str:
    from epicstaff_storage import EpicStaffStorage

    storage = EpicStaffStorage()
    try:
        entries = storage.walk(folder_path)
        count = len(entries)
        storage.delete_folder(folder_path)
    except ValueError as e:
        return str(e)
    except FileNotFoundError:
        return f"No such folder: {folder_path}."
    except PermissionError as e:
        return str(e)
    except RuntimeError as e:
        return str(e)

    return f"Deleted folder {folder_path} ({count} object(s) removed)."
