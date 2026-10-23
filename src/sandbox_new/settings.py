from pathlib import Path

from foundation.utils.env import Env
from src.shared.redis_keys import crew_code_result_channel

BASE_DIR = Path(__file__).resolve().parent

env = Env()
if not env.bool("RUN_IN_DOCKER", False):
    env.read_env(env_file=BASE_DIR / "../.env")

DEBUG = env.bool("SANDBOX_DEBUG", False)

# Independent of DEBUG: that one only switches Litestar's debug responses.
LOG_LEVEL = env.str("SANDBOX_LOG_LEVEL", "INFO")

# Read from env so the code and the mounted volume agree on one path.
VENVS_DIR = env.path("SANDBOX_VENVS_DIR", BASE_DIR / "venvs")
VENV_STAGING_DIR = VENVS_DIR / "builds"

# Per-execution workspaces are created under here.
EXECUTIONS_DIR = BASE_DIR / "executions"

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

# How many executions the worker runs concurrently.
WORKER_CONCURRENCY = env.int("SANDBOX_WORKER_CONCURRENCY", 4)

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

# NOTE: must equal MIN_EXECUTION_TIMEOUT_SECONDS in
# src/django_app/django_app/settings/execution_timeout.py, which is the lowest timeout the
# frontend lets a user pick.
MIN_EXECUTION_TIMEOUT = 3
# Seconds. None means no upper limit.
MAX_EXECUTION_TIMEOUT = env.time("SANDBOX_MAX_EXECUTION_TIMEOUT")
DEFAULT_EXECUTION_TIMEOUT = env.time("SANDBOX_DEFAULT_EXECUTION_TIMEOUT")

# Same rules django_app enforces on startup: a job without a timeout of its own must still
# get a bounded one, so the default is never none and always within [MIN, MAX].
if DEFAULT_EXECUTION_TIMEOUT is None:
    raise ValueError("SANDBOX_DEFAULT_EXECUTION_TIMEOUT cannot be none.")
if DEFAULT_EXECUTION_TIMEOUT < MIN_EXECUTION_TIMEOUT or (
    MAX_EXECUTION_TIMEOUT is not None and DEFAULT_EXECUTION_TIMEOUT > MAX_EXECUTION_TIMEOUT
):
    raise ValueError(
        f"SANDBOX_DEFAULT_EXECUTION_TIMEOUT must be at least {MIN_EXECUTION_TIMEOUT}s "
        "and not above SANDBOX_MAX_EXECUTION_TIMEOUT."
    )

# Bytes. Caps the result and storage mutations files the worker reads back from a run.
MAX_RESULT_SIZE = env.byte_size("SANDBOX_MAX_RESULT_SIZE")
if MAX_RESULT_SIZE is None or MAX_RESULT_SIZE <= 0:
    raise ValueError("SANDBOX_MAX_RESULT_SIZE must be a positive size, not none.")

# Defaults are the confining value: a missing setting must not unconfine the sandbox.
MASK_SECRET = env.bool("SANDBOX_MASK_SECRET", True)
BLOCK_NETWORK = env.bool("SANDBOX_BLOCK_NETWORK", True)
REQUIRE_ISOLATION = env.bool("SANDBOX_REQUIRE_ISOLATION", True)
REQUIRE_SIGNAL_ISOLATION = env.bool("SANDBOX_REQUIRE_SIGNAL_ISOLATION", True)

# The one port a storage-enabled execution is allowed to reach.
STORAGE_PORT = env.int("STORAGE_PORT")

STORAGE_HOST = env.str("STORAGE_HOST")
STORAGE_SSL = env.bool("STORAGE_SSL")
STORAGE_ENDPOINT = f"{'https' if STORAGE_SSL else 'http'}://{STORAGE_HOST}:{STORAGE_PORT}"
STORAGE_BUCKET = env.str("STORAGE_BUCKET")
