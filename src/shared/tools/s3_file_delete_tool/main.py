def main(file_path: str) -> str:
    from epicstaff_storage import EpicStaffStorage

    try:
        EpicStaffStorage().delete(file_path)
        return f"File {file_path} deleted successfully."
    except PermissionError as e:
        return str(e)
