"""The `libs_lock` of a venv in the API: why the caller may not change its libraries.

Code that runs in a venv with a storage grant locks the venv's libraries for a caller who
lacks the Files permission behind that grant. The sandbox is the external boundary and the
only thing replaced.
"""

from unittest.mock import patch

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework import status

from proxies.sandbox.models import SandboxVenvBinding
from rbac.models.enums import Permission, ResourceType
from tables.models import Graph, PythonCode
from tables.models.graph_models import (
    ClassificationDecisionTableNode,
    PythonNode,
    WebhookTriggerNode,
)
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

CLIENT_PATH = "proxies.sandbox.services.VenvService.client_class"

ALL_PERMISSIONS = (
    Permission.CREATE | Permission.READ | Permission.UPDATE | Permission.DELETE | Permission.LIST
)

DELETE_LOCK = (
    "Code that runs in this virtual environment has Files: Delete, which you don't have. "
    "You can rename it, but not change its libraries."
)


@pytest.fixture
def sandbox_client():
    with patch(CLIENT_PATH) as client_class:
        yield client_class.return_value.__enter__.return_value


@pytest.fixture
def flow(acme):
    return Graph.objects.create(name="venv-lock-flow", org=acme)


@pytest.fixture
def no_delete_user(custom_role_user, acme):
    """Full access to venvs, and Files except Delete."""
    return custom_role_user(
        acme,
        "venv-lock-no-delete@example.com",
        {
            ResourceType.VENVS: ALL_PERMISSIONS,
            ResourceType.FILES: Permission.READ | Permission.CREATE | Permission.UPDATE,
        },
    )


@pytest.fixture
def full_files_user(custom_role_user, acme):
    """Full access to venvs and every Files permission."""
    return custom_role_user(
        acme,
        "venv-lock-full-files@example.com",
        {
            ResourceType.VENVS: ALL_PERMISSIONS,
            ResourceType.FILES: ALL_PERMISSIONS,
        },
    )


def _venv(org, resource_id):
    return SandboxVenvBinding.objects.create(org_id=org.id, resource_id=str(resource_id))


def _upstream(*bindings):
    result = [
        {
            "id": int(binding.resource_id),
            "name": f"venv-{binding.resource_id}",
            "libs": [],
            "status": "completed",
            "error": None,
        }
        for binding in bindings
    ]
    return {
        "count": len(result),
        "limit": 0,
        "offset": 0,
        "next": None,
        "previous": None,
        "result": result,
    }


def _python_code(venv):
    return PythonCode.objects.create(code="def main(): return 1", entrypoint="main", venv=venv)


def _run_python_node_in(flow, venv, *, name="py", **flags):
    return PythonNode.objects.create(
        graph=flow, node_name=name, python_code=_python_code(venv), **flags
    )


