import json
import re
from unittest.mock import AsyncMock

import pytest

from dynamic_venv_executor_chain import DynamicVenvExecutorChain
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
    assert set(object_statement["Action"]) == {
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
    }
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
    assert sorted(list_statement["Condition"]["StringLike"]["s3:prefix"]) == [
        "f1",
        "f2",
    ]


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


# --- Cross-tenant path-traversal leak: _scoped_folders() joins the untrusted
# `allowed_paths` entries onto the trusted `org_prefix` *before* normalization,
# so a single-level ".." absorbs the org prefix itself:
#   "org_1/../org_2/"  --posixpath.normpath-->  "org_2/"
# `_normalize_path`'s traversal guard only rejects normalized paths that still
# start with "..", which this case no longer does by the time it's checked.
# The tests below assert the SECURE behavior (no sibling-org prefix must ever
# appear in the returned policy) and therefore FAIL against the current code.


def test_build_policy_rejects_sibling_org_via_prefix_absorbed_traversal():
    manager = make_manager()
    folders = DynamicVenvExecutorChain._scoped_folders("org_1", ["../org_2/"])

    policy = manager.build_policy("b", folders)

    object_statement = policy["Statement"][0]
    for resource in object_statement["Resource"]:
        assert resource.startswith("arn:aws:s3:::b/org_1/") or resource == "arn:aws:s3:::b/org_1", (
            f"Policy grants access to a sibling org's objects via path-traversal-absorbed "
            f"prefix: {resource!r} does not start with 'arn:aws:s3:::b/org_1/'"
        )

    list_statement = policy["Statement"][1]
    for prefix in list_statement["Condition"]["StringLike"]["s3:prefix"]:
        assert prefix.startswith("org_1/") or prefix == "org_1", (
            f"Policy grants s3:ListBucket over a sibling org's prefix via "
            f"path-traversal-absorbed prefix: {prefix!r} does not start with 'org_1/'"
        )


def test_build_policy_rejects_sibling_org_via_multi_segment_traversal():
    manager = make_manager()
    # "org_1" + "a/../../org_2/" -> normpath -> "org_2" (both ".." segments consumed,
    # the second one eating into the org prefix itself)
    folders = DynamicVenvExecutorChain._scoped_folders("org_1", ["a/../../org_2/"])

    policy = manager.build_policy("b", folders)

    object_statement = policy["Statement"][0]
    for resource in object_statement["Resource"]:
        assert resource.startswith("arn:aws:s3:::b/org_1/") or resource == "arn:aws:s3:::b/org_1", (
            f"Policy grants access to a sibling org's objects via multi-segment "
            f"path-traversal-absorbed prefix: {resource!r} does not start with 'arn:aws:s3:::b/org_1/'"
        )


def test_build_policy_list_bucket_condition_rejects_sibling_org_prefix():
    manager = make_manager()
    folders = DynamicVenvExecutorChain._scoped_folders("org_1", ["../org_2/"])

    policy = manager.build_policy("b", folders)

    list_statement = policy["Statement"][1]
    prefixes = list_statement["Condition"]["StringLike"]["s3:prefix"]
    assert all(prefix.startswith("org_1/") or prefix == "org_1" for prefix in prefixes), (
        f"s3:ListBucket StringLike condition leaks a sibling org's prefix: {prefixes!r}"
    )


def test_build_policy_rejects_sibling_org_file_via_traversal():
    manager = make_manager()
    # No trailing "/" on the traversal target, so _normalize_path does not append
    # "/*" -- this grants exactly the single sibling-org file "org_2/secret.txt".
    folders = DynamicVenvExecutorChain._scoped_folders("org_1", ["../org_2/secret.txt"])

    policy = manager.build_policy("b", folders)

    object_statement = policy["Statement"][0]
    for resource in object_statement["Resource"]:
        assert resource.startswith("arn:aws:s3:::b/org_1/") or resource == "arn:aws:s3:::b/org_1", (
            f"Policy grants access to a specific file in a sibling org via "
            f"path traversal: {resource!r} does not start with 'arn:aws:s3:::b/org_1/'"
        )


def test_scoped_folders_plain_subfolder_stays_in_org():
    manager = make_manager()
    folders = DynamicVenvExecutorChain._scoped_folders("org_1", ["reports/"])

    policy = manager.build_policy("b", folders)

    object_statement = policy["Statement"][0]
    assert object_statement["Resource"] == ["arn:aws:s3:::b/org_1/reports/*"]


def test_scoped_folders_none_allowed_paths_grants_whole_org():
    manager = make_manager()
    folders = DynamicVenvExecutorChain._scoped_folders("org_1", None)

    policy = manager.build_policy("b", folders)

    object_statement = policy["Statement"][0]
    assert object_statement["Resource"] == ["arn:aws:s3:::b/org_1/*"]


def test_scoped_folders_interior_traversal_resolving_inside_org_is_not_rejected():
    manager = make_manager()
    # "org_1" + "a/../b/" -> normpath -> "org_1/b" (the ".." only cancels the
    # interior "a" segment, never touching the org prefix) -- this must stay
    # allowed so a future fix that blanket-bans any ".." doesn't regress this.
    folders = DynamicVenvExecutorChain._scoped_folders("org_1", ["a/../b/"])

    policy = manager.build_policy("b", folders)

    object_statement = policy["Statement"][0]
    assert object_statement["Resource"] == ["arn:aws:s3:::b/org_1/b/*"]


def test_build_policy_still_catches_bucket_wide_escape():
    manager = make_manager()
    with pytest.raises(CredentialManagerError):
        manager.build_policy("b", {"org_1/../../"})
