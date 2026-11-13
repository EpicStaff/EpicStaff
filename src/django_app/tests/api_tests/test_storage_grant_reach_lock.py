"""Editing a virtualenv is locked by the boxes of the code that runs in it.

Code in a virtualenv runs with the libraries installed there, so changing them is changing
what code run with a storage grant executes.
"""

from unittest.mock import patch

import pytest
from rest_framework import status

from proxies.sandbox.models import SandboxVenvBinding
from rbac.models.enums import Permission, ResourceType
from tables.models import Graph, PythonCode
from tables.models.graph_models import ClassificationDecisionTableNode, PythonNode
from tests.custom_role_fixtures import *  # noqa: F401,F403
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

ALL = Permission.CREATE | Permission.READ | Permission.UPDATE | Permission.DELETE
RW_GRANT = {"storage_grant_read": True, "storage_grant_write": True, "storage_grant_delete": False}
READ_AND_WRITE = (
    "This code runs with Files: Read, Files: Create, Files: Update, which you don't have. "
    "Contact an admin to change it."
)


@pytest.fixture
def flow(acme):
    return Graph.objects.create(name="reach-flow", org=acme)


@pytest.fixture
def editor(client_as, custom_role_user, acme):
    """Edits flows and virtualenvs: no FILES permission at all."""
    permissions = {ResourceType.FLOWS: ALL, ResourceType.VENVS: ALL}
    client = client_as(custom_role_user(acme, "reach-editor@example.com", permissions))
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


@pytest.fixture
def admin_client(client_as, admin_acme, acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


@pytest.fixture
def venv(acme):
    return SandboxVenvBinding.objects.create(org_id=acme.id, resource_id="9001")


@pytest.fixture
def upstream():
    with patch("proxies.sandbox.services.VenvService.update", return_value={"libs": ["x"]}) as update:
        yield update


@pytest.mark.django_db
def test_changing_a_venv_that_ticked_code_runs_in_needs_those_boxes(
    flow, venv, editor, admin_client, upstream
):
    PythonNode.objects.create(
        graph=flow, python_code=PythonCode.objects.create(code="x", venv=venv), **RW_GRANT
    )

    refused = editor.patch(f"/api/venvs/{venv.pk}/", {"libs": ["requests"]}, format="json")
    allowed = admin_client.patch(f"/api/venvs/{venv.pk}/", {"libs": ["requests"]}, format="json")

    assert refused.status_code == status.HTTP_403_FORBIDDEN
    assert refused.data["message"] == READ_AND_WRITE
    assert allowed.status_code == status.HTTP_200_OK, allowed.content
    assert upstream.call_count == 1


@pytest.mark.django_db
def test_each_code_slot_of_a_classification_table_locks_its_venv_by_its_own_boxes(
    flow, venv, editor, upstream
):
    ClassificationDecisionTableNode.objects.create(
        graph=flow,
        pre_python_code=PythonCode.objects.create(code="x"),
        post_python_code=PythonCode.objects.create(code="y", venv=venv),
        pre_storage_grant_read=True,
        post_storage_grant_read=False,
    )

    response = editor.patch(f"/api/venvs/{venv.pk}/", {"libs": ["requests"]}, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content


@pytest.mark.django_db
def test_a_venv_used_only_by_code_with_no_box_ticked_is_free(flow, venv, editor, upstream):
    PythonNode.objects.create(graph=flow, python_code=PythonCode.objects.create(code="x", venv=venv))

    response = editor.patch(f"/api/venvs/{venv.pk}/", {"libs": ["requests"]}, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content


@pytest.mark.django_db
def test_another_orgs_venv_is_a_404_not_a_403(beta, venv, client_as, custom_role_user, upstream):
    outsider = client_as(
        custom_role_user(beta, "reach-outsider@example.com", {ResourceType.VENVS: ALL})
    )
    outsider.credentials(HTTP_X_ORGANIZATION_ID=str(beta.id))

    response = outsider.patch(f"/api/venvs/{venv.pk}/", {"libs": ["requests"]}, format="json")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    upstream.assert_not_called()
