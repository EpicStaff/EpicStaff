def main(file_path: str, line_number: int, content: str) -> str:
    from epicstaff_storage import EpicStaffStorage
    from epicstaff_storage.storage import split_lines

    if line_number < 1:
        return f"line_number must be >= 1, got {line_number}."

    storage = EpicStaffStorage()
    try:
        try:
            existing = storage.read(file_path)
            line_count = len(split_lines(existing))
        except FileNotFoundError:
            line_count = 0

        if line_number > line_count + 1:
            return (
                f"line_number {line_number} is out of range — {file_path} has {line_count} lines "
                f"(use a value between 1 and {line_count + 1})."
            )

        storage.insert_lines(file_path, line_number, content)
    except PermissionError as e:
        return str(e)
    except ValueError as e:
        return str(e)
    except RuntimeError as e:
        return str(e)

    return f"Content inserted before line {line_number} in {file_path} successfully."
