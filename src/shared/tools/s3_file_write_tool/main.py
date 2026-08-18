def main(file_path: str, content: str) -> str:
    from epicstaff_storage import EpicStaffStorage

    storage = EpicStaffStorage()
    try:
        storage.write(file_path, content)
    except FileNotFoundError:
        return f"File not found: {file_path}."
    except PermissionError as e:
        return str(e)
    except ValueError as e:
        return str(e)
    except RuntimeError as e:
        return str(e)

    return f"Wrote {file_path}."
