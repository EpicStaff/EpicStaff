"""What the execution controller accepts and what it rejects.

Storage is fail-closed at intake: a submission that asks for storage without an org
prefix or without credentials is rejected outright, because accepting it would tell the
caller the job was taken and then fail it in the worker.

A full sandbox answers 503 with `Retry-After`, decided by a guard before the body is
read; held jobs do not fill it. A job that would be held answers 503 once the held cap
is reached. The status endpoint answers for every execution the sandbox still knows, and 404
for the rest -- that 404 is how a waiting producer learns to stop waiting.
"""

from litestar import status_codes

from manager.domain.enums import VenvStatus
from tests.builders import make_venv
from tests.manager.presentation.conftest import MAX_ACCEPTED, MAX_HELD

SUBMISSION = {
    "execution_id": "exec-1",
    "session_id": 7,
    "code": "def main():\n    return 1",
    "entrypoint": "main",
    "global_kwargs": {"LIMIT": 3},
    "func_kwargs": {"value": "x"},
    "secrets": {"TOKEN": "s3cret"},
    "use_storage": False,
    "storage_allowed_paths": [],
    "storage_org_prefix": None,
    "timeout": None,
}

CREDENTIALS = {"access_key": "AK123", "secret_key": "SK456"}


def test_submit_against_a_completed_venv_is_accepted_and_dispatched(
    client, venv_repository, dispatcher
):
    venv = venv_repository.seed(make_venv(status=VenvStatus.COMPLETED, hash="1abc"))[0]

    response = client.post("/executions", json={**SUBMISSION, "venv_id": venv.id})

    assert response.status_code == status_codes.HTTP_202_ACCEPTED
    assert response.json() == {"execution_id": "exec-1", "status": "queued"}
    assert [job.execution_id for job in dispatcher.dispatched] == ["exec-1"]
    assert dispatcher.dispatched[0].venv_hash == "1abc"


def test_submit_against_a_building_venv_is_accepted_and_held(
    client, venv_repository, dispatcher, holding
):
    venv = venv_repository.seed(make_venv(status=VenvStatus.PROCESSING))[0]

    response = client.post("/executions", json={**SUBMISSION, "venv_id": venv.id})

    assert response.status_code == status_codes.HTTP_202_ACCEPTED
    assert response.json()["status"] == "held"
    assert dispatcher.dispatched == []
    assert [job.execution_id for job in holding.release(venv.id)] == ["exec-1"]


def test_submit_without_a_venv_id_uses_the_default_venv(client, venv_repository, dispatcher):
    venv_repository.seed(make_venv(name="default", status=VenvStatus.COMPLETED, hash="1abc"))

    response = client.post("/executions", json=SUBMISSION)

    assert response.status_code == status_codes.HTTP_202_ACCEPTED
    assert dispatcher.dispatched[0].venv_hash == "1abc"


def test_submit_without_a_session_id_is_accepted(client, venv_repository, dispatcher):
    venv_repository.seed(make_venv(name="default", status=VenvStatus.COMPLETED, hash="1abc"))

    response = client.post("/executions", json={**SUBMISSION, "session_id": None})

    assert response.status_code == status_codes.HTTP_202_ACCEPTED
    assert dispatcher.dispatched[0].session_id is None


def test_submit_with_storage_carries_the_storage_fields_to_the_worker(
    client, venv_repository, dispatcher
):
    venv = venv_repository.seed(make_venv(status=VenvStatus.COMPLETED, hash="1abc"))[0]

    response = client.post(
        "/executions",
        json={
            **SUBMISSION,
            "venv_id": venv.id,
            "use_storage": True,
            "storage_allowed_paths": ["docs/"],
            "storage_org_prefix": "org1",
            "storage_credentials": CREDENTIALS,
        },
    )

    assert response.status_code == status_codes.HTTP_202_ACCEPTED
    job = dispatcher.dispatched[0]
    assert job.use_storage is True
    assert job.storage_allowed_paths == ["docs/"]
    assert job.storage_org_prefix == "org1"
    assert job.storage_credentials.access_key == "AK123"
    assert job.storage_credentials.secret_key == "SK456"


