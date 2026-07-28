def main(file_path: str, line_number: int, content: str) -> str:
    from epicstaff_storage import EpicStaffStorage

    try:
        EpicStaffStorage().insert_lines(file_path, line_number, content)
        return f"Content inserted at line {line_number} in {file_path} successfully."
    except ValueError as e:
        return str(e)
    except PermissionError as e:
        return str(e)
    except FileNotFoundError as e:
        return str(e)
