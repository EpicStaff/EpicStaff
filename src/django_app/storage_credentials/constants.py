"""Names, TTLs, and Redis key formats for per-execution storage credential
issuance."""

from src.shared.storage_credentials.constants import (
    STORAGE_CREDENTIAL_REQUEST_ENVELOPE_TYPE,
    STORAGE_CREDENTIAL_REQUEST_STREAM,
)

# Re-exported for `redis/request_consumer.py` (and any other same-package
# importer) to pull both the local and the shared-module constants from one
# place: `storage_credentials.constants`. Without `__all__` naming them,
# `ruff --fix` treats this import as unused (F401) and silently deletes it
# on the next `pre-commit run --all-files` -- which is exactly what
# happened here once already.
__all__ = [
    "CODE_RESULTS_CHANNEL",
    "CREDENTIAL_IN_PROGRESS_TTL_SECONDS",
    "CREDENTIAL_RESPONSE_TTL_SECONDS",
    "ORG_USER_POLICY_NAME_PREFIX",
    "SECRET_NAME_ORG_STORAGE_USER",
    "STORAGE_CREDENTIAL_REQUEST_CLAIM_MIN_IDLE_MS",
    "STORAGE_CREDENTIAL_REQUEST_CONSUMER_GROUP",
    "STORAGE_CREDENTIAL_REQUEST_ENVELOPE_TYPE",
    "STORAGE_CREDENTIAL_REQUEST_STREAM",
    "TEMPORARY_CREDENTIAL_TTL_SECONDS_DEFAULT",
    "TEMPORARY_CREDENTIAL_TTL_SECONDS_MAX",
    "TTL_RECONCILIATION_INTERVAL_SECONDS",
]

# `Secret(system=True, name=...)` that stores one organization's org-level
# storage IAM user credentials (access_key:secret_key, colon-joined plaintext).
SECRET_NAME_ORG_STORAGE_USER = "system_minio_org_user"

# Named storage policy attached to that same org-level user.
ORG_USER_POLICY_NAME_PREFIX = "org_storage_user_policy"

# TTL for a temporary (per-execution) service account.
TEMPORARY_CREDENTIAL_TTL_SECONDS_DEFAULT = 1200
TEMPORARY_CREDENTIAL_TTL_SECONDS_MAX = 3600

# How long an issued response waits in its List key for sandbox to BLPOP it.
CREDENTIAL_RESPONSE_TTL_SECONDS = 300

# TtlReconciliationService.sweep() cadence.
TTL_RECONCILIATION_INTERVAL_SECONDS = 900

# Consumer group over STORAGE_CREDENTIAL_REQUEST_STREAM (imported above from
# `src.shared.storage_credentials.constants`, shared with `sandbox` since
# both sides must agree on the stream name and envelope type). A durable,
# redelivery-capable primitive: unlike the scope key (GETDEL, execute-once)
# or the response key (List+BLPOP, private per-execution channel), this is
# the one link where a future horizontally scaled issuer could otherwise
# double-process the same request.
STORAGE_CREDENTIAL_REQUEST_CONSUMER_GROUP = "storage_credential_issuers"

# Idle time before a pending (unacked) request is eligible for XAUTOCLAIM
# redelivery to another consumer.
STORAGE_CREDENTIAL_REQUEST_CLAIM_MIN_IDLE_MS = 30_000

# How long the "in progress" marker set right after a delivery wins the
# scope GETDEL survives. Must outlast the slowest realistic
# credential_service.issue() call (a MinIO admin API round-trip) plus the
# STORAGE_CREDENTIAL_REQUEST_CLAIM_MIN_IDLE_MS redelivery threshold above,
# with meaningful margin, so that a redelivered duplicate (via XAUTOCLAIM)
# can see the original delivery is still working -- or just finished --
# instead of racing it with a spurious "scope_not_published" error
# response. 90s gives 3x STORAGE_CREDENTIAL_REQUEST_CLAIM_MIN_IDLE_MS
# (30s) of buffer.
CREDENTIAL_IN_PROGRESS_TTL_SECONDS = 90

CODE_RESULTS_CHANNEL = "code_results"
