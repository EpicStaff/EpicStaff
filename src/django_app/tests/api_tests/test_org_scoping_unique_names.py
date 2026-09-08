"""Per-org unique name/custom_name fields must return a clean 400 on a duplicate
within the same org (not a DB IntegrityError / 500), and allow the same name in a
different org. Covers the fields whose uniqueness moved from field-level
`unique=True` to a per-org UniqueConstraint (PR #593)."""

import pytest
from rest_framework.test import APIClient

from tables.models import Graph
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


@pytest.mark.django_db
def test_python_code_tool_duplicate_name_returns_400(client_a, org_a):
    code = PythonCode.objects.create(code="x", entrypoint="main")
    PythonCodeTool.objects.create(
        name="dup", description="d", python_code=code, org=org_a
    )
    resp = client_a.post("/api/python-code-tool/", _py_payload("dup"), format="json")
    assert resp.status_code == 400
    assert "already exists" in str(resp.data)


# ---- EST-4000: a custom PythonCodeTool must not be able to shadow a built-in ----


@pytest.mark.django_db
def test_python_code_tool_create_named_like_built_in_returns_400(client_a, org_a):
    built_in_code = PythonCode.objects.create(code="x", entrypoint="main")
    PythonCodeTool.objects.create(
        name="SerperDevTool",
        description="d",
        python_code=built_in_code,
        built_in=True,
        org=None,
    )
    resp = client_a.post(
        "/api/python-code-tool/", _py_payload("SerperDevTool"), format="json"
    )
    assert resp.status_code == 400
    # The project's global exception handler (utils/exception_handler.py)
    # wraps every serializer ValidationError into {status_code, code,
    # message} — the same envelope every other duplicate-name test in this
    # file asserts against — so the field-keyed detail is only visible
    # inside the stringified `message`, not at `resp.data["name"]`.
    assert "built-in tool with this name" in str(resp.data)


@pytest.mark.django_db
def test_python_code_tool_rename_to_built_in_name_returns_400(client_a, org_a):
    built_in_code = PythonCode.objects.create(code="x", entrypoint="main")
    PythonCodeTool.objects.create(
        name="SerperDevTool",
        description="d",
        python_code=built_in_code,
        built_in=True,
        org=None,
    )
    own_code = PythonCode.objects.create(code="y", entrypoint="main")
    own_tool = PythonCodeTool.objects.create(
        name="MyTool", description="d", python_code=own_code, org=org_a
    )
    resp = client_a.patch(
        f"/api/python-code-tool/{own_tool.id}/",
        {"name": "SerperDevTool"},
        format="json",
    )
    assert resp.status_code == 400
    assert "built-in tool with this name" in str(resp.data)


@pytest.mark.django_db
def test_python_code_tool_rename_to_own_current_name_is_allowed(client_a, org_a):
    """The validator excludes `instance.pk` on both the per-org and the
    built-in check, so a no-op rename must not 400."""
    code = PythonCode.objects.create(code="x", entrypoint="main")
    tool = PythonCodeTool.objects.create(
        name="MyTool", description="d", python_code=code, org=org_a
    )
    resp = client_a.patch(
        f"/api/python-code-tool/{tool.id}/",
        {"name": "MyTool", "description": "new desc"},
        format="json",
    )
    assert resp.status_code == 200, resp.data


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
