"""Per-org unique name/custom_name fields must return a clean 400 on a duplicate
within the same org (not a DB IntegrityError / 500), and allow the same name in a
different org. Covers the fields whose uniqueness moved from field-level
`unique=True` to a per-org UniqueConstraint (PR #593)."""

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from tables.models import Crew, Graph  # noqa: F401  (import sanity)
from tables.models.embedding_models import EmbeddingConfig
from tables.models.llm_models import LLMConfig
from tables.models.mcp_models import McpTool
from tables.models.python_models import PythonCode, PythonCodeTool, PythonCodeToolConfig
from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="Org A")


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="Org B")


def _admin_client(django_user_model, org, email):
    role = Role.objects.get(
        name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True
    )
    user = django_user_model.objects.create_user(email=email, password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=org, role=role)
    c = APIClient()
    c.force_authenticate(user=user)
    c.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return c


@pytest.fixture
def client_a(db, django_user_model, org_a):
    return _admin_client(django_user_model, org_a, "admin_a@example.com")


# ---- LLMConfig.custom_name ----


@pytest.mark.django_db
def test_llm_config_duplicate_name_returns_400(client_a, org_a, org_b):
    LLMConfig.objects.create(custom_name="dup", org=org_a)
    resp = client_a.post("/api/llm-configs/", {"custom_name": "dup"}, format="json")
    assert resp.status_code == 400
    assert "already exists" in str(resp.data)


@pytest.mark.django_db
def test_llm_config_same_name_other_org_ok(client_a, org_a, org_b):
    LLMConfig.objects.create(custom_name="dup", org=org_b)  # different org
    resp = client_a.post("/api/llm-configs/", {"custom_name": "dup"}, format="json")
    assert resp.status_code == 201, resp.data


# ---- EmbeddingConfig.custom_name ----


@pytest.mark.django_db
def test_embedding_config_duplicate_name_returns_400(client_a, org_a):
    EmbeddingConfig.objects.create(custom_name="dup", org=org_a)
    resp = client_a.post(
        "/api/embedding-configs/", {"custom_name": "dup"}, format="json"
    )
    assert resp.status_code == 400
    assert "already exists" in str(resp.data)


# ---- McpTool.name ----


@pytest.mark.django_db
def test_mcp_tool_duplicate_name_returns_400(client_a, org_a):
    McpTool.objects.create(name="dup", org=org_a)
    resp = client_a.post("/api/mcp-tools/", {"name": "dup"}, format="json")
    assert resp.status_code == 400
    assert "already exists" in str(resp.data)


# ---- PythonCodeTool.name ----


def _py_payload(name):
    return {
        "name": name,
        "description": "d",
        "python_code": {"code": "x", "entrypoint": "main", "libraries": []},
    }


def _make_tool(*, org=None, built_in=False, name="tool"):
    code = PythonCode.objects.create(code="x", entrypoint="main")
    return PythonCodeTool.objects.create(
        name=name,
        description="",
        python_code=code,
        built_in=built_in,
        org=org,
    )


@pytest.mark.django_db
def test_python_code_tool_duplicate_name_returns_400(client_a, org_a):
    code = PythonCode.objects.create(code="x", entrypoint="main")
    PythonCodeTool.objects.create(
        name="dup", description="d", python_code=code, org=org_a
    )
    resp = client_a.post("/api/python-code-tool/", _py_payload("dup"), format="json")
    assert resp.status_code == 400
    assert "already exists" in str(resp.data)


@pytest.mark.django_db
def test_python_code_tool_create_with_name_of_soft_deleted_tool_succeeds(
    client_a, org_a
):
    """The (org, name) unique constraint only applies to active rows — soft-deleting
    a tool must free up its name for reuse within the same org."""
    create_resp = client_a.post(
        "/api/python-code-tool/", _py_payload("dup"), format="json"
    )
    assert create_resp.status_code == 201, create_resp.data
    tool_id = create_resp.data["id"]

    delete_resp = client_a.delete(f"/api/python-code-tool/{tool_id}/")
    assert delete_resp.status_code == 204, delete_resp.data

    recreate_resp = client_a.post(
        "/api/python-code-tool/", _py_payload("dup"), format="json"
    )
    assert recreate_resp.status_code == 201, recreate_resp.data
    assert recreate_resp.data["name"] == "dup"


