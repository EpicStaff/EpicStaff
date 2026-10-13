"""Behavior of the scoped storage policy builder.

This is the code that keeps one organization's execution from reaching another's
objects, so every escape attempt gets a test. ``provision`` and ``revoke`` are not
covered: the admin client is built inside ``__init__`` with no seam for a stand-in.
"""

import pytest

from worker.infrastructure.storage.credentials import (
    CredentialManagerError,
    MinioStorageCredentials,
)

BUCKET = "sandbox"
BUCKET_ARN = f"arn:aws:s3:::{BUCKET}"


@pytest.fixture
def adapter() -> MinioStorageCredentials:
    return MinioStorageCredentials(
        host="http://localhost:9000", access_key="minio", secret_key="minio123", bucket=BUCKET
    )


def resources(policy: dict) -> list[str]:
    return policy["Statement"][0]["Resource"]


def test_no_allowed_paths_grants_the_whole_organization(adapter):
    policy = adapter._build_policy(org_prefix="org1", allowed_paths=None)

    assert resources(policy) == [f"{BUCKET_ARN}/org1/*"]


def test_an_empty_allowed_paths_list_grants_the_whole_organization(adapter):
    policy = adapter._build_policy(org_prefix="org1", allowed_paths=[])

    assert resources(policy) == [f"{BUCKET_ARN}/org1/*"]


def test_a_trailing_slash_grants_the_folder_contents(adapter):
    policy = adapter._build_policy(org_prefix="org1", allowed_paths=["docs/"])

    assert resources(policy) == [f"{BUCKET_ARN}/org1/docs/*"]


def test_a_path_without_a_trailing_slash_grants_that_object(adapter):
    policy = adapter._build_policy(org_prefix="org1", allowed_paths=["reports/q1.csv"])

    assert resources(policy) == [f"{BUCKET_ARN}/org1/reports/q1.csv"]


def test_several_paths_are_sorted(adapter):
    policy = adapter._build_policy(org_prefix="org1", allowed_paths=["zeta/", "alpha/"])

    assert resources(policy) == [f"{BUCKET_ARN}/org1/alpha/*", f"{BUCKET_ARN}/org1/zeta/*"]


def test_a_leading_slash_is_not_an_escape(adapter):
    policy = adapter._build_policy(org_prefix="org1", allowed_paths=["/docs/"])

    assert resources(policy) == [f"{BUCKET_ARN}/org1/docs/*"]


@pytest.mark.parametrize(
    "path",
    ["../org2/", "docs/../../org2/", "..", "../", "docs/../..", "\\..\\org2\\"],
)
def test_a_path_that_escapes_the_organization_is_refused(adapter, path):
    with pytest.raises(CredentialManagerError):
        adapter._build_policy(org_prefix="org1", allowed_paths=[path])


@pytest.mark.parametrize("org_prefix", ["", "/", "..", ".", "org1/sub", "../org2"])
def test_an_invalid_organization_prefix_is_refused(adapter, org_prefix):
    with pytest.raises(CredentialManagerError):
        adapter._build_policy(org_prefix=org_prefix, allowed_paths=["docs/"])


def test_the_policy_has_the_three_statements_the_client_needs(adapter):
    policy = adapter._build_policy(org_prefix="org1", allowed_paths=["docs/"])

    actions = [statement["Action"] for statement in policy["Statement"]]
    assert actions == [
        ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
        ["s3:ListBucket"],
        ["s3:GetBucketLocation"],
    ]
    assert policy["Version"] == "2012-10-17"


def test_listing_is_constrained_to_the_allowed_prefixes(adapter):
    policy = adapter._build_policy(org_prefix="org1", allowed_paths=["docs/", "reports/q1.csv"])

    list_statement = policy["Statement"][1]
    assert list_statement["Resource"] == [BUCKET_ARN]
    assert list_statement["Condition"]["StringLike"]["s3:prefix"] == [
        "org1/docs/*",
        "org1/reports/q1.csv",
    ]
