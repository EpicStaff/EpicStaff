import signal
import time

import pytest

from dotdict import DotDict

DEPTH = 28
WATCHDOG_TIMEOUT_SECONDS = 5
MAX_ALLOWED_CONSTRUCTION_SECONDS = 1.0


class _ConstructionTimeout(Exception):
    pass


def _build_nested_dict(depth: int) -> dict:
    data = {"value": "leaf"}
    for level in range(depth, 0, -1):
        data = {f"level_{level}": data}
    return data


def _raise_construction_timeout(signum, frame):
    raise _ConstructionTimeout(
        f"DotDict construction did not complete within "
        f"{WATCHDOG_TIMEOUT_SECONDS}s -- exponential DotObject "
        "reconversion regression"
    )


def test_dotdict_construction_deep_nesting_is_not_exponential():
    """Regression test for exponential blowup in DotDict/DotObject construction.

    DotObject(data) recursively converts every nested dict/list value, but
    DotDict.__init__ -> __setitem__ then calls DotObject(value) again on
    values that are already converted. Each additional level of nesting
    roughly doubles the number of conversion calls, so a dict nested ~28
    levels deep triggers hundreds of millions of calls and either takes
    minutes or appears to hang.

    A SIGALRM watchdog bounds the worst case so this test cannot hang the
    test runner even on unfixed code, and a tight wall-clock assertion
    catches the exponential blowup well before it reaches a full hang.
    """
    nested_data = _build_nested_dict(DEPTH)

    previous_handler = signal.signal(signal.SIGALRM, _raise_construction_timeout)
    signal.alarm(WATCHDOG_TIMEOUT_SECONDS)
    try:
        start = time.monotonic()
        result = DotDict(nested_data)
        elapsed = time.monotonic() - start
    except _ConstructionTimeout as exc:
        pytest.fail(str(exc))
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous_handler)

    assert elapsed < MAX_ALLOWED_CONSTRUCTION_SECONDS, (
        f"DotDict construction of a {DEPTH}-level nested dict took "
        f"{elapsed:.3f}s (limit {MAX_ALLOWED_CONSTRUCTION_SECONDS}s) -- "
        "likely the exponential DotObject reconversion regression"
    )

    node = result
    for level in range(1, DEPTH + 1):
        node = node[f"level_{level}"]
    assert node["value"] == "leaf"
