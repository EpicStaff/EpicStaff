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
from django.utils import timezone
from django.urls import reverse
from rest_framework.test import APIClient

from agents.models.surface_models import AgentInlineSurface, InlineSurface, Surface
from tables.models.graph_models import AgentNode, Graph, StorageFile, TaskNode
from tables.models.knowledge_models.collection_models import SourceCollection
from tables.models.mcp_models import McpTool
from tables.models.python_models import PythonCode, PythonCodeTool
from rbac.models import Organization, OrganizationUser, Role
from rbac.models.enums import BuiltInRole
from agents.serializers.surface_serializers import SurfaceStorageItemWriteSerializer

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
# A storage file outside the caller's reach is dropped, not rejected: see the
# storage-file tests below.
REJECTED_WHEN_FOREIGN = [reference for reference in REFERENCES if reference != "storage_file"]
EACH_REJECTED_REFERENCE = pytest.mark.parametrize("reference", REJECTED_WHEN_FOREIGN)


@EACH_NODE
@EACH_REJECTED_REFERENCE
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
        *[(reference, "another-org", 400) for reference in REJECTED_WHEN_FOREIGN],
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


def _bin(storage_file):
    StorageFile.objects.filter(pk=storage_file.pk).update(active=False, soft_deleted_at=timezone.now())


def _save_nodes(client, graph, node_kind, storage_items):
    node_list_key = {"tasknode": "task_node_list", "agentnode": "agent_node_list"}[node_kind]
    return client.post(
        reverse("graphs-save-flow", args=[graph.id]),
        {
            "save_version": graph.save_version,
            node_list_key: [
                {
                    "graph": graph.id,
                    "node_name": "bulk-node",
                    "inline_surface": {"storage_items": storage_items},
                }
            ],
        },
        format="json",
    )


def _stored_file_ids(node_kind, graph):
    model = {"tasknode": TaskNode, "agentnode": AgentNode}[node_kind]
    node = model.objects.get(graph=graph, node_name="bulk-node")
    return set(node.inline_surface.storage_items.values_list("storage_file_id", flat=True))


def _file(org, name):
    return StorageFile.objects.create(org=org, path=f"{name}.txt", name=f"{name}.txt")


@EACH_NODE
def test_bulk_save_drops_a_binned_storage_file_and_keeps_the_live_one(client_a, org_a, node_kind):
    graph = Graph.objects.create(name="a-graph", org=org_a)
    binned, live = _file(org_a, "binned"), _file(org_a, "live")
    _bin(binned)

    resp = _save_nodes(
        client_a,
        graph,
        node_kind,
        [
            {"storage_file": binned.id, "can_view": "allow"},
            {"storage_file": live.id, "can_view": "allow", "can_edit": "deny"},
        ],
    )

    assert resp.status_code == 200, resp.data
    assert _stored_file_ids(node_kind, graph) == {live.id}
    node = {"tasknode": TaskNode, "agentnode": AgentNode}[node_kind].objects.get(graph=graph)
    item = node.inline_surface.storage_items.get()
    assert (item.can_view, item.can_edit, item.can_delete) == ("allow", "deny", "unset")


@EACH_NODE
@pytest.mark.parametrize("origin", ["another-org", "nonexistent", "purged"])
def test_bulk_save_drops_an_unreachable_storage_file_like_a_binned_one(
    client_a, org_a, org_b, node_kind, origin
):
    graph = Graph.objects.create(name="a-graph", org=org_a)
    live = _file(org_a, "live")
    if origin == "another-org":
        unreachable_id = _file(org_b, "foreign").id
    elif origin == "purged":
        purged = _file(org_a, "purged")
        unreachable_id = purged.id
        purged.delete()
    else:
        unreachable_id = StorageFile.all_objects.order_by("-id").first().id + 1000

    resp = _save_nodes(
        client_a,
        graph,
        node_kind,
        [{"storage_file": unreachable_id}, {"storage_file": live.id}],
    )

    assert resp.status_code == 200, resp.data
    assert _stored_file_ids(node_kind, graph) == {live.id}


@pytest.mark.parametrize("malformed", ["abc", None, [1], True, {"id": 1}])
def test_bulk_save_still_rejects_a_malformed_storage_file_value(client_a, org_a, malformed):
    graph = Graph.objects.create(name="a-graph", org=org_a)

    resp = _save_nodes(client_a, graph, "tasknode", [{"storage_file": malformed}])

    assert resp.status_code == 400, resp.data
    assert not TaskNode.objects.filter(graph=graph).exists()