@pytest.mark.django_db
def test_python_code_tool_delete_soft_delete_default_leaves_row_in_all_objects(
    client_a, org_a
):
    """SOFT_DELETE=True (default): DELETE hides the tool from `objects` but keeps
    it in `all_objects` with `is_soft_deleted=True` and `soft_deleted_at` set."""
    tool = _make_tool(org=org_a, built_in=False, name="to-delete")

    resp = client_a.delete(f"/api/python-code-tool/{tool.id}/")

    assert resp.status_code == 204, resp.data
    assert not PythonCodeTool.objects.filter(id=tool.id).exists()
    assert PythonCodeTool.all_objects.filter(id=tool.id).exists()
    deleted_tool = PythonCodeTool.all_objects.get(id=tool.id)
    assert deleted_tool.is_soft_deleted is True
    assert deleted_tool.soft_deleted_at is not None


@pytest.mark.django_db
@override_settings(SOFT_DELETE=False)
def test_python_code_tool_delete_hard_deletes_when_soft_delete_disabled(
    client_a, org_a
):
    """SOFT_DELETE=False: DELETE removes the row entirely, even from `all_objects`."""
    tool = _make_tool(org=org_a, built_in=False, name="to-hard-delete")

    resp = client_a.delete(f"/api/python-code-tool/{tool.id}/")

    assert resp.status_code == 204, resp.data
    assert not PythonCodeTool.all_objects.filter(id=tool.id).exists()


@pytest.mark.django_db
def test_python_code_tool_builtin_cannot_be_deleted_with_soft_delete_enabled(client_a):
    """Built-in tool deletion protection holds regardless of SOFT_DELETE — the
    guard in PythonCodeToolViewSet.destroy() runs before any .delete() call."""
    builtin_tool = _make_tool(built_in=True, org=None, name="builtin")

    resp = client_a.delete(f"/api/python-code-tool/{builtin_tool.id}/")

    assert resp.status_code == 400
    untouched = PythonCodeTool.all_objects.get(id=builtin_tool.id)
    assert untouched.is_soft_deleted is False
    assert untouched.soft_deleted_at is None


@pytest.mark.django_db
@override_settings(SOFT_DELETE=False)
def test_python_code_tool_builtin_cannot_be_deleted_with_soft_delete_disabled(
    client_a,
):
    """Same guard holds when SOFT_DELETE=False — the built-in tool must not be
    hard-deleted either."""
    builtin_tool = _make_tool(built_in=True, org=None, name="builtin-hard")

    resp = client_a.delete(f"/api/python-code-tool/{builtin_tool.id}/")

    assert resp.status_code == 400
    assert PythonCodeTool.all_objects.filter(id=builtin_tool.id).exists()


# ---- PythonCodeToolConfig (tool, name) per org ----


@pytest.mark.django_db
def test_python_code_tool_config_duplicate_returns_400(client_a, org_a):
    code = PythonCode.objects.create(code="x", entrypoint="main")
    tool = PythonCodeTool.objects.create(
        name="t", description="d", python_code=code, org=org_a
    )
    PythonCodeToolConfig.objects.create(name="cfg", tool=tool, org=org_a)
    resp = client_a.post(
        "/api/python-code-tool-configs/",
        {"name": "cfg", "tool": tool.id, "configuration": {}},
        format="json",
    )
    assert resp.status_code == 400
    assert "already exists" in str(resp.data)


# ---- Graph.name (fixed earlier — regression guard) ----


@pytest.mark.django_db
def test_graph_duplicate_name_returns_400(client_a, org_a):
    Graph.objects.create(name="dup", metadata={"nodes": [], "edges": []}, org=org_a)
    resp = client_a.post(
        "/api/graphs/", {"name": "dup", "save_version": 1}, format="json"
    )
    assert resp.status_code == 400
    assert "already exists" in str(resp.data)
