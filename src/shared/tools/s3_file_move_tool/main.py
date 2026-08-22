def main(from_path: str, to_path: str) -> str:
    from epicstaff_storage import EpicStaffStorage

    storage = EpicStaffStorage()
    try:
        storage.move(from_path, to_path)
    except FileNotFoundError:
        return f"Source file not found: {from_path}."
    except PermissionError as e:
        return str(e)
    except ValueError as e:
        return str(e)
    except RuntimeError as e:
        return str(e)

    return f"Moved {from_path} to {to_path}."
