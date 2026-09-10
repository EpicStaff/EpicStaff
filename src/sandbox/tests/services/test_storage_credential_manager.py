import json
import re
from unittest.mock import AsyncMock

import pytest

from services.storage_credential_manager import (
    CredentialManagerError,
    StorageCredentialManager,
)


def make_manager() -> StorageCredentialManager:
    return StorageCredentialManager("http://localhost:9000", "root-ak", "root-sk")


def test_build_policy_two_folders_object_statement():
    manager = make_manager()
    policy = manager.build_policy("b", {"f1", "f2"})

    object_statement = policy["Statement"][0]
    assert set(object_statement["Action"]) == {"s3:GetObject", "s3:PutObject", "s3:DeleteObject"}
    assert object_statement["Resource"] == [
        "arn:aws:s3:::b/f1",
        "arn:aws:s3:::b/f2",
    ]


def test_build_policy_two_folders_list_bucket_statement():
    manager = make_manager()
    policy = manager.build_policy("b", {"f1", "f2"})

    list_statement = policy["Statement"][1]
    assert list_statement["Action"] == ["s3:ListBucket"]
    assert list_statement["Resource"] == ["arn:aws:s3:::b"]
    assert sorted(list_statement["Condition"]["StringLike"]["s3:prefix"]) == ["f1", "f2"]


def test_build_policy_get_bucket_location_statement():
    manager = make_manager()
    policy = manager.build_policy("b", {"f1"})

    location_statement = policy["Statement"][2]
    assert "s3:GetBucketLocation" in location_statement["Action"]
    assert "arn:aws:s3:::b" in location_statement["Resource"]


def test_build_policy_exactly_three_statements():
    manager = make_manager()
    policy = manager.build_policy("b", {"f1", "f2"})

    assert len(policy["Statement"]) == 3


def test_build_policy_version():
    manager = make_manager()
    policy = manager.build_policy("b", {"f1"})

    assert policy["Version"] == "2012-10-17"


def test_build_policy_deterministic_across_set_orderings():
    manager = make_manager()
    policy_a = manager.build_policy("b", {"f1", "f2"})
    policy_b = manager.build_policy("b", {"f2", "f1"})

    assert policy_a == policy_b


def test_build_policy_empty_folders_raises():
    manager = make_manager()
    with pytest.raises(CredentialManagerError):
        manager.build_policy("b", set())


def test_build_policy_path_traversal_raises():
    manager = make_manager()
    with pytest.raises(CredentialManagerError):
        manager.build_policy("b", {"../etc"})


def test_build_policy_root_slash_returns_wildcard():
    """_normalize_path("/") normalizes to "/" (no traversal, non-empty) and
    appends "/*" because the stripped path ends with "/", yielding "//*".
    The resource is bucket + "/" + "//*" = "arn:aws:s3:::b///*". The current
    contract does not raise for a bare slash; callers are responsible for
    validating input at a higher level if bucket-wide access must be prevented."""
    manager = make_manager()
    policy = manager.build_policy("b", {"/"})

    object_statement = policy["Statement"][0]
    assert object_statement["Resource"] == ["arn:aws:s3:::b///*"]


def test_build_policy_empty_string_folder_raises():
    manager = make_manager()
    with pytest.raises(CredentialManagerError):
        manager.build_policy("b", {""})


def test_build_policy_normalize_whitespace_and_trailing_slash():
    """_normalize_path strips whitespace and applies posixpath.normpath.
    A trailing slash causes "/*" to be appended; a leading slash is preserved
    after normpath. These two inputs therefore produce different normalized paths
    and are not equal — this test pins the current contract for each."""
    manager = make_manager()

    # " /foo/bar/ " → strip → "/foo/bar/" → normpath → "/foo/bar" → ends with "/" → "/foo/bar/*"
    policy_spaced = manager.build_policy("b", {" /foo/bar/ "})
    object_statement_spaced = policy_spaced["Statement"][0]
    assert object_statement_spaced["Resource"] == ["arn:aws:s3:::b//foo/bar/*"]

    # "foo/bar" → strip → "foo/bar" → normpath → "foo/bar" → no trailing "/" → "foo/bar"
    policy_plain = manager.build_policy("b", {"foo/bar"})
    object_statement_plain = policy_plain["Statement"][0]
    assert object_statement_plain["Resource"] == ["arn:aws:s3:::b/foo/bar"]


