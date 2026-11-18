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

import json

import pytest
from src.shared.models.storage_scope import StorageAction

from storage_credentials.exceptions import (
    CredentialScopeValidationError,
    TemporaryPolicyTooLargeError,
)
from storage_credentials.policies import build_org_user_policy, build_temporary_policy

ALL_ACTIONS = frozenset(StorageAction)

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


def _policy(*, shared=(), actions=ALL_ACTIONS, own=()) -> dict:
    return build_temporary_policy(
        "bucket",
        shared_folders=set(shared),
        shared_actions=frozenset(actions),
        own_folders=set(own),
    )


def _object_statements(policy: dict) -> list[dict]:
    return [
        statement
        for statement in policy["Statement"]
        if statement["Effect"] == "Allow" and statement["Action"][0].startswith("s3:") and "Resource" in statement
        and statement["Resource"][0] != "arn:aws:s3:::bucket"
    ]


def _listing_prefixes(policy: dict) -> list[str]:
    statement = next(
        s
        for s in policy["Statement"]
        if s["Effect"] == "Allow" and s["Action"] == ["s3:ListBucket"]
    )
    return statement["Condition"]["StringLike"]["s3:prefix"]


def _deny_statements(policy: dict) -> list[dict]:
    return [s for s in policy["Statement"] if s["Effect"] == "Deny"]


def test_temporary_policy_allow_has_no_admin_actions():
    policy = _policy(shared={"org_1/foo"})
    allow_actions = _allow_actions(policy)
    assert not any(action.startswith("admin:") for action in allow_actions)


def test_temporary_policy_denies_self_service_account_minting():
    policy = _policy(shared={"org_1/foo"})
    deny_statements = _deny_statements(policy)
    assert deny_statements, "build_temporary_policy() must include a Deny statement"

    denied_actions: set[str] = set()
    for statement in deny_statements:
        denied_actions.update(statement["Action"])
    assert _SELF_MINT_ACTIONS <= denied_actions


def test_temporary_policy_scopes_resources_to_allowed_folders():
    policy = _policy(shared={"org_1/foo"})
    allow_statement = next(
        s
        for s in policy["Statement"]
        if s["Effect"] == "Allow" and "s3:GetObject" in s["Action"]
    )
    assert allow_statement["Resource"] == ["arn:aws:s3:::bucket/org_1/foo"]


@pytest.mark.parametrize(
    ("shared", "own"),
    [((), ()), (("../etc",), ()), ((), ("../etc",))],
    ids=["no-folders", "traversal-in-shared", "traversal-in-own"],
)
def test_temporary_policy_refuses_a_scope_it_cannot_confine(shared, own):
    with pytest.raises(CredentialScopeValidationError):
        _policy(shared=shared, own=own)


@pytest.mark.parametrize(
    ("actions", "object_actions", "readable"),
    [
        ({StorageAction.READ}, ["s3:GetObject"], True),
        ({StorageAction.READ, StorageAction.WRITE}, ["s3:GetObject", "s3:PutObject"], True),
        ({StorageAction.READ, StorageAction.DELETE}, ["s3:GetObject", "s3:DeleteObject"], True),
        (set(StorageAction), ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"], True),
        ({StorageAction.WRITE}, ["s3:PutObject"], False),
    ],
    ids=["read", "read-write", "read-delete", "all", "write-only"],
)
def test_shared_folders_get_exactly_the_actions_the_identity_holds(actions, object_actions, readable):
    policy = _policy(shared={"org_1/reports/"}, actions=actions, own={"org_1/sessions/5/"})

    shared_statement = next(
        s for s in _object_statements(policy) if "arn:aws:s3:::bucket/org_1/reports/*" in s["Resource"]
    )
    assert shared_statement["Action"] == object_actions
    # Listing follows read access: the own folder is always listable, the shared one only with READ.
    expected_listing = ["org_1/reports/*", "org_1/sessions/5/*"] if readable else ["org_1/sessions/5/*"]
    assert _listing_prefixes(policy) == expected_listing


def test_own_folders_always_get_every_action():
    policy = _policy(shared={"org_1/reports/"}, actions={StorageAction.READ}, own={"org_1/sessions/5/"})

    own_statement = next(
        s for s in _object_statements(policy) if s["Resource"] == ["arn:aws:s3:::bucket/org_1/sessions/5/*"]
    )
    assert own_statement["Action"] == ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]


def test_own_and_shared_folders_with_the_same_actions_share_one_statement():
    policy = _policy(shared={"org_1/reports/"}, own={"org_1/sessions/5/"})

    (statement,) = _object_statements(policy)
    assert statement["Action"] == ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    assert statement["Resource"] == [
        "arn:aws:s3:::bucket/org_1/reports/*",
        "arn:aws:s3:::bucket/org_1/sessions/5/*",
    ]


def test_shared_folders_are_left_out_when_no_action_is_allowed_on_them():
    policy = _policy(shared={"org_1/reports/"}, actions=(), own={"org_1/sessions/5/"})

    (statement,) = _object_statements(policy)
    assert statement["Resource"] == ["arn:aws:s3:::bucket/org_1/sessions/5/*"]
    assert "reports" not in json.dumps(policy)


def test_nothing_is_left_to_grant_without_own_folders_or_allowed_shared_actions():
    with pytest.raises(CredentialScopeValidationError):
        _policy(shared={"org_1/reports/"}, actions=())


def test_the_denies_stay_whatever_the_actions_allowed():
    policy = _policy(shared={"org_1/reports/"}, actions={StorageAction.READ}, own={"org_1/sessions/5/"})

    denied_actions = {action for s in _deny_statements(policy) for action in s["Action"]}
    assert _SELF_MINT_ACTIONS <= denied_actions
    assert len(_deny_statements(policy)) == 3


def test_a_policy_over_the_backend_size_limit_is_refused_before_the_backend_is_called():
    many_files = {f"org_1/attachments/some-quite-long-file-name-{index}.pdf" for index in range(80)}

    with pytest.raises(TemporaryPolicyTooLargeError) as error:
        _policy(shared=many_files, own={"org_1/sessions/5/"})

    assert error.value.status_code == 400
    assert "attach a folder" in str(error.value).lower()


def test_the_policy_size_limit_is_inclusive(settings):
    files = {f"org_1/attachments/file-{index}.pdf" for index in range(10)}
    size = len(json.dumps(_policy(shared=files), separators=(",", ":")).encode())

    settings.STORAGE_TEMPORARY_POLICY_MAX_BYTES = size
    _policy(shared=files)

    settings.STORAGE_TEMPORARY_POLICY_MAX_BYTES = size - 1
    with pytest.raises(TemporaryPolicyTooLargeError):
        _policy(shared=files)


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


def test_temporary_policy_denies_the_org_recycle_bin():
    policy = _policy(shared={"org_1/foo", "org_1"})
    deny_objects = next(s for s in _deny_statements(policy) if "s3:GetObject" in s["Action"])
    deny_listing = next(s for s in _deny_statements(policy) if s["Action"] == ["s3:ListBucket"])

    assert deny_objects["Action"] == ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    assert deny_objects["Resource"] == [
        "arn:aws:s3:::bucket/org_1/.recycle-bin",
        "arn:aws:s3:::bucket/org_1/.recycle-bin/*",
    ]
    assert deny_listing["Condition"] == {"StringLike": {"s3:prefix": ["org_1/.recycle-bin*"]}}
