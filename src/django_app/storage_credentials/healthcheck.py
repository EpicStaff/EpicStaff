import os
import sys
import time

HEARTBEAT_FILE_DEFAULT = "/dev/shm/storage_credential_issuer_heartbeat"
HEARTBEAT_MAX_AGE_SECONDS_DEFAULT = 20

heartbeat_file_path = os.environ.get("HEARTBEAT_FILE", HEARTBEAT_FILE_DEFAULT)
heartbeat_max_age_seconds = float(
    os.environ.get("HEARTBEAT_MAX_AGE_SECONDS", HEARTBEAT_MAX_AGE_SECONDS_DEFAULT)
)

try:
    heartbeat_age_seconds = time.time() - os.path.getmtime(heartbeat_file_path)
except OSError:
    sys.exit(1)

sys.exit(0 if heartbeat_age_seconds < heartbeat_max_age_seconds else 1)
