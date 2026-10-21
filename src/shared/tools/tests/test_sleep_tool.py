import pytest

from conftest import load_tool_main

sleep_module = load_tool_main("sleep_tool")
sleep_main = sleep_module.main
DEFAULT_MAX_SECONDS = sleep_module.DEFAULT_MAX_SECONDS
UNSET = object()


@pytest.fixture
def slept(monkeypatch):
    """The durations the tool actually slept for, in order."""
    durations: list[float] = []
    monkeypatch.setattr(sleep_module.time, "sleep", durations.append)
    # The sandbox injects tool config as module globals; none may leak between tests.
    monkeypatch.delitem(sleep_module.__dict__, "max_seconds", raising=False)
    return durations


@pytest.mark.parametrize(
    ("configured_max", "kwargs", "expected_sleep", "capped"),
    [
        (UNSET, {"seconds": 30}, 30.0, False),
        (UNSET, {"seconds": 2.5}, 2.5, False),
        (60, {"seconds": 30}, 30.0, False),
        (60, {"seconds": 120}, 60.0, True),
        (UNSET, {"seconds": DEFAULT_MAX_SECONDS + 500}, float(DEFAULT_MAX_SECONDS), True),
        ("not-a-number", {"seconds": 10}, 10.0, False),
        # global_kwargs folds the user_input config into func_kwargs too; the global wins.
        (60, {"seconds": 120, "max_seconds": 999}, 60.0, True),
    ],
    ids=["default-max", "float", "within-max", "over-max", "over-default-max", "bad-max-falls-back", "stray-max-kwarg"],
)
def test_sleeps_for_the_requested_time_capped_at_the_max(slept, configured_max, kwargs, expected_sleep, capped):
    if configured_max is not UNSET:
        sleep_module.max_seconds = configured_max

    result = sleep_main(reason="waiting for rate-limit window to reset", **kwargs)

    assert slept == [expected_sleep]
    assert not result.startswith("Error")
    assert "waiting for rate-limit window to reset" in result
    assert ("capped" in result.lower()) is capped
    assert f"{kwargs['seconds']:g}" in result


@pytest.mark.parametrize(
    "kwargs",
    [
        {"reason": "no duration given"},
        {"seconds": 0, "reason": "zero"},
        {"seconds": -5, "reason": "negative"},
        {"seconds": "not-a-number", "reason": "bad type"},
        {"seconds": True, "reason": "bool"},
        {"seconds": object(), "reason": "weird input"},
        {"seconds": 10},
        {"seconds": 10, "reason": "   "},
    ],
    ids=["no-seconds", "zero", "negative", "non-numeric", "boolean", "object", "no-reason", "blank-reason"],
)
def test_invalid_input_is_an_error_message_and_no_sleep(slept, kwargs):
    result = sleep_main(**kwargs)

    assert isinstance(result, str)
    assert result.startswith("Error:")
    assert slept == []
