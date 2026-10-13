"""Per-org unique name/custom_name fields must return a clean 400 on a duplicate
within the same org (not a DB IntegrityError / 500), and allow the same name in a
different org. Covers the fields whose uniqueness moved from field-level
`unique=True` to a per-org UniqueConstraint (PR #593), plus the python tool name
rules (no shadowing a built-in, soft-deleted names are free) and built-in tool
delete protection."""

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from tables.models import Graph
from tables.models.embedding_models import EmbeddingConfig
from tables.models.llm_models import LLMConfig
from tables.models.mcp_models import McpTool
from tables.models.python_models import PythonCode, PythonCodeTool, PythonCodeToolConfig
from rbac.models import Organization, OrganizationUser, Role
from rbac.models.enums import BuiltInRole

pytestmark = pytest.mark.django_db


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="Org A")


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="Org B")


@pytest.fixture
def client_a(db, django_user_model, org_a):
    user = django_user_model.objects.create_user(email="admin_a@example.com", password="StrongPass123!")
    role = Role.objects.get(name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True)
    OrganizationUser.objects.create(user=user, org=org_a, role=role)
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org_a.id))
    return client


def _tool(*, org=None, built_in=False, name="tool"):
    return PythonCodeTool.objects.create(
        name=name, description="d", python_code=PythonCode.objects.create(code="x", entrypoint="main"), built_in=built_in, org=org
    )


def _py_payload(name):
    return {"name": name, "description": "d", "python_code": {"code": "x", "entrypoint": "main", "libraries": []}}


def _tool_config(org):
    return PythonCodeToolConfig.objects.create(name="cfg", tool=_tool(org=org, name=f"t-{org.id}"), org=org)


# resource: create url, make an existing row named "dup" in org, the POST body for "dup" in org_a
NAMED = {
    "llm-config": ("/api/llm-configs/", lambda org: LLMConfig.objects.create(custom_name="dup", org=org), lambda existing: {"custom_name": "dup"}),
    "embedding-config": ("/api/embedding-configs/", lambda org: EmbeddingConfig.objects.create(custom_name="dup", org=org), lambda existing: {"custom_name": "dup"}),
    "mcp-tool": ("/api/mcp-tools/", lambda org: McpTool.objects.create(name="dup", org=org), lambda existing: {"name": "dup"}),
    "python-code-tool": ("/api/python-code-tool/", lambda org: _tool(org=org, name="dup"), lambda existing: _py_payload("dup")),
    "python-code-tool-config": ("/api/python-code-tool-configs/", _tool_config, lambda existing: {"name": "cfg", "tool": existing.tool_id, "configuration": {}}),
    "graph": ("/api/graphs/", lambda org: Graph.objects.create(name="dup", metadata={"nodes": [], "edges": []}, org=org), lambda existing: {"name": "dup", "save_version": 1}),
}


@pytest.mark.parametrize("resource", list(NAMED))
def test_a_name_taken_in_the_same_org_is_a_clean_400(client_a, org_a, resource):
    url, make, body = NAMED[resource]

    resp = client_a.post(url, body(make(org_a)), format="json")

    assert resp.status_code == 400
    assert "already exists" in str(resp.data)


def test_the_same_name_in_another_org_is_allowed(client_a, org_b):
    LLMConfig.objects.create(custom_name="dup", org=org_b)

    assert client_a.post("/api/llm-configs/", {"custom_name": "dup"}, format="json").status_code == 201


@pytest.mark.parametrize("write", ["create", "rename"])
def test_a_custom_tool_cannot_take_a_built_in_tools_name(client_a, org_a, write):
    _tool(built_in=True, name="SerperDevTool")

    if write == "create":
        resp = client_a.post("/api/python-code-tool/", _py_payload("SerperDevTool"), format="json")
    else:
        own = _tool(org=org_a, name="MyTool")
        resp = client_a.patch(f"/api/python-code-tool/{own.id}/", {"name": "SerperDevTool"}, format="json")

    assert resp.status_code == 400
    # The global exception handler wraps field errors into {status_code, code, message}.
    assert "built-in tool with this name" in str(resp.data)


def test_keeping_a_tools_own_name_on_update_is_allowed(client_a, org_a):
    tool = _tool(org=org_a, name="MyTool")

    resp = client_a.patch(f"/api/python-code-tool/{tool.id}/", {"name": "MyTool", "description": "new"}, format="json")

    assert resp.status_code == 200, resp.data


def test_a_soft_deleted_tools_name_can_be_reused(client_a):
    tool_id = client_a.post("/api/python-code-tool/", _py_payload("dup"), format="json").data["id"]

    assert client_a.delete(f"/api/python-code-tool/{tool_id}/").status_code == 204
    recreated = client_a.post("/api/python-code-tool/", _py_payload("dup"), format="json")

    assert recreated.status_code == 201, recreated.data
    assert recreated.data["name"] == "dup"


@pytest.mark.parametrize("soft_delete", [True, False])
def test_deleting_a_custom_tool_follows_the_soft_delete_setting(client_a, org_a, soft_delete):
    tool = _tool(org=org_a, name="to-delete")

    with override_settings(SOFT_DELETE=soft_delete):
        resp = client_a.delete(f"/api/python-code-tool/{tool.id}/")

    assert resp.status_code == 204, resp.data
    assert not PythonCodeTool.objects.filter(id=tool.id).exists()
    kept = PythonCodeTool.all_objects.filter(id=tool.id).first()
    assert (kept is not None) is soft_delete
    if soft_delete:
        assert kept.is_soft_deleted is True
        assert kept.soft_deleted_at is not None


@pytest.mark.parametrize("soft_delete", [True, False])
def test_a_built_in_tool_cannot_be_deleted(client_a, soft_delete):
    built_in = _tool(built_in=True, name="builtin")

    with override_settings(SOFT_DELETE=soft_delete):
        resp = client_a.delete(f"/api/python-code-tool/{built_in.id}/")

    assert resp.status_code == 400
    untouched = PythonCodeTool.all_objects.get(id=built_in.id)
    assert (untouched.is_soft_deleted, untouched.soft_deleted_at) == (False, None)
