import json
import os
import re
from unittest.mock import AsyncMock

import pytest

from services.storage_credential_manager import (
    CredentialManagerError,
    StorageCredentialManager,
)

_reopen_while_open_posix_only = pytest.mark.skipif(
    os.name != "posix",
    reason="POSIX-only: NamedTemporaryFile cannot be reopened while open on Windows",
)


def make_manager() -> StorageCredentialManager:
    return StorageCredentialManager("http://localhost:9000", "root-ak", "root-sk")


def test_build_policy_two_folders_object_statement():
    manager = make_manager()
    policy = manager.build_policy("b", "org_1", ["f1", "f2"])

    object_statement = policy["Statement"][0]
    assert set(object_statement["Action"]) == {
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
    }
    assert object_statement["Resource"] == [
        "arn:aws:s3:::b/org_1/f1",
        "arn:aws:s3:::b/org_1/f2",
    ]


def test_build_policy_two_folders_list_bucket_statement():
    manager = make_manager()
    policy = manager.build_policy("b", "org_1", ["f1", "f2"])

    list_statement = policy["Statement"][1]
    assert list_statement["Action"] == ["s3:ListBucket"]
    assert list_statement["Resource"] == ["arn:aws:s3:::b"]
    assert sorted(list_statement["Condition"]["StringLike"]["s3:prefix"]) == [
        "org_1/f1",
        "org_1/f2",
    ]


def test_build_policy_get_bucket_location_statement():
    manager = make_manager()
    policy = manager.build_policy("b", "org_1", ["f1"])

    location_statement = policy["Statement"][2]
    assert "s3:GetBucketLocation" in location_statement["Action"]
    assert "arn:aws:s3:::b" in location_statement["Resource"]


def test_build_policy_exactly_three_statements():
    manager = make_manager()
    policy = manager.build_policy("b", "org_1", ["f1", "f2"])

    assert len(policy["Statement"]) == 3


def test_build_policy_version():
    manager = make_manager()
    policy = manager.build_policy("b", "org_1", ["f1"])

    assert policy["Version"] == "2012-10-17"


def test_build_policy_deterministic_across_input_orderings():
    manager = make_manager()
    policy_a = manager.build_policy("b", "org_1", ["f1", "f2"])
    policy_b = manager.build_policy("b", "org_1", ["f2", "f1"])

    assert policy_a == policy_b


def test_build_policy_empty_allowed_paths_list_grants_whole_org():
    # Deliberate, preserved from the pre-fix semantics: an empty allowed_paths
    # list means "no explicit paths" and collapses to a whole-org grant, same
    # as allowed_paths=None. This is NOT an accident of the containment fix --
    # build_policy never rejects an empty allowed_paths list.
    manager = make_manager()
    policy = manager.build_policy("b", "org_1", [])

    object_statement = policy["Statement"][0]
    assert object_statement["Resource"] == ["arn:aws:s3:::b/org_1/*"]


def test_build_policy_path_traversal_raises():
    manager = make_manager()
    with pytest.raises(CredentialManagerError):
        manager.build_policy("b", "org_1", ["../etc"])


def test_build_policy_root_slash_path_grants_whole_org_wildcard():
    """An explicit "/" path element joins to "org_1/", which normalizes to
    "org_1" and (because the stripped input ends with "/") gets "/*" appended,
    yielding the same whole-org wildcard grant as allowed_paths=None."""
    manager = make_manager()
    policy = manager.build_policy("b", "org_1", ["/"])

    object_statement = policy["Statement"][0]
    assert object_statement["Resource"] == ["arn:aws:s3:::b/org_1/*"]


def test_build_policy_empty_string_path_element_grants_whole_org():
    # Deliberate, preserved from the pre-fix semantics: an empty path element
    # strips/lstrips to "", joins as "org_1/", normalizes to "org_1", and --
    # because the pre-normalization string ends with "/" -- gets "/*"
    # appended, landing on the same whole-org wildcard as "/" or None. This is
    # NOT an accident of the containment fix; there is no per-element
    # emptiness check in build_policy.
    manager = make_manager()
    policy = manager.build_policy("b", "org_1", [""])

    object_statement = policy["Statement"][0]
    assert object_statement["Resource"] == ["arn:aws:s3:::b/org_1/*"]


def test_build_policy_whitespace_only_path_element_grants_whole_org():
    # Deliberate, preserved from the pre-fix semantics: a whitespace-only path
    # element strips to "" and follows the exact same collapse as an empty
    # string element above, landing on the whole-org wildcard. This is NOT an
    # accident of the containment fix; there is no per-element emptiness
    # check in build_policy.
    manager = make_manager()
    policy = manager.build_policy("b", "org_1", ["   "])

    object_statement = policy["Statement"][0]
    assert object_statement["Resource"] == ["arn:aws:s3:::b/org_1/*"]


def test_build_policy_normalize_whitespace_and_trailing_slash():
    """Leading whitespace/slashes are stripped before the join, so a spaced,
    slash-prefixed path still lands inside the org. A trailing slash appends
    the "/*" wildcard; no trailing slash leaves a bare object resource."""
    manager = make_manager()

    # " /foo/bar/ " -> strip -> "/foo/bar/" -> lstrip('/') -> "foo/bar/"
    # -> join "org_1/foo/bar/" -> normpath "org_1/foo/bar" -> trailing "/" -> "org_1/foo/bar/*"
    policy_spaced = manager.build_policy("b", "org_1", [" /foo/bar/ "])
    object_statement_spaced = policy_spaced["Statement"][0]
    assert object_statement_spaced["Resource"] == ["arn:aws:s3:::b/org_1/foo/bar/*"]

    # "foo/bar" -> join "org_1/foo/bar" -> normpath "org_1/foo/bar" -> no trailing "/"
    policy_plain = manager.build_policy("b", "org_1", ["foo/bar"])
    object_statement_plain = policy_plain["Statement"][0]
    assert object_statement_plain["Resource"] == ["arn:aws:s3:::b/org_1/foo/bar"]


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


