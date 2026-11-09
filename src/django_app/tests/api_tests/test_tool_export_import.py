import json

import pytest
from rest_framework.test import APIClient

from tables.models.label_models import Label
from tables.models.mcp_models import McpTool
from tables.models.python_models import PythonCode, PythonCodeTool
from rbac.models import Organization, OrganizationUser, Role
from rbac.models.enums import Permission, ResourceType
from rbac.models.role import RolePermission
from tables.models import TransferJob
from tables.services.secrets import secret_service
from tests.transfer_job_helpers import FinishedExport, export_via_job


# ---- fixtures ----
#
# Both built-in roles now carry the EXPORT bit (16) on the TOOLS resource
# (migration 0210_seed_tools_export_permission): "Org Admin" is
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
        code="def main(): return 1", entrypoint="main"
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


@pytest.fixture
def mcp_tool_with_auth_a(org_a, tool_label_a):
    secret = secret_service.create(
        text="Bearer sk-super-secret-token", org=org_a, name="MCP_AUTH_SECRET_A"
    )
    tool = McpTool.objects.create(
        name="McpToolWithAuthA",
        transport="https://example.com/mcp-secret",
        tool_name="do_secret_thing",
        auth_secret=secret,
        org=org_a,
    )
    tool.labels.add(tool_label_a)
    return tool


@pytest.fixture
def python_tool_a2(org_a, tool_label_a):
    code = PythonCode.objects.create(
        code="def main(): return 2", entrypoint="main"
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
        code="def main(): return 3", entrypoint="main"
    )
    return PythonCodeTool.objects.create(
        name="BuiltInPyTool",
        description="builtin",
        python_code=code,
        org=None,
        built_in=True,
    )


