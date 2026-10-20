"""Deleting a virtual environment through the gateway.

`PythonCode.venv_id` is a plain integer column, so nothing in the database stops
a venv from being deleted out from under the code that runs in it. The endpoint
refuses instead. The sandbox service itself is the external boundary and is the
only thing replaced here.
"""

from unittest.mock import patch

import pytest
from proxies.sandbox.models import SandboxVenvBinding
from rest_framework import status

from tables.models import PythonCode, PythonCodeTool
from tables.models.graph_models import Graph, PythonNode

VENV_ID = 12
CLIENT_PATH = "proxies.sandbox.views.SandboxVenvBindingViewSet.client_class"


@pytest.fixture
def binding(default_org):
    return SandboxVenvBinding.objects.create(org_id=default_org.id, resource_id=str(VENV_ID))


@pytest.fixture
def sandbox_client():
    """The upstream sandbox, replaced so no delete leaves this process."""
    with patch(CLIENT_PATH) as client_class:
        yield client_class.return_value.__enter__.return_value


def delete_venv(auth_client):
    return auth_client.delete(f"/api/venvs/{VENV_ID}/")


@pytest.mark.django_db
def test_an_unused_venv_is_deleted(auth_client, binding, sandbox_client):
    response = delete_venv(auth_client)

    assert response.status_code == status.HTTP_204_NO_CONTENT
    sandbox_client.remove.assert_called_once_with(str(VENV_ID))
    assert not SandboxVenvBinding.objects.filter(pk=binding.pk).exists()


@pytest.mark.django_db
def test_a_venv_a_tool_runs_in_is_refused(auth_client, default_org, binding, sandbox_client):
    python_code = PythonCode.objects.create(
        code="def main(): return 1", entrypoint="main", venv_id=VENV_ID
    )
    PythonCodeTool.objects.create(
        python_code=python_code, org_id=default_org.id, name="Extract PDF", description=""
    )

    response = delete_venv(auth_client)

    assert response.status_code == status.HTTP_409_CONFLICT
    assert "Extract PDF" in response.data["message"]
    # Nothing was released: refusing after the upstream delete would leave the
    # binding pointing at a venv that no longer exists.
    sandbox_client.remove.assert_not_called()
    assert SandboxVenvBinding.objects.filter(pk=binding.pk).exists()


@pytest.mark.django_db
def test_a_venv_a_node_runs_in_is_refused(auth_client, default_org, binding, sandbox_client):
    python_code = PythonCode.objects.create(
        code="def main(): return 1", entrypoint="main", venv_id=VENV_ID
    )
    graph = Graph.objects.create(name="Flow", org=default_org)
    PythonNode.objects.create(graph=graph, python_code=python_code, node_name="Transform")

    response = delete_venv(auth_client)

    assert response.status_code == status.HTTP_409_CONFLICT
    assert "Transform" in response.data["message"]
    sandbox_client.remove.assert_not_called()


@pytest.mark.django_db
def test_a_venv_held_only_by_orphaned_code_says_so(auth_client, binding, sandbox_client):
    """Deleting a tool leaves its PythonCode behind, so a row can outlive every
    owner. The venv stays locked, and the message has to admit there is nothing
    to go and unlink."""
    PythonCode.objects.create(code="def main(): return 1", entrypoint="main", venv_id=VENV_ID)

    response = delete_venv(auth_client)

    assert response.status_code == status.HTTP_409_CONFLICT
    assert "no tool or node uses any more" in response.data["message"]
    sandbox_client.remove.assert_not_called()


@pytest.mark.django_db
def test_code_in_another_venv_does_not_block_this_one(auth_client, default_org, binding, sandbox_client):
    python_code = PythonCode.objects.create(
        code="def main(): return 1", entrypoint="main", venv_id=VENV_ID + 1
    )
    PythonCodeTool.objects.create(
        python_code=python_code, org_id=default_org.id, name="Other tool", description=""
    )

    assert delete_venv(auth_client).status_code == status.HTTP_204_NO_CONTENT
