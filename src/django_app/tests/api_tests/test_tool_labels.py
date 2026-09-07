import pytest
from rest_framework.test import APIClient

from tables.models.label_models import Label
from tables.models.mcp_models import McpTool
from tables.models.python_models import PythonCode, PythonCodeTool
from tables.models.rbac_models import Organization, OrganizationUser, Role


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
    # Org Admin (not Member) so destroy is permitted — this suite exercises
    # scope/org isolation, not the RBAC verb-gate role matrix.
    user = django_user_model.objects.create_user(
        email="member_a@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org_a, role=org_admin_role)
    return user


@pytest.fixture
def client_a(member_a, org_a):
    client = APIClient()
    client.force_authenticate(user=member_a)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org_a.id))
    return client


@pytest.fixture
def member_b(db, django_user_model, org_b, org_admin_role):
    user = django_user_model.objects.create_user(
        email="member_b@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org_b, role=org_admin_role)
    return user


@pytest.fixture
def client_b(member_b, org_b):
    client = APIClient()
    client.force_authenticate(user=member_b)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org_b.id))
    return client


@pytest.fixture
def python_code_tool_a(org_a) -> PythonCodeTool:
    code = PythonCode.objects.create(code="def main(): return 1", entrypoint="main")
    return PythonCodeTool.objects.create(
        name="ToolA",
        description="desc",
        python_code=code,
        org=org_a,
    )


@pytest.fixture
def mcp_tool_a(org_a) -> McpTool:
    return McpTool.objects.create(
        name="McpA",
        transport="https://example.com/mcp",
        tool_name="do_thing",
        org=org_a,
    )


def _results(resp):
    body = resp.data
    return body["results"] if isinstance(body, dict) and "results" in body else body


# ---- creation + tree isolation ----


@pytest.mark.django_db
def test_create_tool_label_lands_in_active_org_with_tool_scope(client_a, org_a):
    resp = client_a.post("/api/tool-labels/", {"name": "Billing"}, format="json")
    assert resp.status_code == 201
    label = Label.objects.get(id=resp.data["id"])
    assert label.org_id == org_a.id
    assert label.scope == Label.Scope.TOOL


@pytest.mark.django_db
def test_tool_label_not_visible_via_flow_labels_endpoint(client_a, org_a):
    resp = client_a.post("/api/tool-labels/", {"name": "Billing"}, format="json")
    assert resp.status_code == 201
    tool_label_id = resp.data["id"]

    flow_resp = client_a.get("/api/labels/")
    assert flow_resp.status_code == 200
    ids = {row["id"] for row in _results(flow_resp)}
    assert tool_label_id not in ids


@pytest.mark.django_db
def test_flow_label_not_visible_via_tool_labels_endpoint(client_a, org_a):
    resp = client_a.post("/api/labels/", {"name": "Onboarding"}, format="json")
    assert resp.status_code == 201
    flow_label_id = resp.data["id"]

    tool_resp = client_a.get("/api/tool-labels/")
    assert tool_resp.status_code == 200
    ids = {row["id"] for row in _results(tool_resp)}
    assert flow_label_id not in ids


@pytest.mark.django_db
def test_same_name_allowed_across_flow_and_tool_scopes(client_a, org_a):
    flow_resp = client_a.post("/api/labels/", {"name": "Shared"}, format="json")
    assert flow_resp.status_code == 201
    tool_resp = client_a.post("/api/tool-labels/", {"name": "Shared"}, format="json")
    assert tool_resp.status_code == 201


@pytest.mark.django_db
def test_tool_label_cannot_be_parented_under_flow_label(client_a, org_a):
    flow_parent = Label.objects.create(name="FlowParent", org=org_a, scope=Label.Scope.FLOW)
    resp = client_a.post(
        "/api/tool-labels/",
        {"name": "Child", "parent": flow_parent.id},
        format="json",
    )
    assert resp.status_code == 400
    # The RBAC exception handler wraps serializer errors into
    # {status_code, code, message}; the field name still appears in message.
    assert "parent" in resp.data["message"]


@pytest.mark.django_db
def test_flow_label_cannot_be_parented_under_tool_label(client_a, org_a):
    tool_parent = Label.objects.create(name="ToolParent", org=org_a, scope=Label.Scope.TOOL)
    resp = client_a.post(
        "/api/labels/",
        {"name": "Child", "parent": tool_parent.id},
        format="json",
    )
    assert resp.status_code == 400
    # The RBAC exception handler wraps serializer errors into
    # {status_code, code, message}; the field name still appears in message.
    assert "parent" in resp.data["message"]


# ---- org scoping ----


@pytest.mark.django_db
def test_cross_org_tool_label_not_selectable(client_a, org_a, org_b):
    foreign_label = Label.objects.create(name="Foreign", org=org_b, scope=Label.Scope.TOOL)
    code = PythonCode.objects.create(code="def main(): return 1", entrypoint="main")
    tool = PythonCodeTool.objects.create(
        name="ToolX", description="d", python_code=code, org=org_a
    )
    resp = client_a.patch(
        f"/api/python-code-tool/{tool.id}/",
        {"labels": [foreign_label.id]},
        format="json",
    )
    assert resp.status_code == 400


