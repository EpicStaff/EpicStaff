import pytest
from rest_framework.test import APIClient

from tables.models.favorite_models import McpToolFavorite, PythonCodeToolFavorite
from tables.models.mcp_models import McpTool
from tables.models.python_models import PythonCode, PythonCodeTool
from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole

PYTHON_TOOL_URL = "/api/python-code-tool/"
MCP_TOOL_URL = "/api/mcp-tools/"


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
        email="fav_a@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org_a, role=role_member)
    return user


@pytest.fixture
def member_a2(db, django_user_model, org_a, role_member):
    """A second member of org_a — for cross-user isolation assertions."""
    user = django_user_model.objects.create_user(
        email="fav_a2@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org_a, role=role_member)
    return user


@pytest.fixture
def client_a(member_a, org_a):
    client = APIClient()
    client.force_authenticate(user=member_a)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org_a.id))
    return client


@pytest.fixture
def client_a2(member_a2, org_a):
    client = APIClient()
    client.force_authenticate(user=member_a2)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org_a.id))
    return client


def _results(resp):
    body = resp.data
    return body["results"] if isinstance(body, dict) and "results" in body else body


def _make_python_tool(org, name="tool") -> PythonCodeTool:
    code = PythonCode.objects.create(code="x", entrypoint="main")
    return PythonCodeTool.objects.create(
        name=name, description="", python_code=code, org=org
    )


def _make_mcp_tool(org, name="mcp-tool") -> McpTool:
    return McpTool.objects.create(
        name=name, transport="https://example.com", tool_name="do_thing", org=org
    )


# ---- toggle: PythonCodeTool ----


@pytest.mark.django_db
def test_pythoncodetool_favorite_post_creates_favorite(client_a, member_a, org_a):
    tool = _make_python_tool(org_a)
    resp = client_a.post(f"{PYTHON_TOOL_URL}{tool.id}/favorite/")
    assert resp.status_code == 200
    assert PythonCodeToolFavorite.objects.filter(user=member_a, tool=tool).count() == 1


@pytest.mark.django_db
def test_pythoncodetool_favorite_post_idempotent(client_a, member_a, org_a):
    tool = _make_python_tool(org_a)
    resp1 = client_a.post(f"{PYTHON_TOOL_URL}{tool.id}/favorite/")
    resp2 = client_a.post(f"{PYTHON_TOOL_URL}{tool.id}/favorite/")
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert PythonCodeToolFavorite.objects.filter(user=member_a, tool=tool).count() == 1


@pytest.mark.django_db
def test_pythoncodetool_favorite_delete_removes_favorite(client_a, member_a, org_a):
    tool = _make_python_tool(org_a)
    client_a.post(f"{PYTHON_TOOL_URL}{tool.id}/favorite/")
    resp = client_a.delete(f"{PYTHON_TOOL_URL}{tool.id}/favorite/")
    assert resp.status_code == 200
    assert PythonCodeToolFavorite.objects.filter(user=member_a, tool=tool).count() == 0


@pytest.mark.django_db
def test_pythoncodetool_favorite_delete_idempotent(client_a, member_a, org_a):
    tool = _make_python_tool(org_a)
    resp1 = client_a.delete(f"{PYTHON_TOOL_URL}{tool.id}/favorite/")
    resp2 = client_a.delete(f"{PYTHON_TOOL_URL}{tool.id}/favorite/")
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert PythonCodeToolFavorite.objects.filter(user=member_a, tool=tool).count() == 0


# ---- toggle: McpTool ----


@pytest.mark.django_db
def test_mcptool_favorite_post_creates_favorite(client_a, member_a, org_a):
    tool = _make_mcp_tool(org_a)
    resp = client_a.post(f"{MCP_TOOL_URL}{tool.id}/favorite/")
    assert resp.status_code == 200
    assert McpToolFavorite.objects.filter(user=member_a, tool=tool).count() == 1


@pytest.mark.django_db
def test_mcptool_favorite_post_idempotent(client_a, member_a, org_a):
    tool = _make_mcp_tool(org_a)
    resp1 = client_a.post(f"{MCP_TOOL_URL}{tool.id}/favorite/")
    resp2 = client_a.post(f"{MCP_TOOL_URL}{tool.id}/favorite/")
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert McpToolFavorite.objects.filter(user=member_a, tool=tool).count() == 1


