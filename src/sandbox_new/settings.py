from pathlib import Path

from foundation.utils.env import Env

BASE_DIR = Path(__file__).resolve().parent

env = Env()
if not env.bool("RUN_IN_DOCKER", False):
    env.read_env(env_file=BASE_DIR / "../.env")

DEBUG = env.bool("SANDBOX_DEBUG", False)

# Read from env so the code and the mounted volume agree on one path.
VENVS_DIR = env.path("SANDBOX_VENVS_DIR", BASE_DIR / "venvs")
VENV_STAGING_DIR = VENVS_DIR / "builds"

# Per-execution workspaces are created under here; savefiles is the shared volume.
EXECUTIONS_DIR = BASE_DIR / "executions"
SAVEFILES_DIR = BASE_DIR / "savefiles"

# Local shared packages the execution wrapper imports unconditionally (dotdict,
# epicstaff_secrets) plus the shared tool helpers (epicstaff_common). They are NOT
# optional libraries: every venv must have them or no execution can run, so they are
# installed on every venv build, never exposed through a venv's `libs`.
SHARED_DIR = (BASE_DIR / ".." / "shared").resolve()
PREDEFINED_VENV_PACKAGES = (
    SHARED_DIR / "dotdict",
    SHARED_DIR / "epicstaff_secrets",
    SHARED_DIR / "epicstaff_common",
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
STORAGE_MUTATION_CHANNEL = env.str("STORAGE_MUTATION_CHANNEL")

REDIS_HOST = env.str("REDIS_HOST")
REDIS_PORT = env.int("REDIS_PORT")
REDIS_USER = env.str("REDIS_USER", "")
REDIS_PASSWORD = env.str("REDIS_PASSWORD", "")

EXECUTION_TIMEOUT = env.time("SANDBOX_EXECUTION_TIMEOUT")

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
STORAGE_ACCESS_KEY = env.str("STORAGE_USER")
STORAGE_SECRET_KEY = env.str("STORAGE_PASSWORD")
