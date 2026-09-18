def main(file_path: str, content: str) -> str:
    from epicstaff_storage import EpicStaffStorage

    storage = EpicStaffStorage()
    try:
        storage.append_text(file_path, content)
    except PermissionError as e:
        return str(e)
    except ValueError as e:
        return str(e)
    except RuntimeError as e:
        return str(e)

    return f"Appended {len(content)} characters to {file_path}."