@pytest.mark.django_db
def test_mcptool_favorite_delete_removes_favorite(client_a, member_a, org_a):
    tool = _make_mcp_tool(org_a)
    client_a.post(f"{MCP_TOOL_URL}{tool.id}/favorite/")
    resp = client_a.delete(f"{MCP_TOOL_URL}{tool.id}/favorite/")
    assert resp.status_code == 200
    assert McpToolFavorite.objects.filter(user=member_a, tool=tool).count() == 0


@pytest.mark.django_db
def test_mcptool_favorite_delete_idempotent(client_a, member_a, org_a):
    tool = _make_mcp_tool(org_a)
    resp1 = client_a.delete(f"{MCP_TOOL_URL}{tool.id}/favorite/")
    resp2 = client_a.delete(f"{MCP_TOOL_URL}{tool.id}/favorite/")
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert McpToolFavorite.objects.filter(user=member_a, tool=tool).count() == 0


# ---- cross-user isolation ----


@pytest.mark.django_db
def test_pythoncodetool_favorite_is_per_user(client_a, client_a2, org_a):
    tool = _make_python_tool(org_a)
    client_a.post(f"{PYTHON_TOOL_URL}{tool.id}/favorite/")

    rows_a = {t["id"]: t for t in _results(client_a.get(PYTHON_TOOL_URL))}
    rows_a2 = {t["id"]: t for t in _results(client_a2.get(PYTHON_TOOL_URL))}

    assert rows_a[tool.id]["is_favorite"] is True
    assert rows_a2[tool.id]["is_favorite"] is False


@pytest.mark.django_db
def test_mcptool_favorite_is_per_user(client_a, client_a2, org_a):
    tool = _make_mcp_tool(org_a)
    client_a.post(f"{MCP_TOOL_URL}{tool.id}/favorite/")

    rows_a = {t["id"]: t for t in _results(client_a.get(MCP_TOOL_URL))}
    rows_a2 = {t["id"]: t for t in _results(client_a2.get(MCP_TOOL_URL))}

    assert rows_a[tool.id]["is_favorite"] is True
    assert rows_a2[tool.id]["is_favorite"] is False


# ---- cross-org isolation (mirrors test_mcptool_copy_cross_org_404) ----


@pytest.mark.django_db
def test_pythoncodetool_favorite_cross_org_404(client_a, org_b):
    other = _make_python_tool(org_b, name="theirs")
    resp = client_a.post(f"{PYTHON_TOOL_URL}{other.id}/favorite/")
    assert resp.status_code == 404
    assert not PythonCodeToolFavorite.objects.filter(tool=other).exists()


@pytest.mark.django_db
def test_mcptool_favorite_cross_org_404(client_a, org_b):
    other = _make_mcp_tool(org_b, name="theirs")
    resp = client_a.post(f"{MCP_TOOL_URL}{other.id}/favorite/")
    assert resp.status_code == 404
    assert not McpToolFavorite.objects.filter(tool=other).exists()


# ---- is_favorite field on list/detail ----


@pytest.mark.django_db
def test_pythoncodetool_is_favorite_in_list_and_detail(client_a, org_a):
    tool = _make_python_tool(org_a)
    client_a.post(f"{PYTHON_TOOL_URL}{tool.id}/favorite/")

    list_rows = {t["id"]: t for t in _results(client_a.get(PYTHON_TOOL_URL))}
    assert list_rows[tool.id]["is_favorite"] is True

    detail = client_a.get(f"{PYTHON_TOOL_URL}{tool.id}/")
    assert detail.data["is_favorite"] is True


@pytest.mark.django_db
def test_mcptool_is_favorite_in_list_and_detail(client_a, org_a):
    tool = _make_mcp_tool(org_a)
    client_a.post(f"{MCP_TOOL_URL}{tool.id}/favorite/")

    list_rows = {t["id"]: t for t in _results(client_a.get(MCP_TOOL_URL))}
    assert list_rows[tool.id]["is_favorite"] is True

    detail = client_a.get(f"{MCP_TOOL_URL}{tool.id}/")
    assert detail.data["is_favorite"] is True


# ---- ?is_favorite filter ----


