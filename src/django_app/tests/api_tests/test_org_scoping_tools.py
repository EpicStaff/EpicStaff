import pytest
from rest_framework.test import APIClient

from tables.models.mcp_models import McpTool
from tables.models.python_models import (
    PythonCode,
    PythonCodeTool,
    PythonCodeToolConfig,
)
from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole


# ---- fixtures ----


@pytest.fixture
def role_member(db):
    return Role.objects.get(name=BuiltInRole.MEMBER, is_built_in=True, org__isnull=True)


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="Org A")


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="Org B")


@pytest.fixture
def member_a(db, django_user_model, org_a, role_member):
    user = django_user_model.objects.create_user(
        email="tm_a@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org_a, role=role_member)
    return user


@pytest.fixture
def client_a(member_a, org_a):  # Member: tools CRU
    c = APIClient()
    c.force_authenticate(user=member_a)
    c.credentials(HTTP_X_ORGANIZATION_ID=str(org_a.id))
    return c


def _results(resp):
    body = resp.data
    return body["results"] if isinstance(body, dict) and "results" in body else body


def _make_tool(*, org=None, built_in=False, name="tool"):
    code = PythonCode.objects.create(code="x", entrypoint="main")
    return PythonCodeTool.objects.create(
        name=name,
        description="",
        python_code=code,
        built_in=built_in,
        org=org,
    )


# ---- McpTool (strict) ----


@pytest.mark.django_db
def test_mcptool_list_only_active_org(client_a, org_a, org_b):
    McpTool.objects.create(name="mine", transport="t", tool_name="x", org=org_a)
    McpTool.objects.create(name="theirs", transport="t", tool_name="x", org=org_b)
    names = {m["name"] for m in _results(client_a.get("/api/mcp-tools/"))}
    assert "mine" in names and "theirs" not in names


@pytest.mark.django_db
def test_mcptool_create_lands_in_active_org(client_a, org_a):
    resp = client_a.post(
        "/api/mcp-tools/",
        {"name": "new", "transport": "http://x", "tool_name": "t"},
        format="json",
    )
    assert resp.status_code == 201, resp.data
    assert McpTool.objects.get(id=resp.data["id"]).org_id == org_a.id


@pytest.mark.django_db
def test_mcptool_detail_cross_org_404(client_a, org_b):
    other = McpTool.objects.create(
        name="theirs", transport="t", tool_name="x", org=org_b
    )
    assert client_a.get(f"/api/mcp-tools/{other.id}/").status_code == 404


# ---- PythonCodeTool (hybrid: built-in global + custom per-org) ----


@pytest.mark.django_db
def test_pythoncodetool_builtin_visible_to_every_org(client_a):
    _make_tool(built_in=True, org=None, name="builtin-tool")
    names = {t["name"] for t in _results(client_a.get("/api/python-code-tool/"))}
    assert "builtin-tool" in names


@pytest.mark.django_db
def test_pythoncodetool_custom_isolated_per_org(client_a, org_a, org_b):
    _make_tool(built_in=False, org=org_a, name="mine")
    _make_tool(built_in=False, org=org_b, name="theirs")
    names = {t["name"] for t in _results(client_a.get("/api/python-code-tool/"))}
    assert "mine" in names and "theirs" not in names


@pytest.mark.django_db
def test_pythoncodetool_create_lands_as_custom(client_a, org_a):
    resp = client_a.post(
        "/api/python-code-tool/",
        {
            "name": "custom-tool",
            "description": "d",
            "python_code": {"code": "x", "entrypoint": "main", "libraries": []},
        },
        format="json",
    )
    assert resp.status_code == 201, resp.data
    created = PythonCodeTool.objects.get(id=resp.data["id"])
    assert created.org_id == org_a.id
    assert created.built_in is False


# ---- PythonCodeToolConfig (strict; per-org even for a built-in tool) ----


@pytest.mark.django_db
def test_pythoncodetoolconfig_list_only_active_org(client_a, org_a, org_b):
    builtin = _make_tool(built_in=True, org=None, name="bt")
    PythonCodeToolConfig.objects.create(name="mine", tool=builtin, org=org_a)
    PythonCodeToolConfig.objects.create(name="theirs", tool=builtin, org=org_b)
    names = {
        c["name"] for c in _results(client_a.get("/api/python-code-tool-configs/"))
    }
    assert "mine" in names and "theirs" not in names


@pytest.mark.django_db
def test_pythoncodetoolconfig_create_lands_in_active_org(client_a, org_a):
    tool = _make_tool(built_in=True, org=None, name="bt")
    resp = client_a.post(
        "/api/python-code-tool-configs/",
        {"name": "cfg", "tool": tool.id, "configuration": {}},
        format="json",
    )
    assert resp.status_code == 201, resp.data
    assert PythonCodeToolConfig.objects.get(id=resp.data["id"]).org_id == org_a.id


# ---- PythonCode (child via referencing parents) ----


@pytest.mark.django_db
def test_pythoncode_of_own_custom_tool_visible(client_a, org_a):
    tool = _make_tool(built_in=False, org=org_a, name="mine")
    ids = {c["id"] for c in _results(client_a.get("/api/python-code/"))}
    assert tool.python_code_id in ids


@pytest.mark.django_db
def test_pythoncode_of_other_orgs_tool_hidden(client_a, org_b):
    tool = _make_tool(built_in=False, org=org_b, name="theirs")
    ids = {c["id"] for c in _results(client_a.get("/api/python-code/"))}
    assert tool.python_code_id not in ids


@pytest.mark.django_db
def test_pythoncode_of_builtin_tool_visible(client_a):
    tool = _make_tool(built_in=True, org=None, name="bt")
    ids = {c["id"] for c in _results(client_a.get("/api/python-code/"))}
    assert tool.python_code_id in ids


@pytest.mark.django_db
def test_pythoncode_unattached_is_hidden(client_a):
    # A standalone PythonCode with no parent matches no org branch of the
    # 4-way filter, so it is not visible (accepted trade-off of no own column).
    orphan = PythonCode.objects.create(code="orphan", entrypoint="main")
    ids = {c["id"] for c in _results(client_a.get("/api/python-code/"))}
    assert orphan.id not in ids
