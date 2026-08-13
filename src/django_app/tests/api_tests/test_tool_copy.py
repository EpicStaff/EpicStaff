import pytest
from rest_framework.test import APIClient

from tables.models.python_models import PythonCode, PythonCodeTool
from tables.models.rbac_models import Organization, OrganizationUser, Role


# ---- fixtures ----


@pytest.fixture
def org_admin_role(db):
    return Role.objects.get(name="Org Admin", is_built_in=True, org__isnull=True)


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="Org A")


@pytest.fixture
def member_a(db, django_user_model, org_a, org_admin_role):
    user = django_user_model.objects.create_user(
        email="copy_member_a@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org_a, role=org_admin_role)
    return user


@pytest.fixture
def client_a(member_a, org_a):
    client = APIClient()
    client.force_authenticate(user=member_a)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org_a.id))
    return client


def _make_tool(*, org=None, built_in=False, name="tool"):
    code = PythonCode.objects.create(code="def main(): return 1", entrypoint="main")
    return PythonCodeTool.objects.create(
        name=name,
        description="desc",
        python_code=code,
        built_in=built_in,
        org=org,
    )


@pytest.fixture
def built_in_python_code_tool() -> PythonCodeTool:
    # Real built-in tools are global (org=None), visible to every org.
    return _make_tool(built_in=True, org=None, name="BuiltInTool")


# ---- copy of a built-in tool ----


@pytest.mark.django_db
def test_copy_built_in_tool_succeeds_and_is_not_built_in(
    client_a, org_a, built_in_python_code_tool
):
    resp = client_a.post(
        f"/api/python-code-tool/{built_in_python_code_tool.id}/copy/",
        {},
        format="json",
    )
    assert resp.status_code == 201, resp.data
    assert resp.data["built_in"] is False

    copy = PythonCodeTool.objects.get(id=resp.data["id"])
    assert copy.built_in is False
    assert copy.id != built_in_python_code_tool.id


@pytest.mark.django_db
def test_copy_of_built_in_tool_lands_in_active_org(
    client_a, org_a, built_in_python_code_tool
):
    # Source built-in tool has org=None; the copy must be stamped with the
    # caller's active org, not inherit the None org_id.
    resp = client_a.post(
        f"/api/python-code-tool/{built_in_python_code_tool.id}/copy/",
        {},
        format="json",
    )
    assert resp.status_code == 201, resp.data

    copy = PythonCodeTool.objects.get(id=resp.data["id"])
    assert copy.org_id == org_a.id


@pytest.mark.django_db
def test_copy_of_built_in_tool_duplicates_python_code_row(
    client_a, org_a, built_in_python_code_tool
):
    resp = client_a.post(
        f"/api/python-code-tool/{built_in_python_code_tool.id}/copy/",
        {},
        format="json",
    )
    assert resp.status_code == 201, resp.data

    copy = PythonCodeTool.objects.get(id=resp.data["id"])
    assert copy.python_code_id != built_in_python_code_tool.python_code_id
    assert copy.python_code.code == built_in_python_code_tool.python_code.code
    assert copy.python_code.entrypoint == built_in_python_code_tool.python_code.entrypoint


@pytest.mark.django_db
def test_copy_of_built_in_tool_is_then_fully_patch_editable(
    client_a, org_a, built_in_python_code_tool
):
    resp = client_a.post(
        f"/api/python-code-tool/{built_in_python_code_tool.id}/copy/",
        {},
        format="json",
    )
    assert resp.status_code == 201, resp.data
    copy_id = resp.data["id"]

    patch_resp = client_a.patch(
        f"/api/python-code-tool/{copy_id}/",
        {"name": "RenamedCopy", "description": "new desc"},
        format="json",
    )
    assert patch_resp.status_code == 200, patch_resp.data

    copy = PythonCodeTool.objects.get(id=copy_id)
    assert copy.name == "RenamedCopy"
    assert copy.description == "new desc"


# ---- existing built-in guardrails must remain intact ----


@pytest.mark.django_db
def test_built_in_tool_still_cannot_be_deleted(client_a, org_a, built_in_python_code_tool):
    resp = client_a.delete(
        f"/api/python-code-tool/{built_in_python_code_tool.id}/"
    )
    assert resp.status_code in (400, 403, 404)
    assert PythonCodeTool.objects.filter(id=built_in_python_code_tool.id).exists()
