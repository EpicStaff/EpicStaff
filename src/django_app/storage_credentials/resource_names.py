from storage_credentials.constants import ORG_USER_POLICY_NAME_PREFIX


def org_storage_prefix(org_id: int) -> str:
    """Bucket prefix the org-level storage user's policy grants, and the only
    namespace a temporary account derived from it may be scoped under."""
    return f"org_{org_id}"


def _org_access_key(org_id: int) -> str:
    return f"org{org_id}storageuser"


def _org_policy_name(org_id: int) -> str:
    return f"{ORG_USER_POLICY_NAME_PREFIX}_{org_id}"
