"""Success responses of the execution controller.

Each request carries ``session_id``: the submit schema makes it optional but the domain
``Job`` requires it, so a submission without one is rejected today. That mismatch is a
known defect and is out of scope for a success-only suite.
"""

from litestar import status_codes

from manager.domain.enums import VenvStatus
from tests.builders import make_venv

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


def test_submit_against_a_completed_venv_is_accepted_and_dispatched(
    client, venv_repository, dispatcher
):
    venv = venv_repository.seed(make_venv(status=VenvStatus.COMPLETED, hash="1abc"))[0]

    response = client.post("/executions", json={**SUBMISSION, "venv_id": venv.id})

    assert response.status_code == status_codes.HTTP_202_ACCEPTED
    assert response.json() == {"execution_id": "exec-1", "status": "accepted"}
    assert [job.execution_id for job in dispatcher.dispatched] == ["exec-1"]
    assert dispatcher.dispatched[0].venv_hash == "1abc"


def test_submit_against_a_building_venv_is_accepted_and_held(
    client, venv_repository, dispatcher, holding
):
    venv = venv_repository.seed(make_venv(status=VenvStatus.PROCESSING))[0]

    response = client.post("/executions", json={**SUBMISSION, "venv_id": venv.id})

    assert response.status_code == status_codes.HTTP_202_ACCEPTED
    assert dispatcher.dispatched == []
    assert [job.execution_id for job in holding.release(venv.id)] == ["exec-1"]


def test_submit_without_a_venv_id_uses_the_default_venv(client, venv_repository, dispatcher):
    venv_repository.seed(make_venv(name="default", status=VenvStatus.COMPLETED, hash="1abc"))

    response = client.post("/executions", json=SUBMISSION)

    assert response.status_code == status_codes.HTTP_202_ACCEPTED
    assert dispatcher.dispatched[0].venv_hash == "1abc"


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
        },
    )

    assert response.status_code == status_codes.HTTP_202_ACCEPTED
    job = dispatcher.dispatched[0]
    assert job.use_storage is True
    assert job.storage_allowed_paths == ["docs/"]
    assert job.storage_org_prefix == "org1"
