from enum import Enum


class StorageAction(str, Enum):
    LIST = "list_"
    LIST_TREE = "list_tree"
    UPLOAD = "upload"
    DOWNLOAD = "download"
    DELETE = "delete"
    MKDIR = "mkdir"
    MOVE = "move"
    COPY = "copy"
    INFO = "info"
    EXISTS = "exists"
    DOWNLOAD_ZIP = "download_zip"
    RENAME = "rename"
    SEARCH = "search"
