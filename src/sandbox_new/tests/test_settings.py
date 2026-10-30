"""Settings the service validates or derives at import time.

Invariant: the sandbox refuses to start unless SANDBOX_DEFAULT_EXECUTION_TIMEOUT is a
bounded duration of at least MIN_EXECUTION_TIMEOUT seconds and not above
SANDBOX_MAX_EXECUTION_TIMEOUT, because a job without a timeout of its own runs under that
default. SANDBOX_MAX_EXECUTION_TIMEOUT may be none (no upper limit).

The admission settings refuse startup too when out of range: a queue or hold timeout that
is none or not positive, caps below 1, a negative minimum, a threshold outside (0, 100].

Both are import-time behavior, so each case reloads settings.py under a patched
environment.
"""

import importlib

import pytest

import settings


@pytest.fixture
def reload_settings_with_env():
    """Reload settings.py under patched variables, then restore the environment and module.

    A reload that raises leaves the module half re-executed, so the module is always
    reloaded again under the original environment afterwards; other tests share this
    module object.
    """
    environment = pytest.MonkeyPatch()

    def reload(**variables: str):
        for name, value in variables.items():
            environment.setenv(name, value)
        return importlib.reload(settings)

    yield reload

    environment.undo()
    importlib.reload(settings)


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
    reloaded = reload_settings_with_env(CODE_RESULT_CHANNEL="somewhere:else")

    assert reloaded.CREW_JOB_RESULT_CHANNEL == "somewhere:else:crew"


@pytest.mark.parametrize("max_result_size", ["0", "-1", "none"])
def test_a_max_result_size_that_is_not_positive_refuses_startup(
    reload_settings_with_env, max_result_size
):
    with pytest.raises(ValueError, match="SANDBOX_MAX_RESULT_SIZE"):
        reload_settings_with_env(SANDBOX_MAX_RESULT_SIZE=max_result_size)


def test_the_max_result_size_is_read_as_a_byte_size(reload_settings_with_env):
    reloaded = reload_settings_with_env(SANDBOX_MAX_RESULT_SIZE="16mb")

    assert reloaded.MAX_RESULT_SIZE == 16 * 1024 * 1024


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("SANDBOX_QUEUE_TIMEOUT", "none"),
        ("SANDBOX_QUEUE_TIMEOUT", "0s"),
        ("SANDBOX_HOLD_TIMEOUT", "none"),
        ("SANDBOX_HOLD_TIMEOUT", "0s"),
        ("SANDBOX_MAX_ACCEPTED_EXECUTIONS", "0"),
        ("SANDBOX_MAX_HELD_EXECUTIONS", "0"),
        ("SANDBOX_MIN_CONCURRENT_EXECUTIONS", "-1"),
        ("SANDBOX_MAX_CONCURRENT_EXECUTIONS", "0"),
        ("SANDBOX_CPU_ADMIT_THRESHOLD", "0"),
        ("SANDBOX_CPU_ADMIT_THRESHOLD", "100.5"),
        ("SANDBOX_MEMORY_ADMIT_THRESHOLD", "0"),
        ("SANDBOX_MEMORY_ADMIT_THRESHOLD", "101"),
    ],
)
def test_an_admission_setting_out_of_range_refuses_startup(reload_settings_with_env, name, value):
    with pytest.raises(ValueError, match=name):
        reload_settings_with_env(**{name: value})


def test_the_admission_settings_have_their_defaults(reload_settings_with_env):
    reloaded = reload_settings_with_env(SANDBOX_QUEUE_TIMEOUT="2m", SANDBOX_HOLD_TIMEOUT="30m")

    assert (
        reloaded.QUEUE_TIMEOUT,
        reloaded.HOLD_TIMEOUT,
        reloaded.MAX_ACCEPTED_EXECUTIONS,
        reloaded.MAX_HELD_EXECUTIONS,
        reloaded.MIN_CONCURRENT_EXECUTIONS,
        reloaded.MAX_CONCURRENT_EXECUTIONS,
        reloaded.CPU_ADMIT_THRESHOLD,
        reloaded.MEMORY_ADMIT_THRESHOLD,
    ) == (120, 1800, 300, 100, 0, 256, 85, 80)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("SANDBOX_CPU_ADMIT_THRESHOLD", "100"),
        ("SANDBOX_MIN_CONCURRENT_EXECUTIONS", "0"),
        ("SANDBOX_HOLD_TIMEOUT", "1s"),
        ("SANDBOX_MAX_HELD_EXECUTIONS", "1"),
    ],
)
def test_an_admission_setting_at_its_bound_is_accepted(reload_settings_with_env, name, value):
    reload_settings_with_env(**{name: value})


@pytest.mark.parametrize(
    ("configured", "expected"),
    [("BENCH", "BENCH"), ("bench", "BENCH"), (" warning ", "WARNING")],
)
def test_log_level_accepts_every_loguru_level_and_bench(
    reload_settings_with_env, configured, expected
):
    reloaded = reload_settings_with_env(SANDBOX_LOG_LEVEL=configured)

    assert reloaded.LOG_LEVEL == expected


@pytest.mark.parametrize("configured", ["VERBOSE", "none", ""])
def test_an_unknown_log_level_refuses_startup(reload_settings_with_env, configured):
    with pytest.raises(ValueError, match="SANDBOX_LOG_LEVEL"):
        reload_settings_with_env(SANDBOX_LOG_LEVEL=configured)
