"""The manager process's settings: everything shared plus its own.

The worker container never gets these variables (database, Redis, result channels,
storage admin credentials, intake caps), which is why they live here and not in
``common.settings``. A missing or invalid one refuses the manager's startup at import.
"""

from common.settings import *
from common.settings import BASE_DIR, VENVS_DIR, env
from src.shared.redis_keys import crew_code_result_channel

DEBUG = env.bool("SANDBOX_DEBUG", False)

VENV_STAGING_DIR = VENVS_DIR / "builds"

# Local shared packages the execution wrapper imports unconditionally (dotdict,
# epicstaff_secrets) plus the shared tool helpers (epicstaff_common). They are NOT
# optional libraries: every venv must have them or no execution can run, so they are
# installed on every venv build, never exposed through a venv's `libs`.
SHARED_DIR = (BASE_DIR / ".." / "shared").resolve()
PREDEFINED_VENV_PACKAGES = (
    SHARED_DIR / "dotdict",
    SHARED_DIR / "epicstaff_secrets",
    SHARED_DIR / "epicstaff_common",
    SHARED_DIR / "epicstaff_storage",
)

# Seconds a job may wait for its venv to finish building before it is failed instead of
# run. Keep it below the producers' result backstops (CREW_CODE_RESULT_TIMEOUT,
# AGENT_CODE_RESULT_TIMEOUT, REALTIME_CODE_RESULT_TIMEOUT, 40 minutes by default), so a
# producer learns the job was not run before it gives up waiting.
HOLD_TIMEOUT = env.time("SANDBOX_HOLD_TIMEOUT")
if HOLD_TIMEOUT is None or HOLD_TIMEOUT <= 0:
    raise ValueError("SANDBOX_HOLD_TIMEOUT must be a duration above zero, not none.")

# Executions accepted and not yet finished (queued or running) before intake answers 503.
# Bounds the memory accepted jobs can hold. Held jobs are capped apart, below.
MAX_ACCEPTED_EXECUTIONS = env.int("SANDBOX_MAX_ACCEPTED_EXECUTIONS", 1000)
if MAX_ACCEPTED_EXECUTIONS is None or MAX_ACCEPTED_EXECUTIONS < 1:
    raise ValueError("SANDBOX_MAX_ACCEPTED_EXECUTIONS must be at least 1.")

# Executions waiting for their venv to finish building before intake answers 503 to
# another one that would wait.
MAX_HELD_EXECUTIONS = env.int("SANDBOX_MAX_HELD_EXECUTIONS", 100)
if MAX_HELD_EXECUTIONS is None or MAX_HELD_EXECUTIONS < 1:
    raise ValueError("SANDBOX_MAX_HELD_EXECUTIONS must be at least 1.")

DB_USER = env.str("SANDBOX_DB_USER")
DB_PASSWORD = env.str("SANDBOX_DB_PASSWORD")
DB_HOST = env.str("DB_HOST")
DB_PORT = env.int("DB_PORT")
DB_NAME = env.str("DB_NAME")
# Postgres schema the sandbox role owns; all sandbox tables + Piccolo migrations live here.
DB_SCHEMA = env.str("SANDBOX_DB_SCHEMA", "sandbox")

JOB_RESULT_CHANNEL = env.str("CODE_RESULT_CHANNEL")
# Crew reads only this channel, so it never parses results meant for django_app, agent or
# realtime. Derived from our own CODE_RESULT_CHANNEL, never from a submission payload.
CREW_JOB_RESULT_CHANNEL = crew_code_result_channel(JOB_RESULT_CHANNEL)
STORAGE_MUTATION_CHANNEL = env.str("STORAGE_MUTATION_CHANNEL")

REDIS_HOST = env.str("REDIS_HOST")
REDIS_PORT = env.int("REDIS_PORT")
REDIS_USER = env.str("REDIS_USER", "")
REDIS_PASSWORD = env.str("REDIS_PASSWORD", "")

# The service's own storage credential, used only for CUSTOM_LIBRARY_BUCKET. An execution
# never gets it: the worker builds the child environment from scratch rather than
# inheriting os.environ, and the credentials it does use arrive per job from the caller.
STORAGE_USER = env.str("STORAGE_USER")
STORAGE_PASSWORD = env.str("STORAGE_PASSWORD")

# Uploaded custom-library sources and the wheels built from them. Kept apart from
# STORAGE_BUCKET, which holds organizations' files.
CUSTOM_LIBRARY_BUCKET = env.str("SANDBOX_CUSTOM_LIBRARY_BUCKET")

# Opens the secret values django_app seals for transport. Its length is not checked here:
# django_app, which seals with the same key, refuses to start on a short one.
SECRETS_TRANSPORT_KEY = env.secret("SECRETS_TRANSPORT_KEY")
# Decrypt-only keys kept after SECRETS_TRANSPORT_KEY was replaced; `none` or empty means none.
SECRETS_TRANSPORT_PREVIOUS_KEYS = [
    key for key in env.list("SECRETS_TRANSPORT_PREVIOUS_KEYS") or [] if key
]
# HKDF info the transport key is derived with: a wire contract with django_app, the producer.
# Read from the environment, which compose shares with every service.
SECRETS_TRANSPORT_HKDF_INFO = env.str("SECRETS_TRANSPORT_HKDF_INFO")
