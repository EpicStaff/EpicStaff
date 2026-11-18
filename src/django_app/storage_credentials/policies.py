"""Storage backend IAM policy builders for storage_credentials.

Two separate functions, never one with an `is_admin` flag: a temporary
(per-execution) service account must never inherit the admin statements an
org-level user needs to mint/revoke/list its own service accounts. A shared
builder with a boolean is exactly the kind of construction where one flipped
default silently escalates privilege.
"""

import json
import posixpath
from typing import Any

from django.conf import settings
from src.shared.models.storage_scope import StorageAction

from storage_credentials.exceptions import (
    CredentialScopeValidationError,
    TemporaryPolicyTooLargeError,
)
from storage_credentials.resource_names import TRASH_DIRECTORY

# The storage backend treats add/remove/update-service-account as an always-on
# "self-service" capability of any service account acting for its own parent
# user -- independent of whether those actions appear in the account's
# Allow policy: a temporary account with only 3 S3 actions in Allow, and no
# admin:* action anywhere, could still mint (and even recursively re-mint) a
# sibling service account for itself. Only an explicit Deny blocks it.
_TEMPORARY_ACCOUNT_SELF_MINT_ACTIONS = [
    "admin:CreateServiceAccount",
    "admin:RemoveServiceAccount",
    "admin:UpdateServiceAccount",
]

_S3_OBJECT_ACTIONS = {
    StorageAction.READ: "s3:GetObject",
    StorageAction.WRITE: "s3:PutObject",
    StorageAction.DELETE: "s3:DeleteObject",
}


def _normalize_path(path: str) -> str:
    stripped = path.strip()
    normalized = posixpath.normpath(stripped) if stripped else ""
    if normalized in ("", "."):
        raise CredentialScopeValidationError(
            "A specific file or folder must be selected — storage-wide access isn't allowed."
        )
    if normalized.startswith(".."):
        raise CredentialScopeValidationError(f"This file path isn't allowed: '{path}'.")
    return f"{normalized}/*" if stripped.endswith("/") else normalized


def build_org_user_policy(bucket: str, org_prefix: str) -> dict[str, Any]:
    """Policy for the long-lived, org-level storage IAM user.

    Grants S3 access to its own `org_<id>/*` prefix plus the admin actions
    needed to mint, revoke, and list its own (never another org's) service
    accounts. `admin:CreateServiceAccount`/`RemoveServiceAccount` are safe
    here specifically because `miniopy-async`'s `add_service_account` cannot
    target another principal, and the storage backend itself refuses cross-user
    minting independent of policy.
    """
    normalized_prefix = org_prefix.strip().rstrip("/")
    if not normalized_prefix:
        raise CredentialScopeValidationError(
            "This organization isn't set up for file storage yet. Please contact support."
        )

    resource = f"arn:aws:s3:::{bucket}/{normalized_prefix}/*"
    bucket_arn = f"arn:aws:s3:::{bucket}"
    prefix_condition = f"{normalized_prefix}/*"

    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
                "Resource": [resource],
            },
            {
                "Effect": "Allow",
                "Action": ["s3:ListBucket"],
                "Resource": [bucket_arn],
                "Condition": {"StringLike": {"s3:prefix": [prefix_condition]}},
            },
            {
                "Effect": "Allow",
                "Action": ["s3:GetBucketLocation"],
                "Resource": [bucket_arn],
            },
            {
                "Effect": "Allow",
                "Action": [
                    "admin:CreateServiceAccount",
                    "admin:RemoveServiceAccount",
                    "admin:ListServiceAccounts",
                ],
                # A bare "*" is valid for MinIO (admin actions aren't
                # resource-scoped), but RustFS rejects it outright at
                # policy-creation time.
                # arn:aws:s3:::* is
                # accepted by both.
                "Resource": ["arn:aws:s3:::*"],
            },
        ],
    }


