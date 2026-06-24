def main(file_path: str, content: str = "") -> str:
    from epicstaff_storage import EpicStaffStorage

    try:
        EpicStaffStorage().write(file_path, content)
        return f"File {file_path} created successfully."
    except PermissionError as e:
        return str(e)