# ---- assignment ----


@pytest.mark.django_db
def test_assign_multiple_tool_labels_to_python_code_tool(
    client_a, org_a, python_code_tool_a
):
    l1 = Label.objects.create(name="L1", org=org_a, scope=Label.Scope.TOOL)
    l2 = Label.objects.create(name="L2", org=org_a, scope=Label.Scope.TOOL)

    resp = client_a.patch(
        f"/api/python-code-tool/{python_code_tool_a.id}/",
        {"labels": [l1.id, l2.id]},
        format="json",
    )
    assert resp.status_code == 200
    python_code_tool_a.refresh_from_db()
    assert set(python_code_tool_a.labels.values_list("id", flat=True)) == {l1.id, l2.id}
    assert set(resp.data["labels"]) == {l1.id, l2.id}


@pytest.mark.django_db
def test_assign_multiple_tool_labels_to_mcp_tool(client_a, org_a, mcp_tool_a):
    l1 = Label.objects.create(name="M1", org=org_a, scope=Label.Scope.TOOL)
    l2 = Label.objects.create(name="M2", org=org_a, scope=Label.Scope.TOOL)

    resp = client_a.put(
        f"/api/mcp-tools/{mcp_tool_a.id}/",
        {
            "name": mcp_tool_a.name,
            "transport": mcp_tool_a.transport,
            "tool_name": mcp_tool_a.tool_name,
            "labels": [l1.id, l2.id],
        },
        format="json",
    )
    assert resp.status_code == 200, resp.data
    mcp_tool_a.refresh_from_db()
    assert set(mcp_tool_a.labels.values_list("id", flat=True)) == {l1.id, l2.id}


@pytest.mark.django_db
def test_patch_with_only_labels_on_python_code_tool(
    client_a, org_a, python_code_tool_a
):
    l1 = Label.objects.create(name="PL1", org=org_a, scope=Label.Scope.TOOL)
    l2 = Label.objects.create(name="PL2", org=org_a, scope=Label.Scope.TOOL)

    resp = client_a.patch(
        f"/api/python-code-tool/{python_code_tool_a.id}/",
        {"labels": [l1.id, l2.id]},
        format="json",
    )
    assert resp.status_code == 200, resp.data
    python_code_tool_a.refresh_from_db()
    assert set(python_code_tool_a.labels.values_list("id", flat=True)) == {l1.id, l2.id}


@pytest.mark.django_db
def test_patch_with_only_labels_on_mcp_tool(client_a, org_a, mcp_tool_a):
    # Regression test: McpToolViewSet.update() is a full-replace-only override
    # that back-fills every concrete field missing from the request body. It
    # must not run for PATCH — partial_update() bypasses it so a bare PATCH
    # with only `labels` doesn't null out the other required fields (name,
    # transport, tool_name) and 400.
    l1 = Label.objects.create(name="M1", org=org_a, scope=Label.Scope.TOOL)
    l2 = Label.objects.create(name="M2", org=org_a, scope=Label.Scope.TOOL)

    resp = client_a.patch(
        f"/api/mcp-tools/{mcp_tool_a.id}/",
        {"labels": [l1.id, l2.id]},
        format="json",
    )
    assert resp.status_code == 200, resp.data
    mcp_tool_a.refresh_from_db()
    assert set(mcp_tool_a.labels.values_list("id", flat=True)) == {l1.id, l2.id}
    assert mcp_tool_a.name == "McpA"
    assert mcp_tool_a.transport == "https://example.com/mcp"
    assert mcp_tool_a.tool_name == "do_thing"


@pytest.mark.django_db
def test_mcp_tool_full_put_without_labels_does_not_clear_assignment(
    client_a, org_a, mcp_tool_a
):
    label = Label.objects.create(name="Keep", org=org_a, scope=Label.Scope.TOOL)
    mcp_tool_a.labels.set([label])

    resp = client_a.put(
        f"/api/mcp-tools/{mcp_tool_a.id}/",
        {
            "name": mcp_tool_a.name,
            "transport": mcp_tool_a.transport,
            "tool_name": mcp_tool_a.tool_name,
        },
        format="json",
    )
    assert resp.status_code == 200
    mcp_tool_a.refresh_from_db()
    assert list(mcp_tool_a.labels.values_list("id", flat=True)) == [label.id]


# ---- built-in tool label updates ----


@pytest.fixture
def built_in_python_code_tool(org_a) -> PythonCodeTool:
    code = PythonCode.objects.create(code="def main(): return 1", entrypoint="main")
    return PythonCodeTool.objects.create(
        name="BuiltInTool",
        description="desc",
        python_code=code,
        org=org_a,
        built_in=True,
    )