def _client(client_as, user, org):
    client = client_as(user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client


@pytest.fixture
def locked_and_free(acme, flow):
    locked = _venv(acme, 7001)
    free = _venv(acme, 7002)
    _run_python_node_in(flow, locked, storage_grant_delete=True)
    _run_python_node_in(
        flow, free, name="py-plain", storage_grant_read=False, storage_grant_write=False
    )
    return locked, free


@pytest.mark.django_db
def test_list_marks_the_locked_venv_and_leaves_the_other_null(
    client_as, no_delete_user, acme, locked_and_free, sandbox_client
):
    locked, free = locked_and_free
    sandbox_client.list.return_value = _upstream(locked, free)

    response = _client(client_as, no_delete_user, acme).get("/api/venvs/")

    assert response.status_code == status.HTTP_200_OK
    locks = {item["id"]: item["libs_lock"] for item in response.data["result"]}
    assert locks == {locked.pk: DELETE_LOCK, free.pk: None}


@pytest.mark.django_db
def test_list_reads_the_locks_in_a_bounded_number_of_queries(
    client_as, no_delete_user, acme, flow, sandbox_client
):
    first = _venv(acme, 7101)
    _run_python_node_in(flow, first, name="py-1", storage_grant_delete=True)
    listed = [first]
    # The gateway takes `result` off the page it is given, so every call needs a fresh one.
    sandbox_client.list.side_effect = lambda **kwargs: _upstream(*listed)
    client = _client(client_as, no_delete_user, acme)
    with CaptureQueriesContext(connection) as one_venv:
        one = client.get("/api/venvs/")

    more = [_venv(acme, 7102 + offset) for offset in range(5)]
    for offset, venv in enumerate(more):
        _run_python_node_in(flow, venv, name=f"py-{offset + 2}", storage_grant_delete=True)
    listed.extend(more)
    with CaptureQueriesContext(connection) as six_venvs:
        six = client.get("/api/venvs/")

    assert [item["libs_lock"] for item in one.data["result"]] == [DELETE_LOCK]
    assert [item["libs_lock"] for item in six.data["result"]] == [DELETE_LOCK] * 6
    assert len(six_venvs) == len(one_venv)


@pytest.mark.django_db
def test_retrieve_carries_the_lock(client_as, no_delete_user, acme, locked_and_free, sandbox_client):
    locked, _ = locked_and_free
    sandbox_client.retrieve.return_value = _upstream(locked)["result"][0]

    response = _client(client_as, no_delete_user, acme).get(f"/api/venvs/{locked.pk}/")

    assert response.data["libs_lock"] == DELETE_LOCK


@pytest.mark.django_db
def test_a_caller_holding_the_permissions_gets_null(
    client_as, full_files_user, acme, locked_and_free, sandbox_client
):
    locked, free = locked_and_free
    sandbox_client.list.return_value = _upstream(locked, free)

    response = _client(client_as, full_files_user, acme).get("/api/venvs/")

    assert [item["libs_lock"] for item in response.data["result"]] == [None, None]


@pytest.mark.django_db
def test_a_superadmin_gets_null(client_as, superadmin, acme, locked_and_free, sandbox_client):
    locked, _ = locked_and_free
    sandbox_client.retrieve.return_value = _upstream(locked)["result"][0]

    response = _client(client_as, superadmin, acme).get(f"/api/venvs/{locked.pk}/")

    assert response.data["libs_lock"] is None


@pytest.mark.django_db
def test_grants_of_every_code_slot_in_the_venv_are_combined(
    client_as, no_delete_user, acme, flow, sandbox_client
):
    venv = _venv(acme, 7201)
    # Webhook code is granted Write, which the caller holds; the classification table's
    # post slot is granted Delete, which they lack. Only the missing one is named.
    WebhookTriggerNode.objects.create(
        graph=flow,
        node_name="hook",
        python_code=_python_code(venv),
        storage_grant_write=True,
    )
    ClassificationDecisionTableNode.objects.create(
        graph=flow,
        node_name="cdt",
        post_python_code=_python_code(venv),
        post_storage_grant_delete=True,
    )
    sandbox_client.retrieve.return_value = _upstream(venv)["result"][0]

    response = _client(client_as, no_delete_user, acme).get(f"/api/venvs/{venv.pk}/")

    assert response.data["libs_lock"] == DELETE_LOCK


@pytest.mark.django_db
def test_a_grant_in_another_org_does_not_lock_the_venv(
    client_as, no_delete_user, acme, beta, sandbox_client
):
    venv = _venv(acme, 7301)
    foreign_flow = Graph.objects.create(name="foreign", org=beta)
    _run_python_node_in(foreign_flow, venv, storage_grant_delete=True)
    sandbox_client.retrieve.return_value = _upstream(venv)["result"][0]

    response = _client(client_as, no_delete_user, acme).get(f"/api/venvs/{venv.pk}/")

    assert response.data["libs_lock"] is None


@pytest.mark.django_db
def test_create_answers_with_a_null_lock(client_as, no_delete_user, acme, sandbox_client):
    sandbox_client.create.return_value = {
        "id": 7401,
        "name": "fresh",
        "libs": [],
        "status": "declared",
        "error": None,
    }

    response = _client(client_as, no_delete_user, acme).post(
        "/api/venvs/", {"name": "fresh", "libs": []}, format="json"
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.data["libs_lock"] is None


@pytest.mark.django_db
def test_a_rename_succeeds_and_the_answer_still_reports_the_lock(
    client_as, no_delete_user, acme, locked_and_free, sandbox_client
):
    locked, _ = locked_and_free
    current = _upstream(locked)["result"][0]
    sandbox_client.retrieve.return_value = current
    sandbox_client.update.return_value = {**current, "name": "renamed"}

    response = _client(client_as, no_delete_user, acme).patch(
        f"/api/venvs/{locked.pk}/", {"name": "renamed"}, format="json"
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data["name"] == "renamed"
    assert response.data["libs_lock"] == DELETE_LOCK
