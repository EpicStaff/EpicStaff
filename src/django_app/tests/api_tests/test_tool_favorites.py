import pytest
from rest_framework.test import APIClient

from tables.models.favorite_models import McpToolFavorite, PythonCodeToolFavorite
from tables.models.mcp_models import McpTool
from tables.models.python_models import PythonCode, PythonCodeTool
from rbac.models import Organization, OrganizationUser, Role
from rbac.models.enums import BuiltInRole

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


KINDS = {
    "python": (PYTHON_TOOL_URL, _make_python_tool, PythonCodeToolFavorite),
    "mcp": (MCP_TOOL_URL, _make_mcp_tool, McpToolFavorite),
}
EACH_KIND = pytest.mark.parametrize("kind", list(KINDS))


@pytest.mark.django_db
@EACH_KIND
def test_favorite_toggle_is_idempotent_both_ways(client_a, member_a, org_a, kind):
    url, make_tool, favorite = KINDS[kind]
    tool = make_tool(org_a)

    added = [client_a.post(f"{url}{tool.id}/favorite/") for _ in range(2)]
    count_after_adding = favorite.objects.filter(user=member_a, tool=tool).count()
    removed = [client_a.delete(f"{url}{tool.id}/favorite/") for _ in range(2)]

    assert [response.status_code for response in added + removed] == [200] * 4
    assert count_after_adding == 1
    assert not favorite.objects.filter(user=member_a, tool=tool).exists()


@pytest.mark.django_db
@EACH_KIND
def test_is_favorite_is_per_user_on_list_and_detail(client_a, client_a2, org_a, kind):
    url, make_tool, _ = KINDS[kind]
    tool = make_tool(org_a)
    client_a.post(f"{url}{tool.id}/favorite/")

    mine = {row["id"]: row for row in _results(client_a.get(url))}
    theirs = {row["id"]: row for row in _results(client_a2.get(url))}

    assert mine[tool.id]["is_favorite"] is True
    assert client_a.get(f"{url}{tool.id}/").data["is_favorite"] is True
    assert theirs[tool.id]["is_favorite"] is False


@pytest.mark.django_db
@EACH_KIND
def test_favoriting_another_orgs_tool_is_404(client_a, org_b, kind):
    url, make_tool, favorite = KINDS[kind]
    other = make_tool(org_b, name="theirs")

    resp = client_a.post(f"{url}{other.id}/favorite/")

    assert resp.status_code == 404
    assert not favorite.objects.filter(tool=other).exists()


@pytest.mark.django_db
@EACH_KIND
def test_is_favorite_filter(client_a, org_a, kind):
    url, make_tool, _ = KINDS[kind]
    favorited = make_tool(org_a, name="favorited")
    not_favorited = make_tool(org_a, name="not-favorited")
    client_a.post(f"{url}{favorited.id}/favorite/")

    true_ids = {row["id"] for row in _results(client_a.get(url, {"is_favorite": "true"}))}
    false_ids = {row["id"] for row in _results(client_a.get(url, {"is_favorite": "false"}))}

    assert favorited.id in true_ids and not_favorited.id not in true_ids
    assert not_favorited.id in false_ids and favorited.id not in false_ids


@pytest.mark.django_db
@EACH_KIND
def test_favorites_sort_first_only_when_asked(client_a, org_a, kind):
    url, make_tool, _ = KINDS[kind]
    oldest, middle, newest = (make_tool(org_a, name=name) for name in ("a-tool", "b-tool", "c-tool"))
    client_a.post(f"{url}{oldest.id}/favorite/")

    by_favorite = [row["id"] for row in _results(client_a.get(url, {"ordering": "favorite"}))]
    default = [row["id"] for row in _results(client_a.get(url))]
    filtered = [row["id"] for row in _results(client_a.get(url, {"is_favorite": "false"}))]

    assert by_favorite[0] == oldest.id
    assert set(by_favorite) == {oldest.id, middle.id, newest.id}
    # The default order is deterministic (-id), whatever is favorited or filtered.
    assert default == [newest.id, middle.id, oldest.id]
    assert filtered == [newest.id, middle.id]
