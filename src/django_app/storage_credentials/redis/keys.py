"""Every Redis key format used by storage_credentials, in one place -- so a
key never gets built slightly differently by the writer than the reader.

The scope key format is imported, not re-declared: `src.shared.storage_
credentials.scope_publisher` is what every publisher (crew/agent/realtime/
django "Test run") writes with, and this module is what the issuer reads
with -- they must agree on the literal format, not just a similar one.
"""

from src.shared.storage_credentials.scope_publisher import (
    CREDENTIAL_SCOPE_KEY_PREFIX,
)

CREDENTIAL_RESPONSE_KEY_PREFIX = "storage_credential_response"
CREDENTIAL_LEASE_KEY_PREFIX = "storage_credential_lease"
CREDENTIAL_IN_PROGRESS_KEY_PREFIX = "storage_credential_in_progress"
ISSUER_HEARTBEAT_KEY = "storage_credential_issuer_heartbeat"


def scope_key(execution_id: str) -> str:
    return f"{CREDENTIAL_SCOPE_KEY_PREFIX}:{execution_id}"


def response_key(execution_id: str) -> str:
    return f"{CREDENTIAL_RESPONSE_KEY_PREFIX}:{execution_id}"


def lease_key(execution_id: str) -> str:
    return f"{CREDENTIAL_LEASE_KEY_PREFIX}:{execution_id}"


def in_progress_key(execution_id: str) -> str:
    return f"{CREDENTIAL_IN_PROGRESS_KEY_PREFIX}:{execution_id}"