def test_bulk_save_still_rejects_a_duplicate_live_storage_file(client_a, org_a):
    graph = Graph.objects.create(name="a-graph", org=org_a)
    live = _file(org_a, "live")

    resp = _save_nodes(
        client_a, graph, "tasknode", [{"storage_file": live.id}, {"storage_file": str(live.id)}]
    )

    assert resp.status_code == 400, resp.data


def test_shared_surface_write_drops_a_binned_storage_file(client_a, org_a):
    binned, live = _file(org_a, "binned"), _file(org_a, "live")
    _bin(binned)

    resp = client_a.post(
        "/api/surfaces/",
        {
            "name": "shared",
            "storage_items": [{"storage_file": binned.id}, {"storage_file": live.id, "can_list": "allow"}],
        },
        format="json",
    )

    assert resp.status_code == 201, resp.data
    surface = Surface.objects.get(org=org_a, name="shared")
    assert list(surface.storage_items.values_list("storage_file_id", "can_list")) == [(live.id, "allow")]


def test_shared_surface_patch_drops_a_binned_storage_file(client_a, org_a):
    binned = _file(org_a, "binned")
    surface = Surface.objects.create(name="shared", org=org_a)
    _bin(binned)

    resp = client_a.patch(
        f"/api/surfaces/{surface.id}/", {"storage_items": [{"storage_file": binned.id}]}, format="json"
    )

    assert resp.status_code == 200, resp.data
    assert not surface.storage_items.exists()


def _unreachable_file_id(org_b, origin):
    if origin == "another-org":
        return _file(org_b, "foreign").id
    return 10**9


@pytest.mark.parametrize("origin", ["another-org", "nonexistent"])
def test_shared_surface_create_drops_an_unreachable_storage_file(client_a, org_a, org_b, origin):
    live = _file(org_a, "live")

    resp = client_a.post(
        "/api/surfaces/",
        {
            "name": "shared",
            "storage_items": [{"storage_file": _unreachable_file_id(org_b, origin)}, {"storage_file": live.id}],
        },
        format="json",
    )

    assert resp.status_code == 201, resp.data
    surface = Surface.objects.get(org=org_a, name="shared")
    assert set(surface.storage_items.values_list("storage_file_id", flat=True)) == {live.id}


@pytest.mark.parametrize("origin", ["another-org", "nonexistent"])
def test_shared_surface_patch_drops_an_unreachable_storage_file(client_a, org_a, org_b, origin):
    surface = Surface.objects.create(name="shared", org=org_a)

    resp = client_a.patch(
        f"/api/surfaces/{surface.id}/",
        {"storage_items": [{"storage_file": _unreachable_file_id(org_b, origin)}]},
        format="json",
    )

    assert resp.status_code == 200, resp.data
    assert not surface.storage_items.exists()


def test_shared_surface_patch_with_only_a_binned_file_clears_the_existing_items(client_a, org_a):
    kept, binned = _file(org_a, "kept"), _file(org_a, "binned")
    surface = Surface.objects.create(name="shared", org=org_a)
    surface.storage_items.create(storage_file=kept)
    _bin(binned)

    resp = client_a.patch(
        f"/api/surfaces/{surface.id}/", {"storage_items": [{"storage_file": binned.id}]}, format="json"
    )

    assert resp.status_code == 200, resp.data
    assert not surface.storage_items.exists()


@EACH_NODE
@pytest.mark.parametrize("write", ["create", "update"])
def test_node_endpoint_drops_binned_and_another_orgs_storage_files(client_a, org_a, org_b, node_kind, write):
    url, model, surfaces = NODES[node_kind]
    graph = Graph.objects.create(name="a-graph", org=org_a)
    binned, foreign = _file(org_a, "binned"), _file(org_b, "foreign")
    _bin(binned)
    inline_surface = {"storage_items": [{"storage_file": binned.id}, {"storage_file": foreign.id}]}

    if write == "create":
        resp = client_a.post(url, {"graph": graph.id, "inline_surface": inline_surface}, format="json")
        assert resp.status_code == 201, resp.data
        node_id = resp.data["id"]
    else:
        node_id = model.objects.create(graph=graph, node_name="n").id
        resp = client_a.patch(f"{url}{node_id}/", {"inline_surface": inline_surface}, format="json")
        assert resp.status_code == 200, resp.data

    assert not model.objects.get(id=node_id).inline_surface.storage_items.exists()


def test_storage_items_without_a_request_in_context_are_still_rejected(org_a):
    live = _file(org_a, "live")

    serializer = SurfaceStorageItemWriteSerializer(data=[{"storage_file": live.id}], many=True)

    assert not serializer.is_valid()
    assert "does not exist" in str(serializer.errors)
