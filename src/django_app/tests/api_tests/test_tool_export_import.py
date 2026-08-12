import pytest
from rest_framework.test import APIClient

from tables.models.label_models import Label
from tables.models.mcp_models import McpTool
from tables.models.python_models import PythonCode, PythonCodeTool
from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import Permission, ResourceType
from tables.models.rbac_models.role import RolePermission


# ---- fixtures ----
#
# Both built-in roles now carry the EXPORT bit (16) on the TOOLS resource
# (EST-3207, migration 0210_seed_tools_export_permission): "Org Admin" is
# 31 (C R U D E) and "Member" is 23 (C R U E, no D — matching the shape
# `files` already uses for Member). A separate custom role is still used
# for the export/import-focused tests below (mirroring the pattern in
# import_export_tests/test_org_scoping_import_permissions.py); built-in
# role coverage lives in test_builtin_role_tools_export_permission below.


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="Org A")


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="Org B")


@pytest.fixture
def exporter_role_a(db, org_a):
    role = Role.objects.create(name="ToolExporter", org=org_a, is_built_in=False)
    RolePermission.objects.create(
        role=role,
        resource_type=ResourceType.TOOLS,
        permissions=int(Permission.CREATE | Permission.READ | Permission.EXPORT),
    )
    return role


@pytest.fixture
def user_a(db, django_user_model, org_a, exporter_role_a):
    user = django_user_model.objects.create_user(
        email="exporter_a@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org_a, role=exporter_role_a)
    return user


@pytest.fixture
def client_a(user_a, org_a):
    c = APIClient()
    c.force_authenticate(user=user_a)
    c.credentials(HTTP_X_ORGANIZATION_ID=str(org_a.id))
    return c


@pytest.fixture
def tool_label_a(org_a):
    return Label.objects.create(name="Billing", org=org_a, scope=Label.Scope.TOOL)


@pytest.fixture
def python_tool_a(org_a, tool_label_a):
    code = PythonCode.objects.create(
        code="def main(): return 1", entrypoint="main", libraries=""
    )
    tool = PythonCodeTool.objects.create(
        name="PyToolA",
        description="desc",
        python_code=code,
        org=org_a,
    )
    tool.labels.add(tool_label_a)
    return tool


@pytest.fixture
def mcp_tool_a(org_a, tool_label_a):
    tool = McpTool.objects.create(
        name="McpToolA",
        transport="https://example.com/mcp",
        tool_name="do_thing",
        org=org_a,
    )
    tool.labels.add(tool_label_a)
    return tool


# ---- export ----


@pytest.mark.django_db
def test_pythoncodetool_export_includes_labels_no_favorite_key(client_a, python_tool_a):
    resp = client_a.get(f"/api/python-code-tool/{python_tool_a.id}/export/")
    assert resp.status_code == 200

    data = resp.json()
    tool_data = data["PythonCodeTool"][0]
    assert tool_data["labels"] == [
        *python_tool_a.labels.values_list("id", flat=True)
    ]
    assert "favorite" not in tool_data
    assert "is_favorite" not in tool_data


@pytest.mark.django_db
def test_mcptool_export_includes_labels_no_favorite_key(client_a, mcp_tool_a):
    resp = client_a.get(f"/api/mcp-tools/{mcp_tool_a.id}/export/")
    assert resp.status_code == 200

    data = resp.json()
    tool_data = data["MCPTool"][0]
    assert tool_data["labels"] == [*mcp_tool_a.labels.values_list("id", flat=True)]
    assert "favorite" not in tool_data
    assert "is_favorite" not in tool_data


# ---- bulk export ----


@pytest.fixture
def python_tool_a2(org_a, tool_label_a):
    code = PythonCode.objects.create(
        code="def main(): return 2", entrypoint="main", libraries=""
    )
    tool = PythonCodeTool.objects.create(
        name="PyToolA2",
        description="desc2",
        python_code=code,
        org=org_a,
    )
    return tool


@pytest.fixture
def mcp_tool_a2(org_a):
    return McpTool.objects.create(
        name="McpToolA2",
        transport="https://example.com/mcp2",
        tool_name="do_other_thing",
        org=org_a,
    )


@pytest.fixture
def builtin_python_tool(db):
    code = PythonCode.objects.create(
        code="def main(): return 3", entrypoint="main", libraries=""
    )
    return PythonCodeTool.objects.create(
        name="BuiltInPyTool",
        description="builtin",
        python_code=code,
        org=None,
        built_in=True,
    )


@pytest.mark.django_db
def test_pythoncodetool_bulk_export_covers_all_ids(
    client_a, python_tool_a, python_tool_a2
):
    resp = client_a.post(
        "/api/python-code-tool/bulk-export/",
        {"ids": [python_tool_a.id, python_tool_a2.id]},
        format="json",
    )
    assert resp.status_code == 200, resp.data
    data = resp.json()
    exported_ids = {row["id"] for row in data["PythonCodeTool"]}
    assert exported_ids == {python_tool_a.id, python_tool_a2.id}


@pytest.mark.django_db
def test_mcptool_bulk_export_covers_all_ids(client_a, mcp_tool_a, mcp_tool_a2):
    resp = client_a.post(
        "/api/mcp-tools/bulk-export/",
        {"ids": [mcp_tool_a.id, mcp_tool_a2.id]},
        format="json",
    )
    assert resp.status_code == 200, resp.data
    data = resp.json()
    exported_ids = {row["id"] for row in data["MCPTool"]}
    assert exported_ids == {mcp_tool_a.id, mcp_tool_a2.id}


@pytest.mark.django_db
def test_pythoncodetool_bulk_export_with_foreign_org_id_400(
    client_a, python_tool_a, org_b
):
    other_code = PythonCode.objects.create(code="x", entrypoint="main", libraries="")
    other_tool = PythonCodeTool.objects.create(
        name="theirs", description="", python_code=other_code, org=org_b
    )
    resp = client_a.post(
        "/api/python-code-tool/bulk-export/",
        {"ids": [python_tool_a.id, other_tool.id]},
        format="json",
    )
    assert resp.status_code == 400
    assert resp.json()["message"] == "Some entity IDs do not exist"


@pytest.mark.django_db
def test_mcptool_bulk_export_with_foreign_org_id_400(client_a, mcp_tool_a, org_b):
    other_tool = McpTool.objects.create(
        name="theirs", transport="t", tool_name="x", org=org_b
    )
    resp = client_a.post(
        "/api/mcp-tools/bulk-export/",
        {"ids": [mcp_tool_a.id, other_tool.id]},
        format="json",
    )
    assert resp.status_code == 400
    assert resp.json()["message"] == "Some entity IDs do not exist"


@pytest.mark.django_db
def test_pythoncodetool_bulk_export_with_nonexistent_id_400(client_a, python_tool_a):
    resp = client_a.post(
        "/api/python-code-tool/bulk-export/",
        {"ids": [python_tool_a.id, python_tool_a.id + 999999]},
        format="json",
    )
    assert resp.status_code == 400
    assert resp.json()["message"] == "Some entity IDs do not exist"


@pytest.mark.django_db
def test_pythoncodetool_bulk_export_includes_builtin_tool(
    client_a, python_tool_a, builtin_python_tool
):
    # Built-in tools (org=None) are globally visible, matching the single
    # `export` action's get_object() behavior via global_visibility_q —
    # they must not be rejected as "doesn't exist" during bulk export.
    resp = client_a.post(
        "/api/python-code-tool/bulk-export/",
        {"ids": [python_tool_a.id, builtin_python_tool.id]},
        format="json",
    )
    assert resp.status_code == 200, resp.data
    data = resp.json()
    exported_ids = {row["id"] for row in data["PythonCodeTool"]}
    assert exported_ids == {python_tool_a.id, builtin_python_tool.id}


# ---- round-trip import ----


@pytest.mark.django_db
def test_pythoncodetool_import_recreates_tool_and_reattaches_labels(
    client_a, python_tool_a, org_a
):
    export_resp = client_a.get(f"/api/python-code-tool/{python_tool_a.id}/export/")
    assert export_resp.status_code == 200

    file = _as_upload(export_resp.content, "python_tool.json")
    count_before = PythonCodeTool.objects.count()

    resp = client_a.post(
        "/api/python-code-tool/import/",
        {"file": file, "import_labels": "true"},
        format="multipart",
    )
    assert resp.status_code == 200, resp.data
    assert PythonCodeTool.objects.count() == count_before + 1

    new_tool = (
        PythonCodeTool.objects.filter(org=org_a)
        .exclude(id=python_tool_a.id)
        .latest("id")
    )
    assert new_tool.python_code.code == python_tool_a.python_code.code
    label_names = set(
        new_tool.labels.filter(scope=Label.Scope.TOOL).values_list("name", flat=True)
    )
    assert label_names == {"Billing"}


@pytest.mark.django_db
def test_mcptool_import_recreates_tool_and_reattaches_labels(
    client_a, mcp_tool_a, org_a
):
    export_resp = client_a.get(f"/api/mcp-tools/{mcp_tool_a.id}/export/")
    assert export_resp.status_code == 200

    file = _as_upload(export_resp.content, "mcp_tool.json")
    count_before = McpTool.objects.count()

    resp = client_a.post(
        "/api/mcp-tools/import/",
        {"file": file, "import_labels": "true"},
        format="multipart",
    )
    assert resp.status_code == 200, resp.data
    assert McpTool.objects.count() == count_before + 1

    new_tool = McpTool.objects.filter(org=org_a).exclude(id=mcp_tool_a.id).latest("id")
    label_names = set(
        new_tool.labels.filter(scope=Label.Scope.TOOL).values_list("name", flat=True)
    )
    assert label_names == {"Billing"}


@pytest.mark.django_db
def test_pythoncodetool_import_labels_false_skips_labels(client_a, python_tool_a):
    export_resp = client_a.get(f"/api/python-code-tool/{python_tool_a.id}/export/")
    file = _as_upload(export_resp.content, "python_tool.json")

    resp = client_a.post(
        "/api/python-code-tool/import/",
        {"file": file, "import_labels": "false"},
        format="multipart",
    )
    assert resp.status_code == 200, resp.data

    new_tool = PythonCodeTool.objects.exclude(id=python_tool_a.id).latest("id")
    assert new_tool.labels.count() == 0


@pytest.mark.django_db
def test_pythoncodetool_import_labels_omitted_defaults_to_attaching_labels(
    client_a, python_tool_a
):
    export_resp = client_a.get(f"/api/python-code-tool/{python_tool_a.id}/export/")
    file = _as_upload(export_resp.content, "python_tool.json")

    resp = client_a.post(
        "/api/python-code-tool/import/",
        {"file": file},
        format="multipart",
    )
    assert resp.status_code == 200, resp.data

    new_tool = PythonCodeTool.objects.exclude(id=python_tool_a.id).latest("id")
    label_names = set(
        new_tool.labels.filter(scope=Label.Scope.TOOL).values_list("name", flat=True)
    )
    assert label_names == {"Billing"}


@pytest.mark.django_db
def test_mcptool_import_labels_false_skips_labels(client_a, mcp_tool_a):
    export_resp = client_a.get(f"/api/mcp-tools/{mcp_tool_a.id}/export/")
    file = _as_upload(export_resp.content, "mcp_tool.json")

    resp = client_a.post(
        "/api/mcp-tools/import/",
        {"file": file, "import_labels": "false"},
        format="multipart",
    )
    assert resp.status_code == 200, resp.data

    new_tool = McpTool.objects.exclude(id=mcp_tool_a.id).latest("id")
    assert new_tool.labels.count() == 0


# ---- cross-org isolation ----


@pytest.mark.django_db
def test_pythoncodetool_export_cross_org_404(client_a, org_b):
    other_code = PythonCode.objects.create(code="x", entrypoint="main", libraries="")
    other_tool = PythonCodeTool.objects.create(
        name="theirs", description="", python_code=other_code, org=org_b
    )
    resp = client_a.get(f"/api/python-code-tool/{other_tool.id}/export/")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_mcptool_export_cross_org_404(client_a, org_b):
    other_tool = McpTool.objects.create(
        name="theirs", transport="t", tool_name="x", org=org_b
    )
    resp = client_a.get(f"/api/mcp-tools/{other_tool.id}/export/")
    assert resp.status_code == 404


def _as_upload(content: bytes, filename: str):
    from io import BytesIO

    f = BytesIO(content)
    f.name = filename
    f.seek(0)
    return f


# ---- built-in role coverage (EST-3207 / migration 0210) ----


@pytest.fixture
def builtin_role(db, request):
    role_name = request.param
    return Role.objects.get(name=role_name, is_built_in=True, org__isnull=True)


@pytest.fixture
def builtin_role_client(db, org_a, builtin_role):
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.create_user(
        email=f"{builtin_role.name.lower().replace(' ', '_')}@example.com",
        password="StrongPass123!",
    )
    OrganizationUser.objects.create(user=user, org=org_a, role=builtin_role)
    c = APIClient()
    c.force_authenticate(user=user)
    c.credentials(HTTP_X_ORGANIZATION_ID=str(org_a.id))
    return c


@pytest.mark.django_db
@pytest.mark.parametrize("builtin_role", ["Org Admin", "Member"], indirect=True)
def test_builtin_role_can_export_python_code_tool(builtin_role_client, python_tool_a):
    resp = builtin_role_client.get(f"/api/python-code-tool/{python_tool_a.id}/export/")
    assert resp.status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("builtin_role", ["Org Admin", "Member"], indirect=True)
def test_builtin_role_can_export_mcp_tool(builtin_role_client, mcp_tool_a):
    resp = builtin_role_client.get(f"/api/mcp-tools/{mcp_tool_a.id}/export/")
    assert resp.status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("builtin_role", ["Org Admin", "Member"], indirect=True)
def test_builtin_role_can_import_python_code_tool(
    builtin_role_client, python_tool_a, client_a
):
    # Export with the (already-authorized) custom-role client to build the
    # upload payload, then verify the built-in role can perform the import
    # (import_entity requires Permission.CREATE, which both roles already
    # had before this migration — this asserts no regression).
    export_resp = client_a.get(f"/api/python-code-tool/{python_tool_a.id}/export/")
    assert export_resp.status_code == 200
    file = _as_upload(export_resp.content, "python_tool.json")

    resp = builtin_role_client.post(
        "/api/python-code-tool/import/",
        {"file": file, "import_labels": "true"},
        format="multipart",
    )
    assert resp.status_code == 200, resp.data


@pytest.mark.django_db
@pytest.mark.parametrize("builtin_role", ["Org Admin", "Member"], indirect=True)
def test_builtin_role_can_import_mcp_tool(builtin_role_client, mcp_tool_a, client_a):
    export_resp = client_a.get(f"/api/mcp-tools/{mcp_tool_a.id}/export/")
    assert export_resp.status_code == 200
    file = _as_upload(export_resp.content, "mcp_tool.json")

    resp = builtin_role_client.post(
        "/api/mcp-tools/import/",
        {"file": file, "import_labels": "true"},
        format="multipart",
    )
    assert resp.status_code == 200, resp.data
