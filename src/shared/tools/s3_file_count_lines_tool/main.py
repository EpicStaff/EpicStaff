def main(file_path: str) -> int | str:
    from epicstaff_storage import EpicStaffStorage, StorageSizeLimitError

    try:
        return EpicStaffStorage().count_lines(file_path)
    except FileNotFoundError:
        return f"File {file_path} not found."
    except PermissionError as e:
        return str(e)
    except StorageSizeLimitError as e:
        return str(e)
