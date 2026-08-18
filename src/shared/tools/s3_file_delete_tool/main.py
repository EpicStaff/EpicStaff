def main(file_path: str) -> str:
    from epicstaff_storage import EpicStaffStorage

    storage = EpicStaffStorage()
    try:
        try:
            storage.info(file_path)
        except FileNotFoundError:
            if storage.exists(file_path):
                return (
                    f"'{file_path}' is a folder, not a file — s3_file_delete_tool only deletes "
                    "files. Use s3_folder_delete_tool with recursive intent to delete a folder."
                )
            return f"File not found: {file_path}."

        storage.delete(file_path)
    except PermissionError as e:
        return str(e)
    except ValueError as e:
        return str(e)
    except RuntimeError as e:
        return str(e)

    return f"Deleted {file_path}."
