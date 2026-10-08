"""N parallel runs of flow A: every one must end with its own correct sum.

One graph is shared by all runs: concurrent sessions of the same flow are the realistic case
and the one most likely to expose shared state between sessions. Inputs differ per run, so a
result can never be mistaken for another run's.

Known failure: parallel runs that need a sandbox venv that does not exist yet all build it
in the same directory at once and corrupt each other's pip install, so most runs end in
`error`. The test stays red until the sandbox serializes venv creation.

Timing is reported and warned about, never failed on; correctness and the hard budget are.
"""

import math
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime

import pytest

from helpers.api import ApiClient
from helpers.bootstrap import unique_suffix
from helpers.flows import CreatedFlow, create_python_flow, start_session
from helpers.polling import session_diagnostics, wait_for_session_status
from helpers.redaction import scrub
from helpers.timings import Timings

pytestmark = pytest.mark.load

PARALLEL_RUNS = 10
RUN_TIMEOUT_SECONDS = 420
# Above this p95 the run is reported as slow (a warning, not a failure).
SLOW_P95_SECONDS = 180
REASON_LENGTH = 200


@dataclass(frozen=True)
class ParallelRun:
    first_addend: int
    second_addend: int
    session_id: int | None
    # A session status, or `start_failed` / `timeout` when the client gave up first.
    status: str
    reason: str
    session: dict

    @property
    def expected_result(self) -> dict:
        return {"sum": self.first_addend + self.second_addend}

    @property
    def result(self) -> object:
        return (self.session.get("status_data") or {}).get("variables", {}).get("result")

    @property
    def server_seconds(self) -> float:
        created = datetime.fromisoformat(self.session["created_at"])
        finished = datetime.fromisoformat(self.session["finished_at"])
        return (finished - created).total_seconds()

    def describe(self) -> str:
        return (
            f"session {self.session_id} a={self.first_addend} b={self.second_addend} "
            f"status={self.status!r} reason={self.reason[:REASON_LENGTH]!r}"
        )


def nearest_rank_percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(percentile / 100 * len(ordered)) - 1)]


def failure_reason(session: dict) -> str:
    """The last line of the session's error: for a traceback, the exception itself."""
    status_data = session.get("status_data") or {}
    text = str(status_data.get("error") or status_data.get("reason") or "").strip()
    return scrub(text.splitlines()[-1] if text else "")


@pytest.fixture(scope="module")
def concurrency_flow(user_client: ApiClient) -> CreatedFlow:
    return create_python_flow(user_client, f"e2e-concurrency-{unique_suffix()}")


@pytest.fixture(scope="module")
def parallel_runs(
    user_client: ApiClient, concurrency_flow: CreatedFlow, timings: Timings
) -> list[ParallelRun]:
    """Start every run at once and wait for all; never raises, so every run is reported."""

    def run_one(index: int) -> ParallelRun:
        first_addend, second_addend = index, 100 + index
        try:
            session_id = start_session(
                user_client,
                concurrency_flow.graph_id,
                {"a": first_addend, "b": second_addend},
            )["session_id"]
        except AssertionError as error:
            return ParallelRun(first_addend, second_addend, None, "start_failed", str(error), {})
        try:
            status = wait_for_session_status(user_client, session_id, RUN_TIMEOUT_SECONDS)
        except AssertionError as error:
            return ParallelRun(first_addend, second_addend, session_id, "timeout", str(error), {})
        session = user_client.get(f"/api/sessions/{session_id}/").json()
        return ParallelRun(
            first_addend, second_addend, session_id, status, failure_reason(session), session
        )

    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=PARALLEL_RUNS) as executor:
        runs = list(executor.map(run_one, range(PARALLEL_RUNS)))
    timings.record("concurrency_wall_seconds", time.monotonic() - started)

    durations = [run.server_seconds for run in runs if run.status == "end"]
    if durations:
        p50 = nearest_rank_percentile(durations, 50)
        p95 = nearest_rank_percentile(durations, 95)
        timings.record("concurrency_run_p50_seconds", p50)
        timings.record("concurrency_run_p95_seconds", p95)
        if p95 > SLOW_P95_SECONDS:
            warnings.warn(f"slow parallel runs: p95 {p95:.1f}s over {SLOW_P95_SECONDS}s", stacklevel=1)
    return runs


def test_every_parallel_run_ends(user_client: ApiClient, parallel_runs: list[ParallelRun]) -> None:
    failed = [run for run in parallel_runs if run.status != "end"]
    if not failed:
        return
    lines = [f"{len(failed)} of {len(parallel_runs)} parallel runs did not end:"]
    lines.extend(run.describe() for run in failed)
    first_with_session = next((run for run in failed if run.session_id is not None), None)
    if first_with_session is not None:
        lines.append(session_diagnostics(user_client, first_with_session.session_id))
    pytest.fail("\n".join(lines), pytrace=False)


def test_every_parallel_run_has_its_own_sum(parallel_runs: list[ParallelRun]) -> None:
    wrong = [
        f"session {run.session_id}: expected {run.expected_result}, got {run.result!r}"
        for run in parallel_runs
        if run.status == "end" and run.result != run.expected_result
    ]
    assert not wrong, "\n".join(wrong)