def build_temporary_policy(
    bucket: str,
    *,
    shared_folders: set[str],
    shared_actions: frozenset[StorageAction],
    own_folders: set[str],
) -> dict[str, Any]:
    """Policy for a per-execution temporary service account.

    Scoped to exactly `shared_folders` and `own_folders` (together a subset of the
    owning org's prefix, validated by `CredentialScopeValidator` before this is
    called). `own_folders` are the run's own folders and get every action.
    `shared_folders` are the files attached to the run and get only
    `shared_actions`, which django takes from the storage grant of the node. User code
    holds these credentials and can call S3 directly, so the policy is what enforces
    them. READ maps to s3:GetObject plus ListBucket on the prefixes, WRITE to
    s3:PutObject, DELETE to s3:DeleteObject. Empty
    `shared_actions` leaves the shared folders out of the policy altogether.

    The explicit Deny statement (4) is not optional hardening -- without it,
    a leaked temporary credential could re-mint itself a replacement service
    account before revocation/TTL catches up, defeating the entire
    revocation mechanism this design relies on.

    Statements (5) and (6) deny the org's recycle-bin folder: user code holds
    these credentials and can call S3 directly, so the policy is the guard, and
    a Deny wins over any Allow above, even for a folder that contains it.

    Allow statements with the same actions are merged, because the storage
    backend rejects a policy over a size limit (see `_assert_policy_fits`).

    Raises:
        CredentialScopeValidationError: no folder is left to grant.
        TemporaryPolicyTooLargeError: the policy exceeds the backend's size limit.
    """
    granted_shared_actions = frozenset(shared_actions) if shared_folders else frozenset()
    own_prefixes = sorted({_normalize_path(folder) for folder in own_folders})
    shared_prefixes = (
        sorted({_normalize_path(folder) for folder in shared_folders})
        if granted_shared_actions
        else []
    )
    if not own_prefixes and not shared_prefixes:
        raise CredentialScopeValidationError(
            "This request doesn't specify which files it needs. Check the file "
            "attachments in your flow."
        )

    prefixes_by_actions: dict[frozenset[StorageAction], set[str]] = {}
    if own_prefixes:
        prefixes_by_actions.setdefault(frozenset(StorageAction), set()).update(own_prefixes)
    if shared_prefixes:
        prefixes_by_actions.setdefault(granted_shared_actions, set()).update(shared_prefixes)

    bucket_arn = f"arn:aws:s3:::{bucket}"
    prefixes = sorted(set(own_prefixes) | set(shared_prefixes))
    readable_prefixes = sorted(
        {
            prefix
            for actions, action_prefixes in prefixes_by_actions.items()
            if StorageAction.READ in actions
            for prefix in action_prefixes
        }
    )
    # Every folder sits under its org prefix (CredentialScopeValidator), so its first
    # segment is the org whose recycle bin must stay out of reach.
    trash_folders = sorted({f"{prefix.split('/', 1)[0]}/{TRASH_DIRECTORY}" for prefix in prefixes})

    statements: list[dict[str, Any]] = [
        {
            "Effect": "Allow",
            "Action": [_S3_OBJECT_ACTIONS[action] for action in StorageAction if action in actions],
            "Resource": [f"{bucket_arn}/{prefix}" for prefix in sorted(action_prefixes)],
        }
        for actions, action_prefixes in prefixes_by_actions.items()
        if actions
    ]
    if readable_prefixes:
        statements.append(
            {
                "Effect": "Allow",
                "Action": ["s3:ListBucket"],
                "Resource": [bucket_arn],
                "Condition": {"StringLike": {"s3:prefix": readable_prefixes}},
            }
        )
    statements += [
        {
            "Effect": "Allow",
            "Action": ["s3:GetBucketLocation"],
            "Resource": [bucket_arn],
        },
        {
            "Effect": "Deny",
            "Action": list(_TEMPORARY_ACCOUNT_SELF_MINT_ACTIONS),
            "Resource": ["arn:aws:s3:::*"],
        },
        {
            "Effect": "Deny",
            "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
            # The bare key too: a file named .recycle-bin would block every key
            # under it on filesystem-backed stores.
            "Resource": [
                resource
                for folder in trash_folders
                for resource in (f"{bucket_arn}/{folder}", f"{bucket_arn}/{folder}/*")
            ],
        },
        {
            "Effect": "Deny",
            "Action": ["s3:ListBucket"],
            "Resource": [bucket_arn],
            "Condition": {"StringLike": {"s3:prefix": [f"{folder}*" for folder in trash_folders]}},
        },
    ]
    policy = {"Version": "2012-10-17", "Statement": statements}
    _assert_policy_fits(policy)
    return policy


def _assert_policy_fits(policy: dict[str, Any]) -> None:
    """Refuse a policy the storage backend would reject, before calling it.

    The backend answers an oversized policy with an error that retries cannot fix,
    which would surface as a misleading "try again shortly".
    """
    size = len(json.dumps(policy, separators=(",", ":")).encode())
    if size > settings.STORAGE_TEMPORARY_POLICY_MAX_BYTES:
        raise TemporaryPolicyTooLargeError()
