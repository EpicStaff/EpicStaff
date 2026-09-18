def main(file_path: str, content: str = "", fail_if_exists: bool = True) -> str:
    from epicstaff_storage import EpicStaffStorage

    storage = EpicStaffStorage()
    try:
        if fail_if_exists and storage.exists(file_path):
            return (
                f"File already exists: {file_path}. Use s3_file_write_tool to overwrite it, "
                "or pass fail_if_exists=false to overwrite here."
            )
        storage.write(file_path, content)
    except FileNotFoundError:
        return f"File not found: {file_path}."
    except PermissionError as e:
        return str(e)
    except ValueError as e:
        return str(e)
    except RuntimeError as e:
        return str(e)

    return f"File created: {file_path}."
