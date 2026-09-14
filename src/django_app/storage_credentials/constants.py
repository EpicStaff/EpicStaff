"""Names, TTLs, and Redis key formats for per-execution MinIO credential
issuance."""

from src.shared.storage_credentials.constants import (
    CREDENTIAL_SCOPE_TTL_SECONDS,
    STORAGE_CREDENTIAL_REQUEST_ENVELOPE_TYPE,
    STORAGE_CREDENTIAL_REQUEST_STREAM,
    STORAGE_CREDENTIAL_WAIT_TIMEOUT_S,
)

# `Secret(system=True, name=...)` that stores one organization's org-level
# MinIO IAM user credentials (access_key:secret_key, colon-joined plaintext).
SECRET_NAME_ORG_MINIO_USER = "system_minio_org_user"

# Named MinIO policy attached to that same org-level user.
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