def test_submit_with_storage_but_no_credentials_is_rejected(
    client, venv_repository, dispatcher
):
    venv = venv_repository.seed(make_venv(status=VenvStatus.COMPLETED, hash="1abc"))[0]

    response = client.post(
        "/executions",
        json={
            **SUBMISSION,
            "venv_id": venv.id,
            "use_storage": True,
            "storage_org_prefix": "org1",
        },
    )

    assert response.status_code == status_codes.HTTP_400_BAD_REQUEST
    assert dispatcher.dispatched == []


def test_submit_with_blank_credentials_is_rejected(client, venv_repository, dispatcher):
    """A credentials object is always truthy, so blank keys would slip past the
    fail-closed check and fail against the object store inside the sandbox."""
    venv = venv_repository.seed(make_venv(status=VenvStatus.COMPLETED, hash="1abc"))[0]

    response = client.post(
        "/executions",
        json={
            **SUBMISSION,
            "venv_id": venv.id,
            "use_storage": True,
            "storage_org_prefix": "org1",
            "storage_credentials": {"access_key": "", "secret_key": ""},
        },
    )

    assert response.status_code == status_codes.HTTP_400_BAD_REQUEST
    assert dispatcher.dispatched == []


def test_submit_with_storage_but_no_org_prefix_is_rejected(client, venv_repository, dispatcher):
    venv = venv_repository.seed(make_venv(status=VenvStatus.COMPLETED, hash="1abc"))[0]

    response = client.post(
        "/executions",
        json={
            **SUBMISSION,
            "venv_id": venv.id,
            "use_storage": True,
            "storage_credentials": CREDENTIALS,
        },
    )

    assert response.status_code == status_codes.HTTP_400_BAD_REQUEST
    assert dispatcher.dispatched == []


def test_submit_without_storage_needs_no_credentials(client, venv_repository, dispatcher):
    venv = venv_repository.seed(make_venv(status=VenvStatus.COMPLETED, hash="1abc"))[0]

    response = client.post("/executions", json={**SUBMISSION, "venv_id": venv.id})

    assert response.status_code == status_codes.HTTP_202_ACCEPTED
    assert dispatcher.dispatched[0].storage_credentials is None


def test_submit_asking_for_the_crew_channel_marks_the_job(client, venv_repository, dispatcher):
    venv = venv_repository.seed(make_venv(status=VenvStatus.COMPLETED, hash="1abc"))[0]

    response = client.post(
        "/executions",
        json={**SUBMISSION, "venv_id": venv.id, "reply_to_crew_channel": True},
    )

    assert response.status_code == status_codes.HTTP_202_ACCEPTED
    assert dispatcher.dispatched[0].reply_to_crew_channel is True


def test_submit_defaults_to_the_shared_result_channel(client, venv_repository, dispatcher):
    venv = venv_repository.seed(make_venv(status=VenvStatus.COMPLETED, hash="1abc"))[0]

    response = client.post("/executions", json={**SUBMISSION, "venv_id": venv.id})

    assert response.status_code == status_codes.HTTP_202_ACCEPTED
    assert dispatcher.dispatched[0].reply_to_crew_channel is False


def fill_to_the_cap(registry) -> None:
    for index in range(MAX_ACCEPTED):
        registry.reserve(f"other-{index}")


def fill_the_held_cap(registry) -> None:
    for index in range(MAX_HELD):
        registry.reserve(f"held-{index}")
        registry.mark_held(f"held-{index}")


def test_resubmitting_an_accepted_id_answers_202_without_a_second_run(
    client, venv_repository, dispatcher
):
    venv = venv_repository.seed(make_venv(status=VenvStatus.COMPLETED, hash="1abc"))[0]
    client.post("/executions", json={**SUBMISSION, "venv_id": venv.id})

    response = client.post("/executions", json={**SUBMISSION, "venv_id": venv.id})

    assert response.status_code == status_codes.HTTP_202_ACCEPTED
    assert response.json() == {"execution_id": "exec-1", "status": "queued"}
    assert [job.execution_id for job in dispatcher.dispatched] == ["exec-1"]


def test_resubmitting_an_id_still_being_admitted_answers_503_retry_after_1(
    client, registry, venv_repository, dispatcher
):
    venv = venv_repository.seed(make_venv(status=VenvStatus.COMPLETED, hash="1abc"))[0]
    # The first request for the id is still resolving its venv.
    registry.reserve("exec-1")

    response = client.post("/executions", json={**SUBMISSION, "venv_id": venv.id})

    assert response.status_code == status_codes.HTTP_503_SERVICE_UNAVAILABLE
    assert response.headers["Retry-After"] == "1"
    assert dispatcher.dispatched == []


