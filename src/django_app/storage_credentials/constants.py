"""Names, TTLs, and Redis key formats for per-execution MinIO credential
issuance."""

# `Secret(system=True, name=...)` that stores one organization's org-level
# MinIO IAM user credentials (access_key:secret_key, colon-joined plaintext).
SECRET_NAME_ORG_MINIO_USER = "system_minio_org_user"

# Named MinIO policy attached to that same org-level user.
ORG_USER_POLICY_NAME_PREFIX = "org_storage_user_policy"

# TTL for a temporary (per-execution) service account.
TEMPORARY_CREDENTIAL_TTL_SECONDS_DEFAULT = 1200
TEMPORARY_CREDENTIAL_TTL_SECONDS_MAX = 3600

# How long the trusted scope written by a publisher survives before a
# never-consumed request is presumed abandoned.
CREDENTIAL_SCOPE_TTL_SECONDS = 900

# How long an issued response waits in its List key for sandbox to BLPOP it.
CREDENTIAL_RESPONSE_TTL_SECONDS = 300

# TtlReconciliationService.sweep() cadence.
TTL_RECONCILIATION_INTERVAL_SECONDS = 900

# Background issuer heartbeat cadence + the TTL on the heartbeat key itself
# (4 missed cycles before /ht/ reports unhealthy).
ISSUER_HEARTBEAT_INTERVAL_SECONDS = 5
ISSUER_HEARTBEAT_KEY_TTL_SECONDS = 20

# How long sandbox's credential-wait client blocks on BLPOP before treating
# the issuer as unreachable and failing closed.
STORAGE_CREDENTIAL_WAIT_TIMEOUT_S = 15

# Redis Stream + consumer group carrying credential-issuance requests
# (sandbox -> issuer). A durable, redelivery-capable primitive: unlike the
# scope key (GETDEL, execute-once) or the response key (List+BLPOP, private
# per-execution channel), this is the one link where a future horizontally
# scaled issuer could otherwise double-process the same request.
STORAGE_CREDENTIAL_REQUEST_STREAM = "storage_credential_requests"
STORAGE_CREDENTIAL_REQUEST_CONSUMER_GROUP = "storage_credential_issuers"
STORAGE_CREDENTIAL_REQUEST_ENVELOPE_TYPE = "issue_temporary_credential"

# Idle time before a pending (unacked) request is eligible for XAUTOCLAIM
# redelivery to another consumer.
STORAGE_CREDENTIAL_REQUEST_CLAIM_MIN_IDLE_MS = 30_000

CODE_RESULTS_CHANNEL = "code_results"
