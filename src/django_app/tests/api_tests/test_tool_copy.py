import pytest
from rest_framework.test import APIClient

from tables.models.label_models import Label
from tables.models.mcp_models import McpTool
from tables.models.python_models import PythonCode, PythonCodeTool
from rbac.models import Organization, OrganizationUser, Role


# ---- fixtures ----


@pytest.fixture
def org_admin_role(db):
    return Role.objects.get(name="Org Admin", is_built_in=True, org__isnull=True)


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="Org A")


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="Org B")


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
def test_copy_of_a_built_in_tool_is_an_ordinary_editable_tool_of_the_callers_org(
    client_a, org_a, org_b, built_in_python_code_tool
):
    source = built_in_python_code_tool
    # A shared built-in tool can carry another org's labels; the copy must not.
    source.labels.set([Label.objects.create(name="OrgBLabel", scope=Label.Scope.TOOL, org=org_b)])

    resp = client_a.post(f"/api/python-code-tool/{source.id}/copy/", {}, format="json")

    assert resp.status_code == 201, resp.data
    assert resp.data["built_in"] is False
    copy = PythonCodeTool.objects.get(id=resp.data["id"])
    assert (copy.built_in, copy.org_id) == (False, org_a.id)
    assert list(copy.labels.values_list("id", flat=True)) == []
    # Its own code row: editing the copy must never change the built-in.
    assert copy.python_code_id != source.python_code_id
    assert (copy.python_code.code, copy.python_code.entrypoint) == (source.python_code.code, source.python_code.entrypoint)
    patched = client_a.patch(
        f"/api/python-code-tool/{copy.id}/", {"name": "RenamedCopy", "description": "new desc"}, format="json"
    )
    assert patched.status_code == 200, patched.data
    copy.refresh_from_db()
    assert (copy.name, copy.description) == ("RenamedCopy", "new desc")


# ---- existing built-in guardrails must remain intact ----


@pytest.mark.django_db
def test_built_in_tool_still_cannot_be_deleted(client_a, org_a, built_in_python_code_tool):
    resp = client_a.delete(
        f"/api/python-code-tool/{built_in_python_code_tool.id}/"
    )
    assert resp.status_code in (400, 403, 404)
    assert PythonCodeTool.objects.filter(id=built_in_python_code_tool.id).exists()


# ---- copy must carry over tool-scope labels ----


def _mcp_tool(org, name):
    return McpTool.objects.create(name=name, transport="https://example.com/mcp", tool_name="some_tool", org=org)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("url", "model", "make_tool", "labelled"),
    [
        ("/api/python-code-tool/", PythonCodeTool, lambda org: _make_tool(org=org, name="PyTool"), True),
        ("/api/python-code-tool/", PythonCodeTool, lambda org: _make_tool(org=org, name="PyTool"), False),
        ("/api/mcp-tools/", McpTool, lambda org: _mcp_tool(org, "McpTool"), True),
    ],
    ids=["python-labelled", "python-unlabelled", "mcp-labelled"],
)
def test_copy_carries_over_the_tool_labels(client_a, org_a, url, model, make_tool, labelled):
    tool = make_tool(org_a)
    labels = [Label.objects.create(name="prod", scope=Label.Scope.TOOL, org=org_a)] if labelled else []
    tool.labels.set(labels)

    resp = client_a.post(f"{url}{tool.id}/copy/", {}, format="json")

    assert resp.status_code == 201, resp.data
    assert list(model.objects.get(id=resp.data["id"]).labels.values_list("id", flat=True)) == [label.id for label in labels]


# ---- copying a shared built-in tool must not carry another org's labels ----


# ---- copy-name numbering must be org-scoped (and built-in-aware) ----


@pytest.fixture
def member_b(db, django_user_model, org_b, org_admin_role):
    user = django_user_model.objects.create_user(
        email="copy_member_b@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org_b, role=org_admin_role)
    return user


@pytest.fixture
def client_b(member_b, org_b):
    client = APIClient()
    client.force_authenticate(user=member_b)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org_b.id))
    return client


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("url", "model", "make_tool"),
    [
        ("/api/python-code-tool/", PythonCodeTool, lambda org, name: _make_tool(org=org, name=name)),
        ("/api/mcp-tools/", McpTool, _mcp_tool),
    ],
    ids=["python", "mcp"],
)
def test_copy_numbering_is_not_inflated_by_other_orgs(client_a, org_a, org_b, url, model, make_tool):
    """Org B already holds "Shared #2".."Shared #6" -- org A's own copy
    numbering must not be pushed past "Shared #2" by rows it can't even see."""
    source = make_tool(org_a, "Shared")
    for n in range(2, 7):
        make_tool(org_b, f"Shared #{n}")

    resp = client_a.post(f"{url}{source.id}/copy/", {}, format="json")

    assert resp.status_code == 201, resp.data
    copy = model.objects.get(id=resp.data["id"])
    assert (copy.name, copy.org_id) == ("Shared #2", org_a.id)


@pytest.mark.django_db
def test_python_code_tool_copy_name_avoids_built_in_collision(client_a, org_a):
    """A copy's generated name must also skip global built-in names, not just
    the target org's own names, otherwise the copy could collide with (or be
    confused for) a built-in tool."""
    built_in = _make_tool(built_in=True, org=None, name="Duplicated")
    _make_tool(org=org_a, built_in=False, name="Duplicated #2")

    resp = client_a.post(f"/api/python-code-tool/{built_in.id}/copy/", {}, format="json")
    assert resp.status_code == 201, resp.data
    copy = PythonCodeTool.objects.get(id=resp.data["id"])
    assert copy.name == "Duplicated #3"


# ---- a concurrent-copy name race must surface cleanly, not leak
# raw DB internals ----


@pytest.mark.django_db
def test_python_code_tool_copy_race_on_name_returns_clean_400(
    client_a, org_a, monkeypatch
):
    """Simulates the name-check/create race: `ensure_unique_identifier`
    hands back a name that collides by the time `create()` runs (e.g. a
    concurrent copy of the same source just took it), raising IntegrityError.
    The client must get a clean 400 message, not the raw DB constraint
    error text."""
    source = _make_tool(org=org_a, built_in=False, name="RaceTool")
    # Pre-create the row the "unique" name generator will (wrongly) hand back,
    # so the service's create() collides on the unique constraint.
    _make_tool(org=org_a, built_in=False, name="RaceTool #2")

    monkeypatch.setattr(
        "tables.services.copy_services.helpers.ensure_unique_identifier",
        lambda base_name, existing_names: "RaceTool #2",
    )

    resp = client_a.post(f"/api/python-code-tool/{source.id}/copy/", {}, format="json")
    assert resp.status_code == 400
    assert "message" in resp.data
    # Must not leak raw DB internals (constraint/table/column names).
    assert "constraint" not in str(resp.data).lower()
    assert "duplicate key" not in str(resp.data).lower()