@pytest.fixture
def user_b(db, django_user_model, org_b, exporter_role_a):
    # `exporter_role_a` is bound to org_a; org_b needs its own role instance
    # with the same permission shape.
    role_b = Role.objects.create(name="ToolExporterB", org=org_b, is_built_in=False)
    RolePermission.objects.create(
        role=role_b,
        resource_type=ResourceType.TOOLS,
        permissions=int(Permission.CREATE | Permission.READ | Permission.EXPORT),
    )
    user = django_user_model.objects.create_user(
        email="exporter_b@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org_b, role=role_b)
    return user


@pytest.fixture
def client_b(user_b, org_b):
    c = APIClient()
    c.force_authenticate(user=user_b)
    c.credentials(HTTP_X_ORGANIZATION_ID=str(org_b.id))
    return c


@pytest.fixture
def shared_built_in_tool_with_both_orgs_labels(org_a, org_b):
    code = PythonCode.objects.create(
        code="def main(): return 1", entrypoint="main"
    )
    tool = PythonCodeTool.objects.create(
        name="SharedBuiltIn",
        description="desc",
        python_code=code,
        org=None,
        built_in=True,
    )
    label_a = Label.objects.create(name="OrgALabel", org=org_a, scope=Label.Scope.TOOL)
    label_b = Label.objects.create(name="OrgBLabel", org=org_b, scope=Label.Scope.TOOL)
    tool.labels.set([label_a, label_b])
    return tool


def _as_upload(content: bytes, filename: str):
    from io import BytesIO

    f = BytesIO(content)
    f.name = filename
    f.seek(0)
    return f


class ToolKind:
    def __init__(self, name, url, export_key, model, fixture, second_fixture, make_foreign):
        self.name, self.url, self.export_key, self.model = name, url, export_key, model
        self.fixture, self.second_fixture, self.make_foreign = fixture, second_fixture, make_foreign

    def __repr__(self):
        return self.name

    def start_export(self, client, ids):
        return client.post(f"{self.url}export-jobs/", {"ids": ids}, format="json")

    def export(self, client, *tools) -> FinishedExport:
        """Export `tools` through an export job and return its finished job and archive."""
        return export_via_job(client, f"{self.url}export-jobs/", {"ids": [tool.id for tool in tools]})

    def import_(self, client, content, *, filename="tool.zip", **fields):
        return client.post(
            f"{self.url}import/", {"file": _as_upload(content, filename), **fields}, format="multipart"
        )

    def import_json(self, client, payload: dict, **fields):
        """Import `payload` as the plain `.json` an export made before archives."""
        return self.import_(client, json.dumps(payload).encode(), filename="tool.json", **fields)


def _foreign_python_tool(org):
    code = PythonCode.objects.create(code="x", entrypoint="main")
    return PythonCodeTool.objects.create(name="theirs", description="", python_code=code, org=org)


TOOL_KINDS = [
    ToolKind("python", "/api/python-code-tool/", "PythonCodeTool", PythonCodeTool, "python_tool_a", "python_tool_a2", _foreign_python_tool),
    ToolKind("mcp", "/api/mcp-tools/", "MCPTool", McpTool, "mcp_tool_a", "mcp_tool_a2",
             lambda org: McpTool.objects.create(name="theirs", transport="t", tool_name="x", org=org)),
]
EACH_KIND = pytest.mark.parametrize("kind", TOOL_KINDS, ids=repr)


# ---- export ----


@pytest.mark.django_db
@EACH_KIND
def test_export_includes_labels_and_no_favorite_key(request, client_a, kind):
    tool = request.getfixturevalue(kind.fixture)

    exported = kind.export(client_a, tool)

    assert exported.job.status == TransferJob.Status.COMPLETED, exported.job.error
    tool_data = exported.envelope[kind.export_key][0]
    assert tool_data["labels"] == [*tool.labels.values_list("id", flat=True)]
    assert "favorite" not in tool_data
    assert "is_favorite" not in tool_data


@pytest.mark.django_db
@EACH_KIND
def test_bulk_export_covers_all_ids(request, client_a, kind):
    tools = [request.getfixturevalue(kind.fixture), request.getfixturevalue(kind.second_fixture)]

    exported = kind.export(client_a, *tools)

    assert exported.job.status == TransferJob.Status.COMPLETED, exported.job.error
    assert {row["id"] for row in exported.envelope[kind.export_key]} == {tool.id for tool in tools}
    assert exported.job.display_name == f"2 {'tools' if kind.name == 'python' else 'MCP tools'}"


@pytest.mark.django_db
@EACH_KIND
@pytest.mark.parametrize("other", ["other-org", "missing"])
def test_export_with_an_id_outside_the_org_is_not_found(request, client_a, org_b, kind, other):
    tool = request.getfixturevalue(kind.fixture)
    other_id = kind.make_foreign(org_b).id if other == "other-org" else tool.id + 999999

    resp = kind.start_export(client_a, [tool.id, other_id])

    # The same 404 for another org's id and a missing one: nothing tells them apart.
    assert resp.status_code == 404
    assert resp.json()["code"] == "export_entities_not_found"
    assert not TransferJob.objects.exists()


@pytest.mark.django_db
def test_pythoncodetool_export_includes_builtin_tool(client_a, python_tool_a, builtin_python_tool):
    # Built-in tools (org=None) are visible to every org, so they are exportable
    # like the org's own tools rather than refused as missing.
    exported = TOOL_KINDS[0].export(client_a, python_tool_a, builtin_python_tool)

    assert exported.job.status == TransferJob.Status.COMPLETED, exported.job.error
    exported_ids = {row["id"] for row in exported.envelope["PythonCodeTool"]}
    assert exported_ids == {python_tool_a.id, builtin_python_tool.id}


@pytest.mark.django_db
def test_a_lone_builtin_tool_export_is_named_after_it(client_a, builtin_python_tool):
    exported = TOOL_KINDS[0].export(client_a, builtin_python_tool)

    assert exported.job.status == TransferJob.Status.COMPLETED, exported.job.error
    assert exported.job.display_name == builtin_python_tool.name
    assert exported.job.file_name.startswith("python_code_tool_")
    assert exported.job.file_name.endswith(".zip")


@pytest.mark.django_db
def test_mcptool_export_does_not_leak_auth_secret(client_a, mcp_tool_with_auth_a):
    """Exporting an MCP tool must never include the `auth` secret."""
    exported = TOOL_KINDS[1].export(client_a, mcp_tool_with_auth_a)

    tool_data = exported.envelope["MCPTool"][0]
    assert "auth" not in tool_data
    assert all(b"sk-super-secret-token" not in member for member in exported.members.values())


@pytest.mark.django_db
def test_mcptool_import_after_export_does_not_carry_over_auth(
    client_a, mcp_tool_with_auth_a, org_a
):
    """
    Re-importing a tool exported with an auth secret must not resurrect the
    secret: the imported copy comes back with auth unset, and the user is
    expected to re-enter it manually (secure-by-default behavior).
    """
    exported = TOOL_KINDS[1].export(client_a, mcp_tool_with_auth_a)

    resp = client_a.post(
        "/api/mcp-tools/import/",
        {"file": exported.upload(), "import_labels": "true"},
        format="multipart",
    )
    assert resp.status_code == 200, resp.data

    new_tool = (
        McpTool.objects.filter(org=org_a)
        .exclude(id=mcp_tool_with_auth_a.id)
        .latest("id")
    )
    assert new_tool.auth_secret_id is None
    assert new_tool.transport == mcp_tool_with_auth_a.transport


# ---- round-trip import ----


@pytest.mark.django_db
@EACH_KIND
@pytest.mark.parametrize(
    ("fields", "expected_labels"),
    [({"import_labels": "true"}, {"Billing"}), ({}, {"Billing"}), ({"import_labels": "false"}, set())],
    ids=["labels", "labels-by-default", "no-labels"],
)
@pytest.mark.parametrize("file_kind", ["zip", "json"])
def test_import_recreates_the_tool_with_its_labels_when_asked(
    request, client_a, org_a, kind, fields, expected_labels, file_kind
):
    tool = request.getfixturevalue(kind.fixture)
    exported = kind.export(client_a, tool)
    count_before = kind.model.objects.count()

    if file_kind == "zip":
        resp = kind.import_(client_a, exported.archive, **fields)
    else:
        resp = kind.import_json(client_a, exported.envelope, **fields)

    assert resp.status_code == 200, resp.data
    assert kind.model.objects.count() == count_before + 1
    new_tool = kind.model.objects.filter(org=org_a).exclude(id=tool.id).latest("id")
    assert set(new_tool.labels.filter(scope=Label.Scope.TOOL).values_list("name", flat=True)) == expected_labels
    if kind.name == "python":
        assert new_tool.python_code.code == tool.python_code.code


@pytest.mark.django_db
@EACH_KIND
def test_import_ignores_a_stale_created_by_reference(request, client_a, kind):
    """`created_by` is server-managed: a payload naming a user that no longer exists
    must be ignored on import, not validated into a 400 ("Invalid pk")."""
    payload = kind.export(client_a, request.getfixturevalue(kind.fixture)).envelope
    payload[kind.export_key][0]["created_by"] = 999999999

    resp = kind.import_json(client_a, payload, import_labels="false")

    assert resp.status_code == 200, resp.data


# ---- exporting a shared built-in tool must not leak other orgs' label names ----


@pytest.mark.django_db
def test_export_of_a_shared_built_in_tool_carries_only_the_callers_labels(
    client_b, org_b, shared_built_in_tool_with_both_orgs_labels
):
    tool = shared_built_in_tool_with_both_orgs_labels

    exported = TOOL_KINDS[0].export(client_b, tool)

    assert exported.job.status == TransferJob.Status.COMPLETED, exported.job.error
    assert exported.envelope["PythonCodeTool"][0]["labels"] == [
        *tool.labels.filter(org_id=org_b.id).values_list("id", flat=True)
    ]
    assert b"OrgALabel" not in exported.members["export.json"]


# ---- built-in role coverage (migration 0210) ----


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
@EACH_KIND
@pytest.mark.parametrize("builtin_role", ["Org Admin", "Member"], indirect=True)
def test_builtin_roles_can_export_and_import_tools(request, builtin_role_client, client_a, kind):
    tool = request.getfixturevalue(kind.fixture)

    exported = kind.export(builtin_role_client, tool)
    imported = kind.import_(builtin_role_client, exported.archive, import_labels="true")

    assert exported.job.status == TransferJob.Status.COMPLETED, exported.job.error
    assert imported.status_code == 200, imported.data


@pytest.mark.django_db
def test_mcptool_import_rejects_non_http_transport(client_a, mcp_tool_a, org_a):
    payload = TOOL_KINDS[1].export(client_a, mcp_tool_a).envelope
    payload["MCPTool"][0]["transport"] = "/tmp/a.py"
    tool_count_before_import = McpTool.objects.filter(org=org_a).count()

    file = _as_upload(json.dumps(payload).encode(), "mcp_tool.json")
    resp = client_a.post(
        "/api/mcp-tools/import/",
        {"file": file, "import_labels": "false"},
        format="multipart",
    )

    assert resp.status_code == 400, resp.data
    assert "transport" in resp.data["message"]
    assert McpTool.objects.filter(org=org_a).count() == tool_count_before_import


# ---- an imported python tool's description is cleaned like the API route cleans it ----


def _import_python_tool_with_description(client, org, tool, description):
    python_kind = TOOL_KINDS[0]
    payload = python_kind.export(client, tool).envelope
    payload["PythonCodeTool"][0]["description"] = description

    resp = python_kind.import_json(client, payload, import_labels="false")

    assert resp.status_code == 200, resp.data
    return PythonCodeTool.objects.filter(org=org).exclude(id=tool.id).latest("id")


@pytest.mark.django_db
def test_import_stores_a_python_tool_description_without_control_characters_and_capped(
    client_a, org_a, python_tool_a
):
    imported = _import_python_tool_with_description(
        client_a, org_a, python_tool_a, "Line one\x1b[31m\x07\n" + "x" * 2000
    )

    assert imported.description == "Line one[31m" + "x" * 1012


@pytest.mark.django_db
def test_a_description_of_only_control_characters_is_rejected_on_import_and_by_the_api(
    client_a, org_a, python_tool_a
):
    python_kind = TOOL_KINDS[0]
    payload = python_kind.export(client_a, python_tool_a).envelope
    payload["PythonCodeTool"][0]["description"] = "\x1b\x07"
    tool_count_before = PythonCodeTool.objects.filter(org=org_a).count()

    imported = python_kind.import_json(client_a, payload, import_labels="false")
    created = client_a.post(
        "/api/python-code-tool/",
        {
            "name": "via-api",
            "description": "\x1b\x07",
            "python_code": {"code": "x", "entrypoint": "main", "libraries": []},
        },
        format="json",
    )

    assert imported.status_code == 400, imported.data
    assert created.status_code == 400, created.data
    assert "Description must contain visible text." in str(imported.data)
    assert "Description must contain visible text." in str(created.data)
    assert PythonCodeTool.objects.filter(org=org_a).count() == tool_count_before


# ---- the synchronous exports are gone ----


@pytest.mark.django_db
@EACH_KIND
def test_the_synchronous_tool_exports_are_gone(request, client_a, kind):
    tool = request.getfixturevalue(kind.fixture)

    single = client_a.get(f"{kind.url}{tool.id}/export/")
    bulk = client_a.post(f"{kind.url}bulk-export/", {"ids": [tool.id]}, format="json")

    assert single.status_code == 404
    # Read as the detail route of a tool called "bulk-export": refused, never served.
    assert bulk.status_code in {403, 404, 405}