@_reopen_while_open_posix_only
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


@_reopen_while_open_posix_only
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


@_reopen_while_open_posix_only
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


@_reopen_while_open_posix_only
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


# --- Cross-tenant path-traversal containment: build_policy now joins the
# untrusted `allowed_paths` entries onto the trusted, already-validated
# `org_prefix` itself, normalizes, and asserts containment (_assert_within_org)
# before any resource ever makes it into the returned policy.


def test_build_policy_rejects_sibling_org_via_prefix_absorbed_traversal():
    manager = make_manager()
    # "org_1" + "../org_2/" -> normpath -> "org_2/*", which fails containment
    # against "org_1" and is rejected by build_policy itself.
    with pytest.raises(CredentialManagerError):
        manager.build_policy("b", "org_1", ["../org_2/"])


def test_build_policy_rejects_sibling_org_via_multi_segment_traversal():
    manager = make_manager()
    # "org_1" + "a/../../org_2/" -> normpath -> "org_2/*" (both ".." segments
    # consumed, the second one eating into the org prefix itself) -> rejected.
    with pytest.raises(CredentialManagerError):
        manager.build_policy("b", "org_1", ["a/../../org_2/"])


def test_build_policy_list_bucket_condition_rejects_sibling_org_prefix():
    manager = make_manager()
    # Same traversal as above; this test specifically guards the s3:prefix
    # condition path, which build_policy computes from the same rejected
    # prefix list, so it raises before any Condition is ever assembled.
    with pytest.raises(CredentialManagerError):
        manager.build_policy("b", "org_1", ["../org_2/"])


def test_build_policy_rejects_sibling_org_file_via_traversal():
    manager = make_manager()
    # No trailing "/" on the traversal target, so no "/*" wildcard is appended
    # -- this would grant exactly the sibling-org file "org_2/secret.txt" if
    # containment weren't enforced. It is, so this raises instead.
    with pytest.raises(CredentialManagerError):
        manager.build_policy("b", "org_1", ["../org_2/secret.txt"])


def test_build_policy_plain_subfolder_stays_in_org():
    manager = make_manager()
    policy = manager.build_policy("b", "org_1", ["reports/"])

    object_statement = policy["Statement"][0]
    assert object_statement["Resource"] == ["arn:aws:s3:::b/org_1/reports/*"]


def test_build_policy_none_allowed_paths_grants_whole_org():
    manager = make_manager()
    policy = manager.build_policy("b", "org_1", None)

    object_statement = policy["Statement"][0]
    assert object_statement["Resource"] == ["arn:aws:s3:::b/org_1/*"]


def test_build_policy_none_allowed_paths_grants_org_wildcard_in_both_statements():
    manager = make_manager()
    policy = manager.build_policy("b", "org_1", None)

    object_statement = policy["Statement"][0]
    list_statement = policy["Statement"][1]
    assert object_statement["Resource"] == ["arn:aws:s3:::b/org_1/*"]
    assert list_statement["Condition"]["StringLike"]["s3:prefix"] == ["org_1/*"]


def test_build_policy_interior_traversal_resolving_inside_org_is_allowed():
    manager = make_manager()
    # "org_1" + "a/../b/" -> normpath -> "org_1/b" (the ".." only cancels the
    # interior "a" segment, never touching the org prefix) -- this must stay
    # allowed so a future fix that blanket-bans any ".." doesn't regress this.
    policy = manager.build_policy("b", "org_1", ["a/../b/"])

    object_statement = policy["Statement"][0]
    assert object_statement["Resource"] == ["arn:aws:s3:::b/org_1/b/*"]


def test_build_policy_still_catches_bucket_wide_escape():
    manager = make_manager()
    # "org_1" + "../../" -> normpath -> ".." -- caught directly by
    # _normalize_path's reject set before containment is even checked.
    with pytest.raises(CredentialManagerError):
        manager.build_policy("b", "org_1", ["../../"])


# --- New guards introduced by the org_prefix/allowed_paths split.


def test_build_policy_rejects_empty_org_prefix():
    manager = make_manager()
    with pytest.raises(CredentialManagerError):
        manager.build_policy("b", "", ["f1"])


def test_build_policy_rejects_dot_org_prefix():
    manager = make_manager()
    with pytest.raises(CredentialManagerError):
        manager.build_policy("b", ".", ["f1"])


def test_build_policy_rejects_dotdot_org_prefix():
    manager = make_manager()
    with pytest.raises(CredentialManagerError):
        manager.build_policy("b", "..", ["f1"])


def test_build_policy_rejects_multi_segment_org_prefix():
    manager = make_manager()
    with pytest.raises(CredentialManagerError):
        manager.build_policy("b", "org_1/../org_2", ["f1"])


def test_build_policy_rejects_sibling_prefix_confusion_org_1_vs_org_10():
    manager = make_manager()
    # "org_1" + "../org_10/file.txt" -> normpath -> "org_10/file.txt". Naive
    # containment via bare.startswith(org_prefix) would wrongly accept this
    # since "org_10" starts with "org_1"; the trailing "/" in the actual check
    # (startswith(f"{org_prefix}/")) is what correctly rejects it.
    with pytest.raises(CredentialManagerError):
        manager.build_policy("b", "org_1", ["../org_10/file.txt"])
