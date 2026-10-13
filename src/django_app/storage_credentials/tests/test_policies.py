"""Two invariants confirmed by a live-MinIO check (step 0) to both be
necessary -- neither is redundant with the other:

1. No `Allow` statement in `build_temporary_policy()` grants any `admin:*`
   action.
2. `build_temporary_policy()` carries an explicit `Deny` on
   `admin:CreateServiceAccount`/`RemoveServiceAccount`/`UpdateServiceAccount`.

(1) alone is insufficient: MinIO allows a service account to self-mint a
sibling service account for its parent user regardless of whether that
action appears in its own Allow policy. Only (2) actually blocks it.
"""

import pytest

from storage_credentials.exceptions import CredentialScopeValidationError
from storage_credentials.policies import build_org_user_policy, build_temporary_policy

_SELF_MINT_ACTIONS = {
    "admin:CreateServiceAccount",
    "admin:RemoveServiceAccount",
    "admin:UpdateServiceAccount",
}


def _allow_actions(policy: dict) -> set[str]:
    actions: set[str] = set()
    for statement in policy["Statement"]:
        if statement["Effect"] == "Allow":
            actions.update(statement["Action"])
    return actions


def _deny_statements(policy: dict) -> list[dict]:
    return [s for s in policy["Statement"] if s["Effect"] == "Deny"]


def test_temporary_policy_allow_has_no_admin_actions():
    policy = build_temporary_policy("bucket", {"org_1/foo"})
    allow_actions = _allow_actions(policy)
    assert not any(action.startswith("admin:") for action in allow_actions)


def test_temporary_policy_denies_self_service_account_minting():
    policy = build_temporary_policy("bucket", {"org_1/foo"})
    deny_statements = _deny_statements(policy)
    assert deny_statements, "build_temporary_policy() must include a Deny statement"

    denied_actions: set[str] = set()
    for statement in deny_statements:
        denied_actions.update(statement["Action"])
    assert _SELF_MINT_ACTIONS <= denied_actions


def test_temporary_policy_scopes_resources_to_allowed_folders():
    policy = build_temporary_policy("bucket", {"org_1/foo"})
    allow_statement = next(
        s
        for s in policy["Statement"]
        if s["Effect"] == "Allow" and "s3:GetObject" in s["Action"]
    )
    assert allow_statement["Resource"] == ["arn:aws:s3:::bucket/org_1/foo"]


def test_temporary_policy_rejects_empty_folders():
    with pytest.raises(CredentialScopeValidationError):
        build_temporary_policy("bucket", set())


def test_temporary_policy_rejects_path_traversal():
    with pytest.raises(CredentialScopeValidationError):
        build_temporary_policy("bucket", {"../etc"})


def test_org_user_policy_scopes_to_org_prefix_and_grants_self_service_admin():
    policy = build_org_user_policy("bucket", "org_5")
    allow_actions = _allow_actions(policy)
    assert allow_actions >= {
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:ListBucket",
        "s3:GetBucketLocation",
        "admin:CreateServiceAccount",
        "admin:RemoveServiceAccount",
        "admin:ListServiceAccounts",
    }
    s3_statement = next(
        s
        for s in policy["Statement"]
        if s["Effect"] == "Allow" and "s3:GetObject" in s["Action"]
    )
    assert s3_statement["Resource"] == ["arn:aws:s3:::bucket/org_5/*"]