@pytest.mark.django_db
def test_labels_only_patch_on_built_in_tool_succeeds(
    client_a, org_a, built_in_python_code_tool
):
    # Labels are org-scoped user tags, not part of the built-in tool's
    # definition — a labels-only PATCH must be allowed even for built-in tools.
    l1 = Label.objects.create(name="BI1", org=org_a, scope=Label.Scope.TOOL)

    resp = client_a.patch(
        f"/api/python-code-tool/{built_in_python_code_tool.id}/",
        {"labels": [l1.id]},
        format="json",
    )
    assert resp.status_code == 200, resp.data
    built_in_python_code_tool.refresh_from_db()
    assert set(
        built_in_python_code_tool.labels.values_list("id", flat=True)
    ) == {l1.id}


@pytest.mark.django_db
def test_non_label_patch_on_built_in_tool_still_rejected(
    client_a, org_a, built_in_python_code_tool
):
    resp = client_a.patch(
        f"/api/python-code-tool/{built_in_python_code_tool.id}/",
        {"name": "RenamedBuiltIn"},
        format="json",
    )
    assert resp.status_code == 400
    built_in_python_code_tool.refresh_from_db()
    assert built_in_python_code_tool.name == "BuiltInTool"


@pytest.mark.django_db
def test_labels_plus_other_field_patch_on_built_in_tool_rejected(
    client_a, org_a, built_in_python_code_tool
):
    # Mixing a labels change with any other field change on a built-in tool
    # must still be rejected as a whole — labels don't grant a bypass.
    l1 = Label.objects.create(name="BI2", org=org_a, scope=Label.Scope.TOOL)

    resp = client_a.patch(
        f"/api/python-code-tool/{built_in_python_code_tool.id}/",
        {"labels": [l1.id], "name": "RenamedBuiltIn"},
        format="json",
    )
    assert resp.status_code == 400
    built_in_python_code_tool.refresh_from_db()
    assert built_in_python_code_tool.name == "BuiltInTool"
    assert list(built_in_python_code_tool.labels.values_list("id", flat=True)) == []


# ---- EST-3773: two orgs labeling the same shared built-in tool ----


@pytest.fixture
def real_built_in_python_code_tool() -> PythonCodeTool:
    # Real built-in tools are global (org=None), unlike `built_in_python_code_tool`
    # above which stamps `org=org_a` and doesn't model how built-ins actually
    # exist in production — every org's labels co-mingle on this one row's
    # `labels` M2M since there is no per-org join.
    code = PythonCode.objects.create(code="def main(): return 1", entrypoint="main")
    return PythonCodeTool.objects.create(
        name="SharedBuiltInTool",
        description="desc",
        python_code=code,
        org=None,
        built_in=True,
    )


@pytest.mark.django_db
def test_two_orgs_labeling_same_built_in_tool_no_400_no_cross_wipe(
    client_a, client_b, org_a, org_b, real_built_in_python_code_tool
):
    label_a = Label.objects.create(name="OrgALabel", org=org_a, scope=Label.Scope.TOOL)
    label_b = Label.objects.create(name="OrgBLabel", org=org_b, scope=Label.Scope.TOOL)
    tool_id = real_built_in_python_code_tool.id

    resp_a = client_a.patch(
        f"/api/python-code-tool/{tool_id}/",
        {"labels": [label_a.id]},
        format="json",
    )
    assert resp_a.status_code == 200, resp_a.data

    # org-2 attaching its own label to the same shared row must not 400.
    resp_b = client_b.patch(
        f"/api/python-code-tool/{tool_id}/",
        {"labels": [label_b.id]},
        format="json",
    )
    assert resp_b.status_code == 200, resp_b.data

    # org-2's GET only shows org-2's label — no cross-org leak.
    get_b = client_b.get(f"/api/python-code-tool/{tool_id}/")
    assert get_b.status_code == 200
    assert get_b.data["labels"] == [label_b.id]

    # org-1's attachment was preserved, not wiped by org-2's write.
    get_a = client_a.get(f"/api/python-code-tool/{tool_id}/")
    assert get_a.status_code == 200
    assert get_a.data["labels"] == [label_a.id]


# ---- cascade delete ----


@pytest.mark.django_db
def test_delete_parent_tool_label_cascades_and_unassigns(
    client_a, org_a, python_code_tool_a
):
    parent = Label.objects.create(name="Parent", org=org_a, scope=Label.Scope.TOOL)
    child = Label.objects.create(
        name="Child", org=org_a, scope=Label.Scope.TOOL, parent=parent
    )
    python_code_tool_a.labels.set([parent, child])

    resp = client_a.delete(f"/api/tool-labels/{parent.id}/")
    assert resp.status_code == 204

    assert not Label.objects.filter(id=parent.id).exists()
    assert not Label.objects.filter(id=child.id).exists()
    assert list(python_code_tool_a.labels.values_list("id", flat=True)) == []
