"""Cross-org reference rejection for the nested `inline_surface` payload on
AgentNode/TaskNode (security regression tests, bug report follow-up).

`python_tools[].python_tool`, `mcp_tools[].mcp_tool`, `knowledge[].collection` and
`storage_items[].storage_file` inside a node's `inline_surface` are org-scoped at the
serializer layer (`OrgVisiblePrimaryKeyRelatedField` / `OrgScopedPrimaryKeyRelatedField`
in `agents/serializers/surface_serializers.py`), so a cross-org pk is rejected exactly
like a non-existent pk. Checked for the standalone node endpoints (`/api/tasknodes/`,
`/api/agentnodes/`) and the graph bulk-save endpoint (`/graphs/{id}/save/`, which
builds its own serializer context).

`python_tool` is a hybrid field: built-ins are intentionally shared across orgs, only
org-owned custom tools are scoped.
"""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from agents.models.surface_models import AgentInlineSurface, InlineSurface
from tables.models.graph_models import AgentNode, Graph, StorageFile, TaskNode
from tables.models.knowledge_models.collection_models import SourceCollection
from tables.models.mcp_models import McpTool
from tables.models.python_models import PythonCode, PythonCodeTool
from rbac.models import Organization, OrganizationUser, Role
from rbac.models.enums import BuiltInRole

pytestmark = pytest.mark.django_db


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="Inline Org A")


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="Inline Org B")


@pytest.fixture
def client_a(db, django_user_model, org_a):
    user = django_user_model.objects.create_user(email="inline_admin_a@example.com", password="StrongPass123!")
    role_admin = Role.objects.get(name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True)
    OrganizationUser.objects.create(user=user, org=org_a, role=role_admin)
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org_a.id))
    return client


def _rejected(resp):
    return resp.status_code == 400 and "does not exist" in str(resp.data)


def _python_tool(organization, *, built_in=False, name="py-tool"):
    code = PythonCode.objects.create(code="def main(): pass")
    return PythonCodeTool.objects.create(
        name=name, description="test", python_code=code, org=organization, built_in=built_in
    )


# Each reference kind: how to make one in an org, its inline_surface payload, and
# how to find it again on a saved node's inline surface.
REFERENCES = {
    "python_tool": (
        lambda org, name: _python_tool(org, name=name),
        lambda obj: {"python_tools": [{"python_tool": obj.id, "mode": "allow"}]},
        lambda surface, obj: surface.python_tools.filter(python_tool_id=obj.id),
    ),
    "mcp_tool": (
        lambda org, name: McpTool.objects.create(
            org=org, name=name, transport="http://localhost/sse", tool_name=name.replace("-", "_")
        ),
        lambda obj: {"mcp_tools": [{"mcp_tool": obj.id, "mode": "allow"}]},
        lambda surface, obj: surface.mcp_tools.filter(mcp_tool_id=obj.id),
    ),
    "knowledge": (
        lambda org, name: SourceCollection.objects.create(org=org, collection_name=name),
        lambda obj: {"knowledge": [{"collection": obj.pk}]},
        lambda surface, obj: surface.knowledge.filter(collection_id=obj.pk),
    ),
    "storage_file": (
        lambda org, name: StorageFile.objects.create(org=org, path=f"{name}.txt", name=f"{name}.txt"),
        lambda obj: {"storage_items": [{"storage_file": obj.id}]},
        lambda surface, obj: surface.storage_items.filter(storage_file_id=obj.id),
    ),
}
NODES = {
    "tasknode": ("/api/tasknodes/", TaskNode, lambda node_id: InlineSurface.objects.filter(task_node_id=node_id)),
    "agentnode": (
        "/api/agentnodes/", AgentNode, lambda node_id: AgentInlineSurface.objects.filter(agent_node_id=node_id)
    ),
}
EACH_REFERENCE = pytest.mark.parametrize("reference", list(REFERENCES))
EACH_NODE = pytest.mark.parametrize("node_kind", list(NODES))


@EACH_NODE
@EACH_REFERENCE
@pytest.mark.parametrize("write", ["create", "update"])
def test_inline_reference_to_another_orgs_object_is_rejected(client_a, org_a, org_b, node_kind, reference, write):
    make, payload, _ = REFERENCES[reference]
    url, model, surfaces = NODES[node_kind]
    graph = Graph.objects.create(name="a-graph", org=org_a)
    foreign = make(org_b, "b-ref")

    if write == "create":
        resp = client_a.post(url, {"graph": graph.id, "inline_surface": payload(foreign)}, format="json")
        assert not model.objects.filter(graph=graph).exists()
    else:
        node = model.objects.create(graph=graph, node_name="n")
        resp = client_a.patch(f"{url}{node.id}/", {"inline_surface": payload(foreign)}, format="json")
        assert not surfaces(node.id).exists()

    assert _rejected(resp), resp.data


@EACH_NODE
@pytest.mark.parametrize(
    ("reference", "owner"),
    [*[(reference, "own-org") for reference in REFERENCES], ("python_tool", "built-in-of-another-org")],
)
def test_inline_reference_in_reach_is_attached(client_a, org_a, org_b, node_kind, reference, owner):
    make, payload, attached = REFERENCES[reference]
    url, model, _ = NODES[node_kind]
    graph = Graph.objects.create(name="a-graph", org=org_a)
    target = make(org_a, "a-ref") if owner == "own-org" else _python_tool(org_b, built_in=True, name="shared")

    resp = client_a.post(url, {"graph": graph.id, "inline_surface": payload(target)}, format="json")

    assert resp.status_code == 201, resp.data
    assert attached(model.objects.get(id=resp.data["id"]).inline_surface, target).exists()


@pytest.mark.parametrize(
    ("reference", "owner", "expected_status"),
    [
        *[(reference, "another-org", 400) for reference in REFERENCES],
        *[(reference, "own-org", 200) for reference in REFERENCES],
        ("python_tool", "built-in-of-another-org", 200),
    ],
)
def test_bulk_save_applies_the_same_inline_reference_rules(client_a, org_a, org_b, reference, owner, expected_status):
    make, payload, attached = REFERENCES[reference]
    graph = Graph.objects.create(name="a-graph", org=org_a)
    target = {
        "another-org": lambda: make(org_b, "bulk-b-ref"),
        "own-org": lambda: make(org_a, "bulk-a-ref"),
        "built-in-of-another-org": lambda: _python_tool(org_b, built_in=True, name="bulk-shared"),
    }[owner]()

    resp = client_a.post(
        reverse("graphs-save-flow", args=[graph.id]),
        {
            "save_version": graph.save_version,
            "task_node_list": [{"graph": graph.id, "node_name": "bulk-task", "inline_surface": payload(target)}],
        },
        format="json",
    )

    assert resp.status_code == expected_status, resp.data
    saved = TaskNode.objects.filter(graph=graph, node_name="bulk-task")
    assert saved.exists() is (expected_status == 200)
    if expected_status == 200:
        assert attached(saved.get().inline_surface, target).exists()
