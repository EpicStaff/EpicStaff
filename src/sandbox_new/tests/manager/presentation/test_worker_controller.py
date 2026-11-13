"""The internal seam the worker drives: pull a job, push a result, heartbeat.

Every route refuses anything without the internal bearer token -- a pull hands out job
payloads with plaintext secrets -- and carries the worker run's boot id. A pull settles
the past: jobs assigned under another boot id are failed with the fixed worker-lost text
before new work is handed out, a superseded boot id is never handed a job, and a pushed
result is accepted only for a job that is still assigned -- late and duplicate results
are dropped, never published twice.
"""

import asyncio

import pytest
from common.contracts import ExecutionJobMessage
from litestar import status_codes

from manager.presentation.rest.worker_controller import WorkerController

from manager.application.worker_loss import WORKER_LOST_MESSAGE
from manager.presentation.rest import worker_controller

AUTH = {"Authorization": "Bearer internal-test-token"}
PULL_HEADERS = {**AUTH, "X-Worker-Boot-Id": "boot-1"}

JOB = ExecutionJobMessage(
    execution_id="exec-1",
    venv_hash="1abc",
    code="def main():\n    return 1",
    entrypoint="main",
    session_id=7,
    reply_to_crew_channel=True,
    timeout=10.0,
)


@pytest.fixture(autouse=True)
def quick_poll(monkeypatch):
    """Keep an empty long-poll from stalling the suite for its real 25 s."""
    monkeypatch.setattr(worker_controller, "LONG_POLL_SECONDS", 0.05)


def test_a_pull_without_the_token_is_refused(client, job_queue):
    job_queue.put_nowait(JOB)

    response = client.get("/worker/jobs", headers={"X-Worker-Boot-Id": "boot-1"})

    assert response.status_code == status_codes.HTTP_401_UNAUTHORIZED
    assert job_queue.qsize() == 1


def test_a_pull_with_a_wrong_token_is_refused(client, job_queue):
    job_queue.put_nowait(JOB)

    response = client.get(
        "/worker/jobs",
        headers={"Authorization": "Bearer wrong", "X-Worker-Boot-Id": "boot-1"},
    )

    assert response.status_code == status_codes.HTTP_401_UNAUTHORIZED
    assert job_queue.qsize() == 1


def test_a_pull_from_an_empty_queue_answers_204(client):
    response = client.get("/worker/jobs", headers=PULL_HEADERS)

    assert response.status_code == status_codes.HTTP_204_NO_CONTENT


def test_a_queued_job_is_handed_out_once_and_assigned(client, job_queue, registry):
    registry.reserve("exec-1")
    registry.mark_queued("exec-1")
    job_queue.put_nowait(JOB)

    response = client.get("/worker/jobs", headers=PULL_HEADERS)

    assert response.status_code == status_codes.HTTP_200_OK
    assert response.json()["execution_id"] == "exec-1"
    assert response.json()["secrets"] == {}
    assert job_queue.qsize() == 0
    # Assigned to boot-1: a pull from another boot id releases it, with its routing hints.
    assert registry.release_assignments_not_from("boot-2") == [("exec-1", 7, True)]


def test_a_pull_under_a_new_boot_id_fails_the_old_runs_jobs(client, registry, failure_sink):
    registry.reserve("exec-old")
    registry.mark_queued("exec-old")
    registry.mark_assigned(
        "exec-old", boot_id="boot-0", session_id=5, reply_to_crew_channel=True
    )

    response = client.get("/worker/jobs", headers=PULL_HEADERS)

    assert response.status_code == status_codes.HTTP_204_NO_CONTENT
    failure = failure_sink.failures[0]
    assert failure.execution_id == "exec-old"
    assert failure.message == WORKER_LOST_MESSAGE
    assert failure.session_id == 5
    assert failure.not_run_reason == "worker_lost"
    assert failure.reply_to_crew_channel is True


def test_a_pull_under_the_same_boot_id_fails_nothing(client, registry, failure_sink):
    registry.reserve("exec-1")
    registry.mark_queued("exec-1")
    registry.mark_assigned("exec-1", boot_id="boot-1")

    response = client.get("/worker/jobs", headers=PULL_HEADERS)

    assert response.status_code == status_codes.HTTP_204_NO_CONTENT
    assert failure_sink.failures == []


