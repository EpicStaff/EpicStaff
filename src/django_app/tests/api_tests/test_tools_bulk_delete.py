import pytest
from rest_framework.test import APIClient

from tables.models.mcp_models import McpTool
from tables.models.python_models import PythonCode, PythonCodeTool
from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole


# ---- fixtures ----


@pytest.fixture
def role_org_admin(db):
    return Role.objects.get(
        name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True
    )


@pytest.fixture
def role_viewer(db):
    return Role.objects.get(name=BuiltInRole.VIEWER, is_built_in=True, org__isnull=True)


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="Org A")


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="Org B")


@pytest.fixture
def org_admin_a(db, django_user_model, org_a, role_org_admin):
    # Org Admin has TOOLS delete (bitmask 15 = C R U D); Member only has C R U
    # (bitmask 7, no DELETE) so bulk_delete would 403 for Member too — matches
    # the single-object destroy path's permission requirement.
    user = django_user_model.objects.create_user(
        email="tbd_admin_a@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org_a, role=role_org_admin)
    return user


@pytest.fixture
def viewer_a(db, django_user_model, org_a, role_viewer):
    user = django_user_model.objects.create_user(
        email="tbd_viewer_a@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org_a, role=role_viewer)
    return user


@pytest.fixture
def client_a(org_admin_a, org_a):  # Org Admin: tools CRUD, including delete
    c = APIClient()
    c.force_authenticate(user=org_admin_a)
    c.credentials(HTTP_X_ORGANIZATION_ID=str(org_a.id))
    return c


@pytest.fixture
def viewer_client_a(viewer_a, org_a):  # Viewer: tools READ only -> no delete
    c = APIClient()
    c.force_authenticate(user=viewer_a)
    c.credentials(HTTP_X_ORGANIZATION_ID=str(org_a.id))
    return c


def _make_python_tool(*, org=None, built_in=False, name="tool"):
    code = PythonCode.objects.create(code="x", entrypoint="main")
    return PythonCodeTool.objects.create(
        name=name, description="", python_code=code, built_in=built_in, org=org
    )


def _make_mcp_tool(*, org, name="mcp"):
    return McpTool.objects.create(
        name=name, transport="https://example.com/mcp", tool_name="do_thing", org=org
    )


# ---- PythonCodeTool bulk_delete ----


@pytest.mark.django_db
def test_python_code_tool_bulk_delete_deletes_non_builtin_and_skips_builtin(
    client_a, org_a
):
    builtin = _make_python_tool(built_in=True, org=None, name="builtin")
    custom_1 = _make_python_tool(built_in=False, org=org_a, name="custom1")
    custom_2 = _make_python_tool(built_in=False, org=org_a, name="custom2")

    resp = client_a.post(
        "/api/python-code-tool/bulk-delete/",
        {"ids": [builtin.id, custom_1.id, custom_2.id]},
        format="json",
    )

    assert resp.status_code == 200, resp.data
    assert resp.data["deleted"] == 2
    assert resp.data["ids"] == [builtin.id, custom_1.id, custom_2.id]

    assert PythonCodeTool.objects.filter(id=builtin.id).exists()
    assert not PythonCodeTool.objects.filter(id=custom_1.id).exists()
    assert not PythonCodeTool.objects.filter(id=custom_2.id).exists()


@pytest.mark.django_db
def test_python_code_tool_bulk_delete_cross_org_not_deleted(client_a, org_a, org_b):
    foreign = _make_python_tool(built_in=False, org=org_b, name="theirs")

    resp = client_a.post(
        "/api/python-code-tool/bulk-delete/", {"ids": [foreign.id]}, format="json"
    )

    assert resp.status_code == 200, resp.data
    assert resp.data["deleted"] == 0
    assert PythonCodeTool.objects.filter(id=foreign.id).exists()


@pytest.mark.django_db
def test_python_code_tool_bulk_delete_invalid_ids_returns_400(client_a):
    resp = client_a.post(
        "/api/python-code-tool/bulk-delete/", {"ids": "not-a-list"}, format="json"
    )
    assert resp.status_code == 400


@pytest.mark.django_db
def test_python_code_tool_bulk_delete_denied_for_viewer(viewer_client_a, org_a):
    tool = _make_python_tool(built_in=False, org=org_a, name="mine")
    resp = viewer_client_a.post(
        "/api/python-code-tool/bulk-delete/", {"ids": [tool.id]}, format="json"
    )
    assert resp.status_code == 403
    assert PythonCodeTool.objects.filter(id=tool.id).exists()


# ---- McpTool bulk_delete ----


@pytest.mark.django_db
def test_mcp_tool_bulk_delete_deletes_everything_requested(client_a, org_a):
    mcp_1 = _make_mcp_tool(org=org_a, name="mine1")
    mcp_2 = _make_mcp_tool(org=org_a, name="mine2")

    resp = client_a.post(
        "/api/mcp-tools/bulk-delete/", {"ids": [mcp_1.id, mcp_2.id]}, format="json"
    )

    assert resp.status_code == 200, resp.data
    assert resp.data["deleted"] == 2
    assert resp.data["ids"] == [mcp_1.id, mcp_2.id]
    assert not McpTool.objects.filter(id__in=[mcp_1.id, mcp_2.id]).exists()


@pytest.mark.django_db
def test_mcp_tool_bulk_delete_cross_org_not_deleted(client_a, org_a, org_b):
    foreign = _make_mcp_tool(org=org_b, name="theirs")

    resp = client_a.post(
        "/api/mcp-tools/bulk-delete/", {"ids": [foreign.id]}, format="json"
    )

    assert resp.status_code == 200, resp.data
    assert resp.data["deleted"] == 0
    assert McpTool.objects.filter(id=foreign.id).exists()


@pytest.mark.django_db
def test_mcp_tool_bulk_delete_denied_for_viewer(viewer_client_a, org_a):
    mcp_tool = _make_mcp_tool(org=org_a, name="mine")
    resp = viewer_client_a.post(
        "/api/mcp-tools/bulk-delete/", {"ids": [mcp_tool.id]}, format="json"
    )
    assert resp.status_code == 403
    assert McpTool.objects.filter(id=mcp_tool.id).exists()
