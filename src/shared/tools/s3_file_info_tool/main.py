def main(file_path: str) -> dict | str:
    from epicstaff_storage import EpicStaffStorage

    try:
        return EpicStaffStorage().info(file_path)
    except FileNotFoundError:
        return f"File {file_path} not found."
    except PermissionError as e:
        return str(e)
