"""The worker process's settings: everything shared plus its own.

This is the whole environment the worker container needs. It deliberately contains no
database, Redis or storage-admin variables -- the container that runs user code gets
none of those.
"""

from common.settings import *
from common.settings import BASE_DIR, env

# Per-execution workspaces are created under here, inside the container's own filesystem.
EXECUTIONS_DIR = BASE_DIR / "executions"

# Executions that always start whatever the load; 0 means the CPUs the container may use.
MIN_CONCURRENT_EXECUTIONS = env.int("SANDBOX_MIN_CONCURRENT_EXECUTIONS", 0)
# Executions that never run at once, whatever the load.
MAX_CONCURRENT_EXECUTIONS = env.int("SANDBOX_MAX_CONCURRENT_EXECUTIONS", 256)
# Percent. Above the minimum, a job starts only while host CPU and container memory are
# below these.
CPU_ADMIT_THRESHOLD = env.float("SANDBOX_CPU_ADMIT_THRESHOLD", 85)
MEMORY_ADMIT_THRESHOLD = env.float("SANDBOX_MEMORY_ADMIT_THRESHOLD", 80)

if MIN_CONCURRENT_EXECUTIONS is None or MIN_CONCURRENT_EXECUTIONS < 0:
    raise ValueError("SANDBOX_MIN_CONCURRENT_EXECUTIONS must be 0 (auto) or more.")
if MAX_CONCURRENT_EXECUTIONS is None or MAX_CONCURRENT_EXECUTIONS < 1:
    raise ValueError("SANDBOX_MAX_CONCURRENT_EXECUTIONS must be at least 1.")
for _name, _threshold in (
    ("SANDBOX_CPU_ADMIT_THRESHOLD", CPU_ADMIT_THRESHOLD),
    ("SANDBOX_MEMORY_ADMIT_THRESHOLD", MEMORY_ADMIT_THRESHOLD),
):
    if _threshold is None or not 0 < _threshold <= 100:
        raise ValueError(f"{_name} must be a percentage above 0 and at most 100.")

# Bytes. Caps the result and storage mutations files the worker reads back from a run.
MAX_RESULT_SIZE = env.byte_size("SANDBOX_MAX_RESULT_SIZE")
if MAX_RESULT_SIZE is None or MAX_RESULT_SIZE <= 0:
    raise ValueError("SANDBOX_MAX_RESULT_SIZE must be a positive size, not none.")

# Defaults are the confining value: a missing setting must not unconfine the sandbox.
MASK_SECRET = env.bool("SANDBOX_MASK_SECRET", True)
BLOCK_NETWORK = env.bool("SANDBOX_BLOCK_NETWORK", True)
REQUIRE_ISOLATION = env.bool("SANDBOX_REQUIRE_ISOLATION", True)
REQUIRE_SIGNAL_ISOLATION = env.bool("SANDBOX_REQUIRE_SIGNAL_ISOLATION", True)

# Where the worker reaches the manager's /worker endpoints. The same name and port every
# producer uses; the worker is just one more HTTP client of the manager.
MANAGER_URL = f"http://{env.str('SANDBOX_HOST')}:{env.int('SANDBOX_PORT')}"
