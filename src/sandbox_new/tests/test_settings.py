"""Settings each process validates or derives at import time.

Shared values live in ``common.settings``; ``manager.settings`` and ``worker.settings``
re-export them and add their own, each validated at import. The worker's module must
import with no manager variables in the environment at all -- that is the whole point
of the split -- while a missing manager variable still refuses the manager's startup.

All of it is import-time behavior, so each case reloads the module chain under a patched
environment.
"""

import importlib

import pytest
from foundation.utils.env import EnvironmentBlankError

from common import settings as common_settings
from manager import settings as manager_settings
from worker import settings as worker_settings

MODULES = {
    "common": common_settings,
    "manager": manager_settings,
    "worker": worker_settings,
}


@pytest.fixture
def reload_settings_with_env():
    """Reload one settings module under patched variables, then restore everything.

    ``manager`` and ``worker`` re-export ``common``, so common is always reloaded first.
    A reload that raises leaves a module half re-executed, so every module is reloaded
    again under the original environment afterwards; other tests share these objects.
    """
    environment = pytest.MonkeyPatch()

    def reload(module_name: str = "common", _unset: tuple[str, ...] = (), **variables: str):
        for name in _unset:
            environment.delenv(name, raising=False)
        for name, value in variables.items():
            environment.setenv(name, value)
        importlib.reload(common_settings)
        if module_name == "common":
            return common_settings
        return importlib.reload(MODULES[module_name])

    yield reload

    environment.undo()
    importlib.reload(common_settings)
    importlib.reload(manager_settings)
    importlib.reload(worker_settings)


@pytest.mark.parametrize(
    ("max_timeout", "default_timeout"),
    [
        ("5m", "none"),
        ("5m", "2s"),
        ("5m", "10m"),
    ],
    ids=["default-none", "default-below-minimum", "default-above-maximum"],
)
def test_an_invalid_default_execution_timeout_refuses_startup(
    reload_settings_with_env, max_timeout, default_timeout
):
    with pytest.raises(ValueError, match="SANDBOX_DEFAULT_EXECUTION_TIMEOUT"):
        reload_settings_with_env(
            SANDBOX_MAX_EXECUTION_TIMEOUT=max_timeout,
            SANDBOX_DEFAULT_EXECUTION_TIMEOUT=default_timeout,
        )


def test_no_maximum_accepts_a_bounded_default(reload_settings_with_env):
    reloaded = reload_settings_with_env(
        SANDBOX_MAX_EXECUTION_TIMEOUT="none",
        SANDBOX_DEFAULT_EXECUTION_TIMEOUT="5m",
    )

    assert (reloaded.MAX_EXECUTION_TIMEOUT, reloaded.DEFAULT_EXECUTION_TIMEOUT) == (None, 300)


def test_the_crew_result_channel_is_derived_from_the_services_own_channel(
    reload_settings_with_env,
):
    """Crew's channel name comes from CODE_RESULT_CHANNEL, never from a submission."""
    reloaded = reload_settings_with_env("manager", CODE_RESULT_CHANNEL="somewhere:else")

    assert reloaded.CREW_JOB_RESULT_CHANNEL == "somewhere:else:crew"


@pytest.mark.parametrize("max_result_size", ["0", "-1", "none"])
def test_a_max_result_size_that_is_not_positive_refuses_startup(
    reload_settings_with_env, max_result_size
):
    with pytest.raises(ValueError, match="SANDBOX_MAX_RESULT_SIZE"):
        reload_settings_with_env("worker", SANDBOX_MAX_RESULT_SIZE=max_result_size)


def test_the_max_result_size_is_read_as_a_byte_size(reload_settings_with_env):
    reloaded = reload_settings_with_env("worker", SANDBOX_MAX_RESULT_SIZE="16mb")

    assert reloaded.MAX_RESULT_SIZE == 16 * 1024 * 1024


@pytest.mark.parametrize(
    ("module_name", "name", "value"),
    [
        ("common", "SANDBOX_QUEUE_TIMEOUT", "none"),
        ("common", "SANDBOX_QUEUE_TIMEOUT", "0s"),
        ("manager", "SANDBOX_HOLD_TIMEOUT", "none"),
        ("manager", "SANDBOX_HOLD_TIMEOUT", "0s"),
        ("manager", "SANDBOX_MAX_ACCEPTED_EXECUTIONS", "0"),
        ("manager", "SANDBOX_MAX_HELD_EXECUTIONS", "0"),
        ("worker", "SANDBOX_MIN_CONCURRENT_EXECUTIONS", "-1"),
        ("worker", "SANDBOX_MAX_CONCURRENT_EXECUTIONS", "0"),
        ("worker", "SANDBOX_CPU_ADMIT_THRESHOLD", "0"),
        ("worker", "SANDBOX_CPU_ADMIT_THRESHOLD", "100.5"),
        ("worker", "SANDBOX_MEMORY_ADMIT_THRESHOLD", "0"),
        ("worker", "SANDBOX_MEMORY_ADMIT_THRESHOLD", "101"),
    ],
)
def test_a_setting_out_of_range_refuses_its_processes_startup(
    reload_settings_with_env, module_name, name, value
):
    with pytest.raises(ValueError, match=name):
        reload_settings_with_env(module_name, **{name: value})


