"""Org storage: streamed raw-body upload through nginx, list, info and a byte-exact download."""

from fixtures.knowledge import STORAGE_FILE_NAME, STORAGE_FOLDER
from helpers.api import ApiClient

STORED_PATH = f"{STORAGE_FOLDER}/{STORAGE_FILE_NAME}"


def test_streamed_upload_stores_the_file(stored_file: dict, knowledge_file_content: bytes) -> None:
    assert stored_file["status"] == "DONE"
    assert stored_file["path"] == STORED_PATH
    assert stored_file["size"] == len(knowledge_file_content)


def test_folder_lists_the_file(user_client: ApiClient, stored_file: dict) -> None:
    listing = user_client.get("/api/storage/list/", params={"path": STORAGE_FOLDER}).json()
    [item] = [item for item in listing["items"] if item["name"] == STORAGE_FILE_NAME]
    assert item["type"] == "file"
    assert isinstance(item["id"], int)


def test_file_info(user_client: ApiClient, stored_file: dict, knowledge_file_content: bytes) -> None:
    info = user_client.get("/api/storage/info/", params={"path": STORED_PATH}).json()
    assert info["path"] == STORED_PATH
    assert info["name"] == STORAGE_FILE_NAME
    assert info["size"] == len(knowledge_file_content)


def test_download_returns_the_uploaded_bytes(
    user_client: ApiClient, stored_file: dict, knowledge_file_content: bytes
) -> None:
    download = user_client.get("/api/storage/download/", params={"path": STORED_PATH})
    assert download.content == knowledge_file_content
