# Local liveness file touched alongside the Redis heartbeat key, read by the
# Docker healthcheck probe.
ISSUER_HEARTBEAT_FILE_PATH = "/dev/shm/storage_credential_issuer_heartbeat"
# Background issuer heartbeat cadence + the TTL on the heartbeat key itself
# (4 missed cycles before the Docker healthcheck probe reports unhealthy).
ISSUER_HEARTBEAT_INTERVAL_SECONDS = 5
ISSUER_HEARTBEAT_KEY_TTL_SECONDS = 20
