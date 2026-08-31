"""MinIO IAM policy builders for storage_credentials.

Two separate functions, never one with an `is_admin` flag: a temporary
(per-execution) service account must never inherit the admin statements an
org-level user needs to mint/revoke/list its own service accounts. A shared
builder with a boolean is exactly the kind of construction where one flipped
default silently escalates privilege.
"""

import posixpath
from typing import Any

from storage_credentials.exceptions import CredentialScopeValidationError

# MinIO treats add/remove/update-service-account as an always-on
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


def _normalize_path(path: str) -> str:
    stripped = path.strip()
    normalized = posixpath.normpath(stripped) if stripped else ""
    if normalized in ("", "."):
        raise CredentialScopeValidationError(
            "Empty path is not allowed (would grant bucket-wide access)."
        )
    if normalized.startswith(".."):
        raise CredentialScopeValidationError(f"Path traversal in path: '{path}'")
    return f"{normalized}/*" if stripped.endswith("/") else normalized


def build_org_user_policy(bucket: str, org_prefix: str) -> dict[str, Any]:
    """Policy for the long-lived, org-level MinIO IAM user.

    Grants S3 access to its own `org_<id>/*` prefix plus the admin actions
    needed to mint, revoke, and list its own (never another org's) service
    accounts. `admin:CreateServiceAccount`/`RemoveServiceAccount` are safe
    here specifically because `miniopy-async`'s `add_service_account` cannot
    target another principal, and the MinIO server itself refuses cross-user
    minting independent of policy.
    """
    normalized_prefix = org_prefix.strip().rstrip("/")
    if not normalized_prefix:
        raise CredentialScopeValidationError("org_prefix must not be empty.")

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
                "Resource": ["*"],
            },
        ],
    }


def build_temporary_policy(bucket: str, allowed_folders: set[str]) -> dict[str, Any]:
    """Policy for a per-execution temporary service account.

    Scoped to exactly `allowed_folders` (a subset of the owning org's
    prefix, validated by `CredentialScopeValidator` before this is called).

    The explicit Deny statement (4) is not optional hardening -- without it,
    a leaked temporary credential could re-mint itself a replacement service
    account before revocation/TTL catches up, defeating the entire
    revocation mechanism this design relies on.
    """
    if not allowed_folders:
        raise CredentialScopeValidationError("No folders provided.")

    bucket_arn = f"arn:aws:s3:::{bucket}"
    prefixes = sorted(_normalize_path(folder) for folder in allowed_folders)
    resources = [f"{bucket_arn}/{prefix}" for prefix in prefixes]

    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
                "Resource": resources,
            },
            {
                "Effect": "Allow",
                "Action": ["s3:ListBucket"],
                "Resource": [bucket_arn],
                "Condition": {"StringLike": {"s3:prefix": prefixes}},
            },
            {
                "Effect": "Allow",
                "Action": ["s3:GetBucketLocation"],
                "Resource": [bucket_arn],
            },
            {
                "Effect": "Deny",
                "Action": list(_TEMPORARY_ACCOUNT_SELF_MINT_ACTIONS),
                "Resource": ["*"],
            },
        ],
    }