def test_normalize_path_strips_whitespace_and_appends_wildcard_when_trailing_slash():
    """strip() removes surrounding whitespace; posixpath.normpath removes the trailing
    slash but preserves the leading one; because the stripped input ended with "/" the
    result gets "/*" appended."""
    result = StorageCredentialManager._normalize_path(" /foo/bar/ ")
    assert result == "/foo/bar/*"


def test_normalize_path_plain_path_unchanged():
    result = StorageCredentialManager._normalize_path("foo/bar")
    assert result == "foo/bar"


def test_split_host_https():
    secure, endpoint = StorageCredentialManager._split_host("https://minio:9000")
    assert secure is True
    assert endpoint == "minio:9000"


def test_split_host_http():
    secure, endpoint = StorageCredentialManager._split_host("http://localhost:9000")
    assert secure is False
    assert endpoint == "localhost:9000"


@pytest.mark.asyncio
async def test_create_returns_credentials():
    manager = make_manager()
    policy = {"Version": "2012-10-17", "Statement": []}

    recorded = {}

    async def fake_add_service_account(policy_file, expiration):
        with open(policy_file, "r") as handle:
            recorded["policy"] = json.load(handle)
        recorded["expiration"] = expiration
        recorded["policy_file"] = policy_file
        return json.dumps({"credentials": {"accessKey": "AK", "secretKey": "SK"}})

    manager._client.add_service_account = fake_add_service_account

    access_key, secret_key = await manager.create(policy)

    assert access_key == "AK"
    assert secret_key == "SK"


@pytest.mark.asyncio
async def test_create_writes_policy_to_temp_file():
    manager = make_manager()
    policy = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow"}]}

    recorded = {}

    async def fake_add_service_account(policy_file, expiration):
        with open(policy_file, "r") as handle:
            recorded["policy"] = json.load(handle)
        recorded["expiration"] = expiration
        recorded["policy_file"] = policy_file
        return json.dumps({"credentials": {"accessKey": "AK", "secretKey": "SK"}})

    manager._client.add_service_account = fake_add_service_account

    await manager.create(policy)

    assert recorded["policy"] == policy


@pytest.mark.asyncio
async def test_create_temp_file_has_json_suffix():
    manager = make_manager()
    policy = {"Version": "2012-10-17", "Statement": []}

    recorded = {}

    async def capturing_add_service_account(policy_file, expiration):
        with open(policy_file, "r") as handle:
            recorded["policy"] = json.load(handle)
        recorded["policy_file"] = policy_file
        recorded["expiration"] = expiration
        return json.dumps({"credentials": {"accessKey": "AK", "secretKey": "SK"}})

    manager._client.add_service_account = capturing_add_service_account

    await manager.create(policy)

    assert recorded["policy_file"].endswith(".json")


@pytest.mark.asyncio
async def test_create_expiration_rfc3339_utc_format():
    manager = make_manager()
    policy = {"Version": "2012-10-17", "Statement": []}

    recorded = {}

    async def capturing_add_service_account(policy_file, expiration):
        with open(policy_file, "r") as handle:
            recorded["policy"] = json.load(handle)
        recorded["policy_file"] = policy_file
        recorded["expiration"] = expiration
        return json.dumps({"credentials": {"accessKey": "AK", "secretKey": "SK"}})

    manager._client.add_service_account = capturing_add_service_account

    await manager.create(policy)

    rfc3339_pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"
    assert re.match(rfc3339_pattern, recorded["expiration"]) is not None


@pytest.mark.asyncio
async def test_revoke_calls_delete_service_account():
    manager = make_manager()
    manager._client.delete_service_account = AsyncMock()

    await manager.revoke("AK")

    manager._client.delete_service_account.assert_awaited_once_with("AK")
