"""A storage-side AccessDenied (the account's policy) surfaces as a readable permission error."""

import pytest

from epicstaff_storage import StoragePermissionError
from fakes import make_client_error


@pytest.mark.parametrize(
    ("method", "error_code", "storage_operation", "call"),
    [
        ("put_object", "AccessDenied", "PutObject", lambda s: s.write("docs/a.txt", "x")),
        ("get_object", "AccessDenied", "GetObject", lambda s: s.read("docs/a.txt")),
        ("delete_object", "AccessDenied", "DeleteObject", lambda s: s.delete("docs/a.txt")),
        ("head_object", "403", "HeadObject", lambda s: s.info("docs/a.txt")),
        ("head_object", "403", "HeadObject", lambda s: s.exists("docs/a.txt")),
    ],
    ids=["write", "read", "delete", "info-403", "exists-403"],
)
def test_access_denied_becomes_a_permission_error_naming_path_and_storage_operation(
    monkeypatch, storage, fake_client, method, error_code, storage_operation, call
):
    def deny(**kwargs):
        raise make_client_error(error_code, storage_operation)

    monkeypatch.setattr(fake_client, method, deny)

    with pytest.raises(StoragePermissionError) as exc_info:
        call(storage)

    message = str(exc_info.value)
    assert "docs/a.txt" in message
    assert storage_operation in message
    assert "Files permissions" in message


def test_other_storage_errors_stay_runtime_errors(monkeypatch, storage, fake_client):
    def fail(**kwargs):
        raise make_client_error("InternalError", "PutObject")

    monkeypatch.setattr(fake_client, "put_object", fail)

    with pytest.raises(RuntimeError) as exc_info:
        storage.write("docs/a.txt", "x")

    assert not isinstance(exc_info.value, StoragePermissionError)