@pytest.mark.django_db
def test_pythoncodetool_is_favorite_filter(client_a, org_a):
    favorited = _make_python_tool(org_a, name="favorited")
    not_favorited = _make_python_tool(org_a, name="not-favorited")
    client_a.post(f"{PYTHON_TOOL_URL}{favorited.id}/favorite/")

    true_ids = {t["id"] for t in _results(client_a.get(PYTHON_TOOL_URL, {"is_favorite": "true"}))}
    false_ids = {t["id"] for t in _results(client_a.get(PYTHON_TOOL_URL, {"is_favorite": "false"}))}

    assert favorited.id in true_ids and not_favorited.id not in true_ids
    assert not_favorited.id in false_ids and favorited.id not in false_ids


@pytest.mark.django_db
def test_mcptool_is_favorite_filter(client_a, org_a):
    favorited = _make_mcp_tool(org_a, name="favorited")
    not_favorited = _make_mcp_tool(org_a, name="not-favorited")
    client_a.post(f"{MCP_TOOL_URL}{favorited.id}/favorite/")

    true_ids = {t["id"] for t in _results(client_a.get(MCP_TOOL_URL, {"is_favorite": "true"}))}
    false_ids = {t["id"] for t in _results(client_a.get(MCP_TOOL_URL, {"is_favorite": "false"}))}

    assert favorited.id in true_ids and not_favorited.id not in true_ids
    assert not_favorited.id in false_ids and favorited.id not in false_ids


# ---- ?ordering=favorite ----


@pytest.mark.django_db
def test_pythoncodetool_ordering_favorite_puts_favorites_first(client_a, org_a):
    tool1 = _make_python_tool(org_a, name="a-tool")
    tool2 = _make_python_tool(org_a, name="b-tool")
    tool3 = _make_python_tool(org_a, name="c-tool")
    client_a.post(f"{PYTHON_TOOL_URL}{tool3.id}/favorite/")

    resp = client_a.get(PYTHON_TOOL_URL, {"ordering": "favorite"})
    ids = [t["id"] for t in _results(resp)]
    assert ids[0] == tool3.id
    assert set(ids) == {tool1.id, tool2.id, tool3.id}


@pytest.mark.django_db
def test_pythoncodetool_default_ordering_unaffected_by_favorites(client_a, org_a):
    tool1 = _make_python_tool(org_a, name="a-tool")
    tool2 = _make_python_tool(org_a, name="b-tool")
    tool3 = _make_python_tool(org_a, name="c-tool")
    client_a.post(f"{PYTHON_TOOL_URL}{tool3.id}/favorite/")

    resp_before = [t["id"] for t in _results(client_a.get(PYTHON_TOOL_URL))]

    # Favoriting must not change default (no `ordering` param) order, and the
    # default order itself must be deterministic (-id) regardless of filters
    # (e.g. is_favorite) being applied — see EST-3207.
    assert resp_before == [tool3.id, tool2.id, tool1.id]

    resp_filtered = [
        t["id"]
        for t in _results(client_a.get(PYTHON_TOOL_URL, {"is_favorite": "false"}))
    ]
    assert resp_filtered == [tool2.id, tool1.id]


@pytest.mark.django_db
def test_mcptool_ordering_favorite_puts_favorites_first(client_a, org_a):
    tool1 = _make_mcp_tool(org_a, name="a-tool")
    tool2 = _make_mcp_tool(org_a, name="b-tool")
    tool3 = _make_mcp_tool(org_a, name="c-tool")
    client_a.post(f"{MCP_TOOL_URL}{tool3.id}/favorite/")

    resp = client_a.get(MCP_TOOL_URL, {"ordering": "favorite"})
    ids = [t["id"] for t in _results(resp)]
    assert ids[0] == tool3.id
    assert set(ids) == {tool1.id, tool2.id, tool3.id}


@pytest.mark.django_db
def test_mcptool_default_ordering_unaffected_by_favorites(client_a, org_a):
    tool1 = _make_mcp_tool(org_a, name="a-tool")
    tool2 = _make_mcp_tool(org_a, name="b-tool")
    tool3 = _make_mcp_tool(org_a, name="c-tool")
    client_a.post(f"{MCP_TOOL_URL}{tool3.id}/favorite/")

    resp_before = [t["id"] for t in _results(client_a.get(MCP_TOOL_URL))]

    # Default order must be deterministic (-id) and unaffected by favorites,
    # and stay consistent when a filter (e.g. is_favorite) is applied.
    assert resp_before == [tool3.id, tool2.id, tool1.id]

    resp_filtered = [
        t["id"] for t in _results(client_a.get(MCP_TOOL_URL, {"is_favorite": "false"}))
    ]
    assert resp_filtered == [tool2.id, tool1.id]
