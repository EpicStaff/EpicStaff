"""A helper running as a plugin's UID can be stopped by the plugin; the launcher never waits on it
past its deadline, and the next kill of the UID ends it."""

import contextlib
import os
import signal
import time
from pathlib import Path

import pytest

from es_plugins.launcher.kill_by_uid import SIGNALLER_UID, check_signaller_uid, kill_uid, run_as_user
from es_plugins.launcher.process_spawn import SpawnSpec, spawn_process
from es_plugins.process_table import ProcessTable
from es_plugins.uid_range import UidRange
from tests.helpers import SYSTEM_PYTHON

PLUGIN_UID = 20041
# Stops every other process of its UID it may signal, over and over.
STOPPER = """
import os, signal
while True:
    try:
        os.kill(-1, signal.SIGSTOP)
    except ProcessLookupError:
        pass
"""


@contextlib.contextmanager
def interrupted_after(seconds: float):
    """Turn a wait that never returns into a failure: the suite has no timeout plugin."""

    def give_up(signal_number, frame):
        raise TimeoutError(f"still waiting after {seconds} s")

    previous = signal.signal(signal.SIGALRM, give_up)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def reap_children() -> None:
    with contextlib.suppress(ChildProcessError):
        while os.waitpid(-1, os.WNOHANG)[0]:
            pass


def kill_everything_of_the_uid() -> tuple[int, ...] | None:
    """Kill the UID's processes as the launcher does; return what survived, None if the kill hung.

    A clean-up step: it never raises, so a test's own failure is the one reported.
    """
    try:
        with interrupted_after(15):
            outcome = kill_uid(PLUGIN_UID, ProcessTable(), reap=reap_children)
    except TimeoutError:
        return None
    reap_children()
    return outcome.remaining


def spawn_stoppers(count: int) -> list[int]:
    return [
        spawn_process(
            SpawnSpec(
                uid=PLUGIN_UID,
                gid=PLUGIN_UID,
                argv=[SYSTEM_PYTHON, "-I", "-c", STOPPER],
                environment={},
                working_directory=Path("/"),
            )
        )
        for _ in range(count)
    ]


@pytest.mark.root
def test_a_helper_the_plugin_stops_is_given_up_at_once_and_the_next_kill_ends_it():
    started = time.monotonic()
    with interrupted_after(10):
        finished = run_as_user(PLUGIN_UID, lambda: os.kill(os.getpid(), signal.SIGSTOP), timeout_seconds=5)
    waited = time.monotonic() - started
    stopped = ProcessTable().living_pids_of_uid(PLUGIN_UID)

    with interrupted_after(20):
        outcome = kill_uid(PLUGIN_UID, ProcessTable())
        statuses = [os.waitstatus_to_exitcode(os.waitpid(pid, 0)[1]) for pid in stopped]

    assert not finished
    assert waited < 1
    assert len(stopped) == 1
    assert outcome.remaining == ()
    assert statuses == [-signal.SIGKILL]


@pytest.mark.root
def test_a_helper_still_running_at_its_deadline_is_given_up():
    started = time.monotonic()
    try:
        with interrupted_after(10):
            finished = run_as_user(PLUGIN_UID, lambda: time.sleep(30), timeout_seconds=0.5)
        waited = time.monotonic() - started
    finally:
        left = kill_everything_of_the_uid()

    assert not finished
    assert 0.5 <= waited < 2
    assert left == ()


@pytest.mark.root
def test_plugin_processes_that_stop_every_process_of_their_uid_are_killed_in_one_round():
    outcomes = []
    for _ in range(3):
        stoppers = spawn_stoppers(4)
        try:
            time.sleep(0.3)
            with interrupted_after(20):
                outcomes.append(kill_uid(PLUGIN_UID, ProcessTable(), reap=reap_children, timeout_seconds=3))
        finally:
            left = kill_everything_of_the_uid()
        assert left == (), f"stoppers {stoppers} outlived the clean-up"

    # The signalling helper is not theirs to stop: its first kill(-1, SIGKILL) always goes out.
    assert [(outcome.rounds, outcome.remaining) for outcome in outcomes] == [(1, ())] * 3


def test_the_signalling_uid_is_never_a_plugins_and_a_range_holding_it_is_refused():
    check_signaller_uid(UidRange(UidRange.MINIMUM_FIRST, UidRange.MAXIMUM_LAST))

    with pytest.raises(ValueError, match="must be outside PLUGINS_NODE_UID_RANGE"):
        check_signaller_uid(UidRange(SIGNALLER_UID - 5, SIGNALLER_UID + 5))
