def main(folder_path: str) -> str:
    from epicstaff_storage import EpicStaffStorage

    storage = EpicStaffStorage()
    try:
        if storage.exists(folder_path):
            return f"Folder already exists: {folder_path}."
        storage.mkdir(folder_path)
    except FileNotFoundError:
        return f"Folder not found: {folder_path}."
    except PermissionError as e:
        return str(e)
    except ValueError as e:
        return str(e)
    except RuntimeError as e:
        return str(e)

    return f"Folder created: {folder_path}."
