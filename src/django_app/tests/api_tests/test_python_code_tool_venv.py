"""Assigning and clearing a tool's virtual environment over the API.

The tool editor sends the whole `python_code` body on save, `venv_id` included
and `null` when the user picked no venv. That is not cosmetic: the update applies
the keys it is given, so an omitted `venv_id` keeps whatever was there. These
tests pin all three outcomes, because the frontend relies on the difference
between sending `null` and sending nothing.
"""

import pytest
from proxies.sandbox.models import SandboxVenvBinding
from rbac.models import Organization, OrganizationUser, Role
from rbac.models.enums import BuiltInRole
from rest_framework import status
from rest_framework.test import APIClient

from tables.models import PythonCode, PythonCodeTool

VENV_ID = 12
OTHER_VENV_ID = 13


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org ToolVenv")


@pytest.fixture
def admin_client(db, django_user_model, org):
    role = Role.objects.get(name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True)
    user = django_user_model.objects.create_user(
        email="toolvenv_admin@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org, role=role)
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client


@pytest.fixture
def owned_venvs(org):
    """Both venvs bound to this org, so the scope check is not what is under test."""
    for venv_id in (VENV_ID, OTHER_VENV_ID):
        SandboxVenvBinding.objects.create(org_id=org.id, resource_id=str(venv_id))


@pytest.fixture
def tool(org):
    python_code = PythonCode.objects.create(
        code="def main():\n    return 1\n", entrypoint="main", venv_id=VENV_ID
    )
    return PythonCodeTool.objects.create(
        org=org, name="Fetch orders", description="Fetches orders", python_code=python_code
    )


def put_tool(client, tool, python_code: dict):
    return client.put(
        f"/api/python-code-tool/{tool.id}/",
        {
            "name": tool.name,
            "description": tool.description,
            "variables": [],
            "python_code": python_code,
            "use_storage": False,
        },
        format="json",
    )


def venv_of(tool) -> int | None:
    tool.python_code.refresh_from_db()
    return tool.python_code.venv_id


@pytest.mark.django_db
def test_a_venv_in_the_body_is_assigned(admin_client, tool, owned_venvs):
    response = put_tool(
        admin_client,
        tool,
        {"code": tool.python_code.code, "entrypoint": "main", "venv_id": OTHER_VENV_ID},
    )

    assert response.status_code == status.HTTP_200_OK
    assert venv_of(tool) == OTHER_VENV_ID


@pytest.mark.django_db
def test_a_null_venv_clears_the_one_the_tool_had(admin_client, tool, owned_venvs):
    response = put_tool(
        admin_client,
        tool,
        {"code": tool.python_code.code, "entrypoint": "main", "venv_id": None},
    )

    assert response.status_code == status.HTTP_200_OK
    assert venv_of(tool) is None


@pytest.mark.django_db
def test_a_body_without_the_key_keeps_the_venv(admin_client, tool, owned_venvs):
    """Why the editor sends `null` rather than leaving the key out."""
    response = put_tool(
        admin_client,
        tool,
        {"code": tool.python_code.code, "entrypoint": "main"},
    )

    assert response.status_code == status.HTTP_200_OK
    assert venv_of(tool) == VENV_ID


@pytest.fixture
def other_org(db):
    return Organization.objects.create(name="Org ToolVenv Other")


@pytest.mark.django_db
@pytest.mark.parametrize(
    "bind_to",
    [pytest.param("other", id="owned-by-another-org"), pytest.param(None, id="owned-by-nobody")],
)
def test_a_venv_the_org_does_not_own_is_refused(admin_client, tool, other_org, bind_to):
    """A venv is reachable only through a binding in the caller's own org.

    Both cases answer the same way on purpose: telling the caller that the venv
    exists but belongs elsewhere would confirm another org's inventory.
    """
    if bind_to == "other":
        SandboxVenvBinding.objects.create(org_id=other_org.id, resource_id=str(OTHER_VENV_ID))

    response = put_tool(
        admin_client,
        tool,
        {"code": tool.python_code.code, "entrypoint": "main", "venv_id": OTHER_VENV_ID},
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["message"] == 'python_code: venv_id: Invalid pk "13" - object does not exist.'
    assert venv_of(tool) == VENV_ID


@pytest.mark.django_db
def test_a_tool_cannot_be_created_in_another_orgs_venv(admin_client, org, other_org):
    SandboxVenvBinding.objects.create(org_id=other_org.id, resource_id=str(OTHER_VENV_ID))

    response = admin_client.post(
        "/api/python-code-tool/",
        {
            "name": "Smuggled",
            "description": "Runs where it should not",
            "variables": [],
            "python_code": {
                "code": "def main():\n    return 1\n",
                "entrypoint": "main",
                "venv_id": OTHER_VENV_ID,
            },
            "use_storage": False,
        },
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert not PythonCodeTool.objects.filter(name="Smuggled").exists()