def test_a_stale_boot_id_is_never_handed_a_job(client, job_queue):
    client.get("/worker/jobs", headers=PULL_HEADERS)
    client.get("/worker/jobs", headers={**AUTH, "X-Worker-Boot-Id": "boot-2"})
    job_queue.put_nowait(JOB)

    response = client.get("/worker/jobs", headers=PULL_HEADERS)

    assert response.status_code == status_codes.HTTP_204_NO_CONTENT
    assert job_queue.qsize() == 1


def test_a_pull_without_the_boot_id_header_is_a_400(client, job_queue):
    job_queue.put_nowait(JOB)

    response = client.get("/worker/jobs", headers=AUTH)

    assert response.status_code == status_codes.HTTP_400_BAD_REQUEST
    assert job_queue.qsize() == 1


def test_a_pushed_result_settles_the_assignment_and_lands_on_the_result_queue(
    client, result_queue, registry
):
    registry.reserve("exec-1")
    registry.mark_queued("exec-1")
    registry.mark_assigned("exec-1", boot_id="boot-1")

    response = client.post(
        "/worker/results",
        json={"execution_id": "exec-1", "stdout": "ok", "ran": True},
        headers=PULL_HEADERS,
    )

    assert response.status_code == status_codes.HTTP_202_ACCEPTED
    result = result_queue.get_nowait()
    assert result.execution_id == "exec-1"
    assert result.ran is True
    # Settled: a later boot change has nothing of this job to fail.
    assert registry.release_assignments_not_from("boot-2") == []


def test_a_result_for_an_unassigned_execution_is_dropped(client, result_queue):
    response = client.post(
        "/worker/results",
        json={"execution_id": "exec-late", "stdout": "ok", "ran": True},
        headers=PULL_HEADERS,
    )

    assert response.status_code == status_codes.HTTP_202_ACCEPTED
    assert result_queue.qsize() == 0


def test_a_duplicate_result_is_dropped(client, result_queue, registry):
    registry.reserve("exec-1")
    registry.mark_queued("exec-1")
    registry.mark_assigned("exec-1", boot_id="boot-1")
    body = {"execution_id": "exec-1", "stdout": "ok", "ran": True}
    client.post("/worker/results", json=body, headers=PULL_HEADERS)

    client.post("/worker/results", json=body, headers=PULL_HEADERS)

    assert result_queue.qsize() == 1


def test_a_push_without_the_token_is_refused(client, result_queue):
    response = client.post(
        "/worker/results",
        json={"execution_id": "exec-1"},
        headers={"X-Worker-Boot-Id": "boot-1"},
    )

    assert response.status_code == status_codes.HTTP_401_UNAUTHORIZED
    assert result_queue.qsize() == 0


def test_a_heartbeat_without_the_token_is_refused(client):
    response = client.post("/worker/heartbeat", headers={"X-Worker-Boot-Id": "boot-1"})

    assert response.status_code == status_codes.HTTP_401_UNAUTHORIZED


def test_a_heartbeat_reporting_the_job_keeps_it_alive(client, registry, worker_contact, clock):
    registry.reserve("exec-1")
    registry.mark_queued("exec-1")
    registry.mark_assigned("exec-1", boot_id="boot-1")
    clock.advance(61.0)

    response = client.post(
        "/worker/heartbeat", json={"execution_ids": ["exec-1"]}, headers=PULL_HEADERS
    )

    assert response.status_code == status_codes.HTTP_204_NO_CONTENT
    assert worker_contact.boot_is_silent("boot-1", 60.0) is False


def test_a_heartbeat_missing_an_old_assignment_fails_it_as_lost(
    client, registry, clock, failure_sink
):
    """The pull response never reached the worker: the run keeps beating, so only its
    own report can reveal the job it never received."""
    registry.reserve("exec-lost")
    registry.mark_queued("exec-lost")
    registry.mark_assigned("exec-lost", boot_id="boot-1", session_id=5, reply_to_crew_channel=True)
    clock.advance(31.0)

    client.post("/worker/heartbeat", json={"execution_ids": []}, headers=PULL_HEADERS)
    assert failure_sink.failures == []  # one missed report is forgiven
    response = client.post(
        "/worker/heartbeat", json={"execution_ids": []}, headers=PULL_HEADERS
    )

    assert response.status_code == status_codes.HTTP_204_NO_CONTENT
    failure = failure_sink.failures[0]
    assert failure.execution_id == "exec-lost"
    assert failure.message == WORKER_LOST_MESSAGE
    assert failure.session_id == 5
    assert failure.not_run_reason == "worker_lost"
    assert failure.reply_to_crew_channel is True


