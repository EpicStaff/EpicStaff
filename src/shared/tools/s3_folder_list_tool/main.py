def main(folder_path: str) -> list | str:
    from epicstaff_storage import EpicStaffStorage

    try:
        return EpicStaffStorage().list(folder_path)
    except PermissionError as e:
        return str(e)
