"""N parallel runs of flow A: every one must end with its own correct sum.

One graph is shared by all runs: concurrent sessions of the same flow are the realistic case
and the one most likely to expose shared state between sessions. Inputs differ per run, so a
result can never be mistaken for another run's.

Each python run currently rebuilds its sandbox venv (~33 s alone), so ten runs rebuild ten
venvs in parallel. Timing is reported and warned about, never failed on; correctness and the
hard budget are.
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
from helpers.timings import Timings

pytestmark = pytest.mark.load

PARALLEL_RUNS = 10
RUN_TIMEOUT_SECONDS = 420
# Above this p95 the run is reported as slow (a warning, not a failure).
SLOW_P95_SECONDS = 180


@dataclass(frozen=True)
class ParallelRun:
    a: int
    b: int
    session_id: int
    status: str
    session: dict

    @property
    def server_seconds(self) -> float:
        created = datetime.fromisoformat(self.session["created_at"])
        finished = datetime.fromisoformat(self.session["finished_at"])
        return (finished - created).total_seconds()


def nearest_rank_percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(percentile / 100 * len(ordered)) - 1)]


@pytest.fixture(scope="module")
def concurrency_flow(user_client: ApiClient) -> CreatedFlow:
    return create_python_flow(user_client, f"e2e-concurrency-{unique_suffix()}")


@pytest.fixture(scope="module")
def parallel_runs(
    user_client: ApiClient, concurrency_flow: CreatedFlow, timings: Timings
) -> list[ParallelRun]:
    def run_one(index: int) -> ParallelRun:
        a, b = index, 100 + index
        session_id = start_session(user_client, concurrency_flow.graph_id, {"a": a, "b": b})[
            "session_id"
        ]
        status = wait_for_session_status(user_client, session_id, RUN_TIMEOUT_SECONDS)
        session = user_client.get(f"/api/sessions/{session_id}/").json()
        return ParallelRun(a, b, session_id, status, session)

    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=PARALLEL_RUNS) as executor:
        runs = list(executor.map(run_one, range(PARALLEL_RUNS)))
    timings.record("concurrency_wall_seconds", time.monotonic() - started)

    ended = [run for run in runs if run.status == "end"]
    if ended:
        durations = [run.server_seconds for run in ended]
        p50 = nearest_rank_percentile(durations, 50)
        p95 = nearest_rank_percentile(durations, 95)
        timings.record("concurrency_run_p50_seconds", p50)
        timings.record("concurrency_run_p95_seconds", p95)
        if p95 > SLOW_P95_SECONDS:
            warnings.warn(
                f"slow parallel runs: p95 {p95:.1f}s over {SLOW_P95_SECONDS}s", stacklevel=1
            )
    return runs


def test_every_parallel_run_ends(user_client: ApiClient, parallel_runs: list[ParallelRun]) -> None:
    failed = [run for run in parallel_runs if run.status != "end"]
    assert not failed, "\n".join(
        f"run a={run.a} b={run.b} ended {run.status!r}\n"
        f"{session_diagnostics(user_client, run.session_id)}"
        for run in failed
    )


def test_every_parallel_run_has_its_own_sum(parallel_runs: list[ParallelRun]) -> None:
    assert any(run.status == "end" for run in parallel_runs), "no parallel run ended"
    wrong = {
        run.session_id: run.session["status_data"].get("variables", {}).get("result")
        for run in parallel_runs
        if run.status == "end"
        and run.session["status_data"].get("variables", {}).get("result") != {"sum": run.a + run.b}
    }
    assert not wrong, wrong
    assert len({run.session_id for run in parallel_runs}) == PARALLEL_RUNS