def test_a_heartbeat_missing_a_fresh_assignment_spares_it(client, registry, failure_sink):
    """A hand-off still in flight is not yet lost: the worker simply has not received
    the job it will report on its next beat."""
    registry.reserve("exec-new")
    registry.mark_queued("exec-new")
    registry.mark_assigned("exec-new", boot_id="boot-1")

    client.post("/worker/heartbeat", json={"execution_ids": []}, headers=PULL_HEADERS)

    assert failure_sink.failures == []
    assert registry.settle_assignment("exec-new") is True


def test_a_heartbeat_does_not_touch_other_boots_assignments(client, registry, clock, failure_sink):
    registry.reserve("exec-other")
    registry.mark_queued("exec-other")
    registry.mark_assigned("exec-other", boot_id="boot-9")
    clock.advance(31.0)

    client.post("/worker/heartbeat", json={"execution_ids": []}, headers=PULL_HEADERS)

    assert failure_sink.failures == []


async def wait_until(check, *, timeout: float = 1.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if check():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("the expected state never arrived")


def call_pull(registry, worker_contact, job_queue, failure_sink, boot_id: str):
    """Invoke the pull handler directly: the test client serializes requests through a
    blocking portal, so overlapping a parked long-poll with observations needs the bare
    coroutine. Auth, DI and routing are pinned by the HTTP tests above."""
    handler = WorkerController.pull_job.fn
    controller = object.__new__(WorkerController)
    return handler(
        controller,
        execution_registry=registry,
        worker_contact=worker_contact,
        job_queue=job_queue,
        job_failure_sink=failure_sink,
        boot_id=boot_id,
    )


async def test_a_waiting_pull_counts_as_a_free_slot(
    registry, worker_contact, job_queue, failure_sink, monkeypatch
):
    """The intake's free-slot probe: a long-poll parked on the queue is a worker slot
    waiting for work, and it stops counting the moment the poll ends."""
    monkeypatch.setattr(worker_controller, "LONG_POLL_SECONDS", 1.0)
    pull = asyncio.create_task(
        call_pull(registry, worker_contact, job_queue, failure_sink, "boot-1")
    )
    await wait_until(lambda: worker_contact.waiting_pollers == 1)

    job_queue.put_nowait(JOB)
    response = await pull

    assert response.status_code == status_codes.HTTP_200_OK
    assert worker_contact.waiting_pollers == 0


async def test_a_boot_superseded_while_waiting_is_not_handed_the_job(
    registry, worker_contact, job_queue, failure_sink, monkeypatch
):
    """The zombie window: boot-1's poll is already parked when boot-2 takes over, so the
    job boot-1 grabs goes back to the queue instead of being assigned to a dead run."""
    monkeypatch.setattr(worker_controller, "LONG_POLL_SECONDS", 1.0)
    pull = asyncio.create_task(
        call_pull(registry, worker_contact, job_queue, failure_sink, "boot-1")
    )
    await wait_until(lambda: worker_contact.waiting_pollers == 1)

    assert worker_contact.accept_boot("boot-2") is True
    job_queue.put_nowait(JOB)
    response = await pull

    assert response.status_code == status_codes.HTTP_204_NO_CONTENT
    assert job_queue.qsize() == 1
    assert registry.release_assignments_not_from("boot-2") == []
async def test_an_empty_poll_timeout_releases_the_waiting_slot(
    registry, worker_contact, job_queue, failure_sink, monkeypatch
):
    monkeypatch.setattr(worker_controller, "LONG_POLL_SECONDS", 0.02)

    response = await call_pull(registry, worker_contact, job_queue, failure_sink, "boot-1")

    assert response.status_code == status_codes.HTTP_204_NO_CONTENT
    assert worker_contact.waiting_pollers == 0
