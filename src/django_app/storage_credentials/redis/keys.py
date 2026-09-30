"""Every Redis key format used by storage_credentials, in one place -- so a
key never gets built slightly differently by the writer than the reader.

The scope and response key formats are imported, not re-declared:
`src.shared.storage_credentials.scope_publisher` is what every publisher
(crew/agent/realtime/django "Test run") writes scopes with, and
`src.shared.storage_credentials.response_key_builder` is what both the issuer
and sandbox use for responses -- they must agree on the literal format, not
just a similar one.
"""

from src.shared.storage_credentials.response_key_builder import (
    CREDENTIAL_RESPONSE_KEY_PREFIX,
    response_key,
)
from src.shared.storage_credentials.scope_publisher import (
    CREDENTIAL_SCOPE_KEY_PREFIX,
)

__all__ = [
    "CREDENTIAL_RESPONSE_KEY_PREFIX",
    "CREDENTIAL_SCOPE_KEY_PREFIX",
    "in_progress_key",
    "lease_key",
    "response_key",
    "scope_key",
]

CREDENTIAL_LEASE_KEY_PREFIX = "storage_credential_lease"
CREDENTIAL_IN_PROGRESS_KEY_PREFIX = "storage_credential_in_progress"
ISSUER_HEARTBEAT_KEY = "storage_credential_issuer_heartbeat"


def scope_key(execution_id: str) -> str:
    return f"{CREDENTIAL_SCOPE_KEY_PREFIX}:{execution_id}"


def lease_key(execution_id: str) -> str:
    return f"{CREDENTIAL_LEASE_KEY_PREFIX}:{execution_id}"


def in_progress_key(execution_id: str) -> str:
    return f"{CREDENTIAL_IN_PROGRESS_KEY_PREFIX}:{execution_id}"