def test_the_status_of_an_id_still_being_admitted_is_queued(client, registry):
    registry.reserve("exec-1")

    response = client.get("/executions/exec-1")

    assert response.status_code == status_codes.HTTP_200_OK
    assert response.json() == {"execution_id": "exec-1", "status": "queued"}


def test_the_status_of_an_accepted_execution_is_returned(client, venv_repository):
    venv = venv_repository.seed(make_venv(status=VenvStatus.COMPLETED, hash="1abc"))[0]
    client.post("/executions", json={**SUBMISSION, "venv_id": venv.id})

    response = client.get("/executions/exec-1")

    assert response.status_code == status_codes.HTTP_200_OK
    assert response.json() == {"execution_id": "exec-1", "status": "queued"}


def test_the_status_of_a_finished_execution_is_done(client, registry):
    registry.reserve("exec-1")
    registry.finish("exec-1", ran=True)

    response = client.get("/executions/exec-1")

    assert response.status_code == status_codes.HTTP_200_OK
    assert response.json()["status"] == "done"


def test_the_status_of_an_unknown_execution_is_not_found(client):
    response = client.get("/executions/exec-404")

    assert response.status_code == status_codes.HTTP_404_NOT_FOUND
    assert [error["code"] for error in response.json()["errors"]] == ["not_found"]


def test_a_full_sandbox_answers_503_with_retry_after(
    client, venv_repository, dispatcher, registry
):
    venv = venv_repository.seed(make_venv(status=VenvStatus.COMPLETED, hash="1abc"))[0]
    fill_to_the_cap(registry)

    response = client.post("/executions", json={**SUBMISSION, "venv_id": venv.id})

    assert response.status_code == status_codes.HTTP_503_SERVICE_UNAVAILABLE
    assert response.headers["Retry-After"] == "5"
    assert [error["code"] for error in response.json()["errors"]] == ["overloaded"]
    assert dispatcher.dispatched == []
    assert registry.status("exec-1") is None


def test_a_full_sandbox_answers_503_before_reading_a_malformed_body(client, registry):
    """The guard runs before the body is decoded, so a caller is told to come back
    later rather than handed a 400 for a body the sandbox never needed to read."""
    fill_to_the_cap(registry)

    response = client.post(
        "/executions", content=b"{not json", headers={"Content-Type": "application/json"}
    )

    assert response.status_code == status_codes.HTTP_503_SERVICE_UNAVAILABLE
    assert response.headers["Retry-After"] == "5"


def test_a_submission_that_would_be_held_answers_503_at_the_held_cap(
    client, venv_repository, holding, registry
):
    venv = venv_repository.seed(make_venv(status=VenvStatus.PROCESSING))[0]
    fill_the_held_cap(registry)

    response = client.post("/executions", json={**SUBMISSION, "venv_id": venv.id})

    assert response.status_code == status_codes.HTTP_503_SERVICE_UNAVAILABLE
    assert response.headers["Retry-After"] == "30"
    assert [error["code"] for error in response.json()["errors"]] == ["overloaded"]
    assert holding.pending_venv_ids() == []
    assert registry.status("exec-1") is None


def test_as_many_held_jobs_as_the_in_flight_cap_do_not_turn_away_a_job_to_run(
    client, venv_repository, dispatcher, registry
):
    """One tenant's venv stuck building must not lock every other org out."""
    venv = venv_repository.seed(make_venv(status=VenvStatus.COMPLETED, hash="1abc"))[0]
    for index in range(MAX_ACCEPTED):
        registry.reserve(f"held-{index}")
        registry.mark_held(f"held-{index}")

    response = client.post("/executions", json={**SUBMISSION, "venv_id": venv.id})

    assert response.status_code == status_codes.HTTP_202_ACCEPTED
    assert [job.execution_id for job in dispatcher.dispatched] == ["exec-1"]


def test_a_malformed_body_below_the_cap_is_still_a_400(client):
    response = client.post(
        "/executions", content=b"{not json", headers={"Content-Type": "application/json"}
    )

    assert response.status_code == status_codes.HTTP_400_BAD_REQUEST
