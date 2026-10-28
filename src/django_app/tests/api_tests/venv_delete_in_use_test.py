"""Deleting a virtual environment through the gateway.

A venv is addressed by its binding, never by the id the sandbox knows it under, so
every test here uses a binding whose upstream id is deliberately a different number:
swapping the two would pass otherwise.

`PythonCode.venv` is PROTECTed, so the database would refuse the delete anyway. The
endpoint refuses first, naming what holds the environment, and before anything is
released upstream. The sandbox service is the external boundary and the only thing
replaced here.
"""

from unittest.mock import patch

import pytest
from proxies.sandbox.models import SandboxVenvBinding
from rbac.models import Organization
from rest_framework import status

from tables.models import PythonCode, PythonCodeTool
from tables.models.graph_models import Graph, PythonNode

UPSTREAM_ID = "4711"
CLIENT_PATH = "proxies.sandbox.services.VenvService.client_class"


@pytest.fixture
def binding(default_org):
    return SandboxVenvBinding.objects.create(org_id=default_org.id, resource_id=UPSTREAM_ID)


@pytest.fixture
def other_binding(default_org):
    return SandboxVenvBinding.objects.create(org_id=default_org.id, resource_id="4712")


@pytest.fixture
def other_org(db):
    return Organization.objects.create(name="Org VenvDelete Other")


@pytest.fixture
def sandbox_client():
    """The upstream sandbox, replaced so no delete leaves this process."""
    with patch(CLIENT_PATH) as client_class:
        yield client_class.return_value.__enter__.return_value


def delete_venv(auth_client, binding):
    return auth_client.delete(f"/api/venvs/{binding.pk}/")


@pytest.mark.django_db
def test_an_unused_venv_is_deleted(auth_client, binding, sandbox_client):
    response = delete_venv(auth_client, binding)

    assert response.status_code == status.HTTP_204_NO_CONTENT
    # The sandbox is told the id it knows, not the one this API hands out.
    sandbox_client.remove.assert_called_once_with(UPSTREAM_ID)
    assert not SandboxVenvBinding.objects.filter(pk=binding.pk).exists()


@pytest.mark.django_db
def test_a_venv_a_tool_runs_in_is_refused(auth_client, default_org, binding, sandbox_client):
    python_code = PythonCode.objects.create(
        code="def main(): return 1", entrypoint="main", venv=binding
    )
    PythonCodeTool.objects.create(
        python_code=python_code, org_id=default_org.id, name="Extract PDF", description=""
    )

    response = delete_venv(auth_client, binding)

    assert response.status_code == status.HTTP_409_CONFLICT
    assert "Extract PDF" in response.data["message"]
    # Nothing was released: refusing after the upstream delete would leave the
    # binding pointing at a venv that no longer exists.
    sandbox_client.remove.assert_not_called()
    assert SandboxVenvBinding.objects.filter(pk=binding.pk).exists()


@pytest.mark.django_db
def test_a_venv_a_node_runs_in_is_refused(auth_client, default_org, binding, sandbox_client):
    python_code = PythonCode.objects.create(
        code="def main(): return 1", entrypoint="main", venv=binding
    )
    graph = Graph.objects.create(name="Flow", org=default_org)
    PythonNode.objects.create(graph=graph, python_code=python_code, node_name="Transform")

    response = delete_venv(auth_client, binding)

    assert response.status_code == status.HTTP_409_CONFLICT
    assert "Transform" in response.data["message"]
    sandbox_client.remove.assert_not_called()


@pytest.mark.django_db
def test_a_venv_held_only_by_orphaned_code_says_so(auth_client, binding, sandbox_client):
    """Deleting a tool leaves its PythonCode behind, so a row can outlive every
    owner. The venv stays locked, and the message has to admit there is nothing
    to go and unlink."""
    PythonCode.objects.create(code="def main(): return 1", entrypoint="main", venv=binding)

    response = delete_venv(auth_client, binding)

    assert response.status_code == status.HTTP_409_CONFLICT
    assert "no tool or node uses any more" in response.data["message"]
    sandbox_client.remove.assert_not_called()


@pytest.mark.django_db
def test_an_owner_in_the_recycle_bin_still_holds_it_and_says_so(
    auth_client, default_org, binding, sandbox_client
):
    """A binned node can be restored, so it keeps its environment. The refusal has
    to name an action that exists: the node is in no flow any more, so "move it" is
    a dead end and emptying the recycle bin is the way out.

    The flow is binned through its own delete, which is how a user gets here.
    """
    python_code = PythonCode.objects.create(
        code="def main(): return 1", entrypoint="main", venv=binding
    )
    graph = Graph.objects.create(name="Flow", org=default_org)
    PythonNode.objects.create(graph=graph, python_code=python_code, node_name="Python-Node #1")
    graph.delete()

    response = delete_venv(auth_client, binding)

    assert response.status_code == status.HTTP_409_CONFLICT
    assert "Python-Node #1" in response.data["message"]
    assert "recycle bin" in response.data["message"]
    assert "Move them" not in response.data["message"]
    sandbox_client.remove.assert_not_called()


@pytest.mark.django_db
def test_a_live_owner_is_named_rather_than_a_binned_one(
    auth_client, default_org, binding, sandbox_client
):
    """With something still live, that is the one the caller can act on."""
    binned_graph = Graph.objects.create(name="Binned flow", org=default_org)
    PythonNode.objects.create(
        graph=binned_graph,
        python_code=PythonCode.objects.create(code="x", entrypoint="main", venv=binding),
        node_name="Binned node",
    )
    binned_graph.delete()

    live_graph = Graph.objects.create(name="Live flow", org=default_org)
    PythonNode.objects.create(
        graph=live_graph,
        python_code=PythonCode.objects.create(code="y", entrypoint="main", venv=binding),
        node_name="Live node",
    )

    response = delete_venv(auth_client, binding)

    assert response.status_code == status.HTTP_409_CONFLICT
    assert "Live node" in response.data["message"]
    assert "Binned node" not in response.data["message"]
    assert "Move them" in response.data["message"]


@pytest.mark.django_db
def test_code_in_another_venv_does_not_block_this_one(
    auth_client, default_org, binding, other_binding, sandbox_client
):
    python_code = PythonCode.objects.create(
        code="def main(): return 1", entrypoint="main", venv=other_binding
    )
    PythonCodeTool.objects.create(
        python_code=python_code, org_id=default_org.id, name="Other tool", description=""
    )

    assert delete_venv(auth_client, binding).status_code == status.HTTP_204_NO_CONTENT


@pytest.mark.django_db
def test_a_venv_of_another_org_is_not_found(auth_client, other_org, sandbox_client):
    """Cross-org is a 404, never a 403: the binding's existence is not disclosed."""
    foreign = SandboxVenvBinding.objects.create(org_id=other_org.id, resource_id="4713")

    assert delete_venv(auth_client, foreign).status_code == status.HTTP_404_NOT_FOUND
    sandbox_client.remove.assert_not_called()
    assert SandboxVenvBinding.objects.filter(pk=foreign.pk).exists()
