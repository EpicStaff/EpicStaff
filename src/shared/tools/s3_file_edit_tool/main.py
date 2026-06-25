def main(file_path: str, line_number: int, expected_text: str, new_text: str) -> str:
    from epicstaff_storage import EpicStaffStorage, StorageLineEditMismatchError

    try:
        EpicStaffStorage().edit_line(file_path, line_number, expected_text, new_text)
        return f"Line {line_number} of {file_path} updated successfully."
    except FileNotFoundError:
        return f"File {file_path} not found."
    except PermissionError as e:
        return str(e)
    except StorageLineEditMismatchError as e:
        return str(e)
    except ValueError as e:
        return str(e)
