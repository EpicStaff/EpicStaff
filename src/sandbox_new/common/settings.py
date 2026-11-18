"""Settings both processes read.

Each process imports its own module -- ``manager.settings`` or ``worker.settings`` --
which re-exports everything here and adds its own variables, so one container never
needs the other's environment. Only truly shared values live in this module.
"""

from pathlib import Path

from foundation.utils.env import Env
from src.shared.envtools import Env as SharedEnv

__all__ = [
    "BASE_DIR",
    "DEFAULT_EXECUTION_TIMEOUT",
    "INTERNAL_TOKEN",
    "LOG_LEVEL",
    "MAX_EXECUTION_TIMEOUT",
    "MIN_EXECUTION_TIMEOUT",
    "QUEUE_TIMEOUT",
    "STORAGE_BUCKET",
    "STORAGE_ENDPOINT",
    "STORAGE_HOST",
    "STORAGE_PORT",
    "STORAGE_SSL",
    "VENVS_DIR",
]

# The service's package root (src/sandbox_new), not this module's directory.
BASE_DIR = Path(__file__).resolve().parent.parent

env = Env()
if not env.bool("RUN_IN_DOCKER", False):
    env.read_env(env_file=BASE_DIR / "../.env")

LOG_LEVEL = env.get_value("SANDBOX_LOG_LEVEL", "INFO", lambda value: value.strip().upper())
# Checked here so a typo (or "none") fails at startup, not inside loguru on the first sink.
# foundation's Env has no log_level(); the accepted names come from the shared one.
if LOG_LEVEL not in SharedEnv.LOG_LEVELS_WITH_BENCH:
    raise ValueError(
        f"SANDBOX_LOG_LEVEL={LOG_LEVEL!r} is not a log level; "
        f"use one of {', '.join(SharedEnv.LOG_LEVELS_WITH_BENCH)}."
    )

# Read from env so the code and the mounted volume agree on one path. The manager builds
# venvs into it; the worker resolves and runs them from it.
VENVS_DIR = env.path("SANDBOX_VENVS_DIR", BASE_DIR / "venvs")

# Seconds a job may wait in the worker queue before it is failed instead of run. Read by
# both processes: the manager predicts queue waits with it, the worker expires queued
# jobs against it.
QUEUE_TIMEOUT = env.time("SANDBOX_QUEUE_TIMEOUT")
if QUEUE_TIMEOUT is None or QUEUE_TIMEOUT <= 0:
    raise ValueError("SANDBOX_QUEUE_TIMEOUT must be a duration above zero, not none.")

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

# Shared secret the worker presents on the manager's /worker endpoints. Those hand out
# job payloads with plaintext secrets, so they must never answer an unauthenticated
# caller. No default: a deployment without it must not start.
INTERNAL_TOKEN = env.str("SANDBOX_INTERNAL_TOKEN")
if not INTERNAL_TOKEN:
    raise ValueError("SANDBOX_INTERNAL_TOKEN must be a non-empty secret.")

# The one port a storage-enabled execution is allowed to reach.
STORAGE_PORT = env.int("STORAGE_PORT")

STORAGE_HOST = env.str("STORAGE_HOST")
STORAGE_SSL = env.bool("STORAGE_SSL")
STORAGE_ENDPOINT = f"{'https' if STORAGE_SSL else 'http'}://{STORAGE_HOST}:{STORAGE_PORT}"
STORAGE_BUCKET = env.str("STORAGE_BUCKET")
