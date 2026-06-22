def main(file_path: str, content: str) -> str:
    from epicstaff_storage import EpicStaffStorage

    try:
        EpicStaffStorage().append_text(file_path, content)
        return f"Content appended to {file_path} successfully."
    except PermissionError as e:
        return str(e)
