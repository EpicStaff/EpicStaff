def main(file_path: str) -> dict | str:
    from epicstaff_storage import EpicStaffStorage

    storage = EpicStaffStorage()
    try:
        return storage.info(file_path)
    except FileNotFoundError:
        return f"File not found: {file_path}."
    except PermissionError as e:
        return str(e)
    except ValueError as e:
        return str(e)
    except RuntimeError as e:
        return str(e)