def test_the_admission_settings_have_their_defaults(reload_settings_with_env):
    manager = reload_settings_with_env(
        "manager", SANDBOX_QUEUE_TIMEOUT="2m", SANDBOX_HOLD_TIMEOUT="30m"
    )
    worker = reload_settings_with_env("worker")

    assert (
        manager.QUEUE_TIMEOUT,
        manager.HOLD_TIMEOUT,
        manager.MAX_ACCEPTED_EXECUTIONS,
        manager.MAX_HELD_EXECUTIONS,
        worker.MIN_CONCURRENT_EXECUTIONS,
        worker.MAX_CONCURRENT_EXECUTIONS,
        worker.CPU_ADMIT_THRESHOLD,
        worker.MEMORY_ADMIT_THRESHOLD,
    ) == (120, 1800, 1000, 100, 0, 256, 85, 80)


MANAGER_ONLY_VARIABLES = (
    "SANDBOX_DB_USER",
    "SANDBOX_DB_PASSWORD",
    "DB_HOST",
    "DB_PORT",
    "DB_NAME",
    "CODE_RESULT_CHANNEL",
    "STORAGE_MUTATION_CHANNEL",
    "REDIS_HOST",
    "REDIS_PORT",
    "STORAGE_USER",
    "STORAGE_PASSWORD",
    "SANDBOX_CUSTOM_LIBRARY_BUCKET",
    "SANDBOX_HOLD_TIMEOUT",
)


def test_the_worker_module_imports_without_manager_variables(reload_settings_with_env):
    """The worker container gets no database, Redis, channel or storage-admin variables;
    its settings module must import there and serve everything the worker reads."""
    reloaded = reload_settings_with_env("worker", _unset=MANAGER_ONLY_VARIABLES)

    assert reloaded.MANAGER_URL == "http://sandbox_new:8090"
    assert reloaded.INTERNAL_TOKEN == "internal-test-token"
    assert reloaded.QUEUE_TIMEOUT == 120
    assert reloaded.MAX_RESULT_SIZE == 16 * 1024 * 1024


def test_the_manager_module_refuses_startup_without_its_variables(reload_settings_with_env):
    with pytest.raises(Exception, match="SANDBOX_HOLD_TIMEOUT"):
        reload_settings_with_env("manager", _unset=MANAGER_ONLY_VARIABLES)


@pytest.mark.parametrize("configured", ["VERBOSE", "none", ""])
def test_an_unknown_log_level_refuses_startup(reload_settings_with_env, configured):
    with pytest.raises(ValueError, match="SANDBOX_LOG_LEVEL"):
        reload_settings_with_env(SANDBOX_LOG_LEVEL=configured)


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        ("none", []),
        ("", []),
        ("old-key-0001", ["old-key-0001"]),
        (" old-key-0001 , ,old-key-0002 ,", ["old-key-0001", "old-key-0002"]),
    ],
    ids=["none", "empty", "one", "padded-with-empty-items"],
)
def test_previous_transport_keys_are_split_stripped_and_empty_items_dropped(
    reload_settings_with_env, configured, expected
):
    previous_keys = reload_settings_with_env(
        "manager", SECRETS_TRANSPORT_PREVIOUS_KEYS=configured
    ).SECRETS_TRANSPORT_PREVIOUS_KEYS

    assert previous_keys == expected


@pytest.mark.parametrize("configured", ["", "   ", "none"])
def test_a_blank_transport_key_refuses_startup(reload_settings_with_env, configured):
    with pytest.raises(EnvironmentBlankError, match="SECRETS_TRANSPORT_KEY"):
        reload_settings_with_env("manager", SECRETS_TRANSPORT_KEY=configured)


def test_a_short_transport_key_is_accepted(reload_settings_with_env):
    """django_app owns the length rule; the sandbox only refuses a blank key."""
    reloaded = reload_settings_with_env("manager", SECRETS_TRANSPORT_KEY="short")

    assert reloaded.SECRETS_TRANSPORT_KEY == "short"
