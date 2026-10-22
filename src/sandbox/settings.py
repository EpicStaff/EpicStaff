from pathlib import Path

from src.shared.envtools import Env

BASE_DIR = Path(__file__).resolve().parent

env = Env()
if not env.bool("RUN_IN_DOCKER", False):
    env.read_env(env_file=BASE_DIR / "../.env")

LOG_LEVEL = env.log_level("SANDBOX_LOG_LEVEL", allowed=env.LOG_LEVELS_WITH_BENCH)

REDIS_HOST = env.str("REDIS_HOST")
REDIS_PORT = env.str("REDIS_PORT")
REDIS_USER = env.str("REDIS_USER")
REDIS_PASSWORD = env.str("REDIS_PASSWORD")

CODE_RESULT_CHANNEL = env.str("CODE_RESULT_CHANNEL")
STORAGE_MUTATION_CHANNEL = env.str("STORAGE_MUTATION_CHANNEL")
CODE_EXEC_CHANNEL = env.str("CODE_EXEC_CHANNEL")

OUTPUT_PATH = env.path("SANDBOX_OUTPUT_PATH")
BASE_VENV_PATH = env.path("SANDBOX_BASE_VENV_PATH")

# Non-secret object storage connection details only. Deliberately no
# STORAGE_ACCESS_KEY/STORAGE_SECRET_KEY here: sandbox never holds the admin
# storage credential. Temporary, session-scoped credentials are minted by
# django_app and passed in via CodeTaskData.storage_credentials -- see
# dynamic_venv_executor_chain.py.
STORAGE_HOST = env.str("STORAGE_HOST")
STORAGE_PORT = env.str("STORAGE_PORT")
http = "https" if env.bool("STORAGE_SSL") else "http"
STORAGE_ENDPOINT = f"{http}://{STORAGE_HOST}:{STORAGE_PORT}"
STORAGE_BUCKET_NAME = env.str("STORAGE_BUCKET")

MASK_SECRET = env.bool("SANDBOX_MASK_SECRET")

# NOTE: must equal MIN_EXECUTION_TIMEOUT_SECONDS in
# src/django_app/django_app/settings/execution_timeout.py.
MIN_EXECUTION_TIMEOUT = 3
# Seconds. None means no upper limit.
MAX_EXECUTION_TIMEOUT = env.time("SANDBOX_MAX_EXECUTION_TIMEOUT")
DEFAULT_EXECUTION_TIMEOUT = env.time("SANDBOX_DEFAULT_EXECUTION_TIMEOUT")

# Same rules django_app enforces on startup: a task without a timeout of its own must still
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

BLOCK_NETWORK = env.bool("SANDBOX_BLOCK_NETWORK")

# Escape hatch for kernels without Landlock: false lets executions run unconfined
# instead of being refused. A deliberately temporary, security-relevant knob.
REQUIRE_ISOLATION_ENV_VAR = "SANDBOX_REQUIRE_ISOLATION"
REQUIRE_ISOLATION = env.bool(REQUIRE_ISOLATION_ENV_VAR)

REQUIRE_SIGNAL_ISOLATION_ENV_VAR = "SANDBOX_REQUIRE_SIGNAL_ISOLATION"
REQUIRE_SIGNAL_ISOLATION = env.bool(REQUIRE_SIGNAL_ISOLATION_ENV_VAR)

BLOCK_PRIVATE_NETWORK_ENV_VAR = "SANDBOX_BLOCK_PRIVATE_NETWORK"
BLOCK_PRIVATE_NETWORK = env.bool(BLOCK_PRIVATE_NETWORK_ENV_VAR)
