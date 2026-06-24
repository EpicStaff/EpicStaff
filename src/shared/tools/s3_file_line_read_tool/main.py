def main(file_path: str, line_number: int, num_lines: int | None = None):
    from epicstaff_storage import EpicStaffStorage, StorageSizeLimitError

    try:
        return EpicStaffStorage().read_lines(file_path, line_number, num_lines)
    except FileNotFoundError:
        return f"File {file_path} not found."
    except PermissionError as e:
        return str(e)
    except StorageSizeLimitError as e:
        return str(e)
    except ValueError as e:
        return str(e)
