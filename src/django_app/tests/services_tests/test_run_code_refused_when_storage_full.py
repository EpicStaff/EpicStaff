"""A code test run that needs storage is refused while its organization is over its quota.

POST /api/run-python-code/ answers 409 `organization_storage_full` for code that would get
storage credentials, whether the code is named by id or by a node target. A refused run
leaves nothing behind: its pending result is deleted, nothing reaches the sandbox, and none
of the organization's older results is evicted to make room for it. Code that needs no
storage is not affected by the quota. An admitted run still evicts the oldest results past
the per-organization limit.

Real view, service and credential service; the sandbox (`sandbox_intake`) and the storage
backend's admin API (FakeStorageGateway) are the external boundaries.
"""

import pytest

from tables.models import Graph, PythonCode, PythonCodeResult, PythonCodeTool, PythonNode, StorageFile
from tables.services import run_python_code_service
from tests.services_tests.test_run_code_storage_credentials import gateway  # noqa: F401

pytestmark = pytest.mark.django_db

URL = "/api/run-python-code/"
QUOTA = 1000
KEPT_RESULTS = 2


@pytest.fixture(autouse=True)
def small_limits(settings, monkeypatch):
    settings.ORG_STORAGE_QUOTA = QUOTA
    monkeypatch.setattr(run_python_code_service, "MAX_STORED_RESULTS", KEPT_RESULTS)


@pytest.fixture
def older_results(default_org):
    return [
        PythonCodeResult.objects.create(execution_id=f"older-{index}", org=default_org)
        for index in range(KEPT_RESULTS)
    ]


@pytest.fixture
def flow(default_org):
    return Graph.objects.create(name="storage-full-flow", org=default_org)


def _fill_storage(org, size: int) -> None:
    StorageFile.objects.create(org=org, path="full.bin", name="full.bin", item_type="file", size=size)


def _code_tool(org, *, use_storage: bool) -> PythonCode:
    python_code = PythonCode.objects.create(code="def main(**kw): return kw", entrypoint="main")
    PythonCodeTool.objects.create(python_code=python_code, org_id=org.id, use_storage=use_storage)
    return python_code


def _run_by_id(client, python_code):
    return client.post(URL, {"python_code_id": python_code.pk, "variables": {}}, format="json")


def _run_node(client, flow):
    python_code = PythonCode.objects.create(code="def main(): return 1", entrypoint="main")
    node = PythonNode.objects.create(graph=flow, python_code=python_code, use_storage=True)
    return client.post(
        URL, {"target": {"type": "python_node", "id": node.pk}, "variables": {}}, format="json"
    )


def _assert_storage_full(response) -> None:
    assert response.status_code == 409, response.content
    body = response.json()
    assert (body["status_code"], body["code"]) == (409, "organization_storage_full")


@pytest.mark.parametrize("named_by", ["python_code_id", "target"])
def test_a_storage_run_over_quota_is_refused_and_leaves_every_result_in_place(
    gateway, default_org, auth_client, sandbox_intake, older_results, flow, named_by  # noqa: F811
):
    _fill_storage(default_org, QUOTA + 1)

    if named_by == "python_code_id":
        response = _run_by_id(auth_client, _code_tool(default_org, use_storage=True))
    else:
        response = _run_node(auth_client, flow)

    _assert_storage_full(response)
    assert sorted(PythonCodeResult.objects.values_list("execution_id", flat=True)) == [
        "older-0",
        "older-1",
    ]
    assert sandbox_intake.bodies == []
    assert gateway.created == []


def test_code_without_storage_runs_over_quota(
    gateway, default_org, auth_client, sandbox_intake  # noqa: F811
):
    _fill_storage(default_org, QUOTA + 1)

    response = _run_by_id(auth_client, _code_tool(default_org, use_storage=False))

    assert response.status_code == 200, response.content
    (task,) = sandbox_intake.bodies
    assert task["execution_id"] == response.json()["execution_id"]
    assert gateway.created == []


def test_an_admitted_storage_run_evicts_the_oldest_result_past_the_limit(
    gateway, default_org, auth_client, sandbox_intake, older_results  # noqa: F811
):
    _fill_storage(default_org, QUOTA)

    response = _run_by_id(auth_client, _code_tool(default_org, use_storage=True))

    assert response.status_code == 200, response.content
    execution_id = response.json()["execution_id"]
    assert sorted(PythonCodeResult.objects.values_list("execution_id", flat=True)) == sorted(
        ["older-1", execution_id]
    )
    assert len(sandbox_intake.bodies) == 1
