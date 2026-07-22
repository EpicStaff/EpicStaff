"""Cross-org reference leaks in Classification Decision Table (CDT) node write
bodies (EST-3318). An org_a client tries to reference org_b / cross-graph
resources through the single-node CDT endpoint and must get a 400.

Covers both enforcement layers:
- serializer fields (graph, default_llm_config) + validate() (default/error
  next-node refs) — the single-node service pops condition_groups/prompt_configs
  before the serializer, so the remaining refs are enforced in the children sync;
- children sync (condition_groups.next_node_id, prompt_configs.llm_config) —
  runs after the node is saved, inside the viewset's atomic transaction, so a
  rejection must also roll back the just-created node (no leak).
"""

import pytest
from rest_framework.test import APIClient

from tables.models import Graph
from tables.models.graph_models import (
    ClassificationConditionGroup,
    ClassificationDecisionTableNode,
    ClassificationDecisionTablePrompt,
    StartNode,
)
from tables.models.llm_models import LLMConfig
from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole


CDT_URL = "/api/classification-decision-table-node/"


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="Org A")


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="Org B")


def _admin_client(django_user_model, org, email):
    # Org Admin: full CRUD on FLOWS, so writes aren't blocked by the verb gate
    # and we isolate the org-reference checks under test.
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


def _graph(org, name="g"):
    return Graph.objects.create(name=name, metadata={"nodes": [], "edges": []}, org=org)


def _save_url(graph_id: int) -> str:
    return f"/api/graphs/{graph_id}/save/"


# ---- graph FK (serializer field) ----


@pytest.mark.django_db
def test_cdt_graph_cross_org_rejected(client_a, org_a, org_b):
    graph_b = _graph(org_b, "b")
    resp = client_a.post(
        CDT_URL, {"graph": graph_b.id, "node_name": "cdt1"}, format="json"
    )
    assert resp.status_code == 400, resp.data
    assert "graph" in str(resp.data)
    assert not ClassificationDecisionTableNode.objects.filter(node_name="cdt1").exists()


# ---- default_llm_config FK (serializer field) ----


@pytest.mark.django_db
def test_cdt_default_llm_config_cross_org_rejected(client_a, org_a, org_b):
    graph_a = _graph(org_a, "a")
    other = LLMConfig.objects.create(custom_name="b-cfg", org=org_b)
    resp = client_a.post(
        CDT_URL,
        {"graph": graph_a.id, "node_name": "cdt1", "default_llm_config": other.id},
        format="json",
    )
    assert resp.status_code == 400, resp.data
    assert "default_llm_config" in str(resp.data)


@pytest.mark.django_db
def test_cdt_default_llm_config_same_org_ok(client_a, org_a):
    graph_a = _graph(org_a, "a")
    mine = LLMConfig.objects.create(custom_name="a-cfg", org=org_a)
    resp = client_a.post(
        CDT_URL,
        {"graph": graph_a.id, "node_name": "cdt1", "default_llm_config": mine.id},
        format="json",
    )
    assert resp.status_code == 201, resp.data


# ---- default_next_node_id (serializer validate) ----


@pytest.mark.django_db
def test_cdt_default_next_node_cross_graph_rejected(client_a, org_a, org_b):
    graph_a = _graph(org_a, "a")
    graph_b = _graph(org_b, "b")
    foreign = StartNode.objects.create(graph=graph_b, variables={})
    resp = client_a.post(
        CDT_URL,
        {
            "graph": graph_a.id,
            "node_name": "cdt1",
            "default_next_node_id": foreign.id,  # node in another graph/org
        },
        format="json",
    )
    assert resp.status_code == 400, resp.data
    assert "default_next_node_id" in str(resp.data)


# ---- condition_groups.next_node_id (children sync, post-save + rollback) ----


@pytest.mark.django_db
def test_cdt_condition_group_next_node_cross_graph_rejected(client_a, org_a, org_b):
    graph_a = _graph(org_a, "a")
    graph_b = _graph(org_b, "b")
    foreign = StartNode.objects.create(graph=graph_b, variables={})
    resp = client_a.post(
        CDT_URL,
        {
            "graph": graph_a.id,
            "node_name": "cdt1",
            "condition_groups": [
                {"group_name": "grp1", "order": 0, "next_node_id": foreign.id}
            ],
        },
        format="json",
    )
    assert resp.status_code == 400, resp.data
    assert "next_node_id" in str(resp.data)
    # No leak: the rejected request must roll back the just-created node.
    assert not ClassificationDecisionTableNode.objects.filter(node_name="cdt1").exists()


@pytest.mark.django_db
def test_cdt_condition_group_next_node_same_graph_ok(client_a, org_a):
    graph_a = _graph(org_a, "a")
    target = StartNode.objects.create(graph=graph_a, variables={})
    resp = client_a.post(
        CDT_URL,
        {
            "graph": graph_a.id,
            "node_name": "cdt1",
            "condition_groups": [
                {"group_name": "grp1", "order": 0, "next_node_id": target.id}
            ],
        },
        format="json",
    )
    assert resp.status_code == 201, resp.data


# ---- prompt_configs.llm_config (children sync, post-save + rollback) ----


@pytest.mark.django_db
def test_cdt_prompt_config_llm_config_cross_org_rejected(client_a, org_a, org_b):
    graph_a = _graph(org_a, "a")
    other = LLMConfig.objects.create(custom_name="b-cfg", org=org_b)
    resp = client_a.post(
        CDT_URL,
        {
            "graph": graph_a.id,
            "node_name": "cdt1",
            "prompt_configs": [{"prompt_key": "p1", "llm_config": other.id}],
        },
        format="json",
    )
    assert resp.status_code == 400, resp.data
    assert "llm_config" in str(resp.data)
    # No leak: the rejected request must roll back the just-created node.
    assert not ClassificationDecisionTableNode.objects.filter(node_name="cdt1").exists()


@pytest.mark.django_db
def test_cdt_prompt_config_llm_config_same_org_ok(client_a, org_a):
    graph_a = _graph(org_a, "a")
    mine = LLMConfig.objects.create(custom_name="a-cfg", org=org_a)
    resp = client_a.post(
        CDT_URL,
        {
            "graph": graph_a.id,
            "node_name": "cdt1",
            "prompt_configs": [{"prompt_key": "p1", "llm_config": mine.id}],
        },
        format="json",
    )
    assert resp.status_code == 201, resp.data


# ---- prompt_configs.llm_config_id: the raw `*_id` FK form is no longer honored.
# Validation/scoping now runs through the prompt serializer, whose field is named
# `llm_config`; `llm_config_id` is an unknown key and is silently ignored (the FE
# sends `llm_config`). So the `_id` form can neither set nor leak a config. ----


@pytest.mark.django_db
def test_cdt_prompt_config_llm_config_id_is_ignored_same_org(client_a, org_a):
    graph_a = _graph(org_a, "a")
    mine = LLMConfig.objects.create(custom_name="a-cfg", org=org_a)
    resp = client_a.post(
        CDT_URL,
        {
            "graph": graph_a.id,
            "node_name": "cdt1",
            "prompt_configs": [{"prompt_key": "p1", "llm_config_id": mine.id}],
        },
        format="json",
    )
    assert resp.status_code == 201, resp.data
    prompt = ClassificationDecisionTablePrompt.objects.get(prompt_key="p1")
    # Only the `llm_config` key is honored; the `_id` form is ignored, not applied.
    assert prompt.llm_config_id is None


@pytest.mark.django_db
def test_cdt_prompt_config_llm_config_id_cross_org_not_attached(client_a, org_a, org_b):
    # Because `llm_config_id` is ignored, a cross-org config can never be attached
    # through it (no rejection needed — it simply never reaches the model).
    graph_a = _graph(org_a, "a")
    other = LLMConfig.objects.create(custom_name="b-cfg", org=org_b)
    resp = client_a.post(
        CDT_URL,
        {
            "graph": graph_a.id,
            "node_name": "cdt1",
            "prompt_configs": [{"prompt_key": "p1", "llm_config_id": other.id}],
        },
        format="json",
    )
    assert resp.status_code == 201, resp.data
    assert not ClassificationDecisionTablePrompt.objects.filter(
        llm_config=other
    ).exists()


# ---- condition_groups.prompt_id: analogous raw FK-id bypass on the group FK ----


@pytest.mark.django_db
def test_cdt_condition_group_prompt_id_cross_org_not_written(client_a, org_a, org_b):
    # A prompt from another org referenced by `prompt_id` must not be written
    # onto a group (it belongs to no prompt of this node).
    graph_a = _graph(org_a, "a")
    graph_b = _graph(org_b, "b")
    node_b = ClassificationDecisionTableNode.objects.create(
        graph=graph_b, node_name="cdt_b"
    )
    foreign_prompt = ClassificationDecisionTablePrompt.objects.create(
        cdt_node=node_b, prompt_key="pb"
    )
    node_a = ClassificationDecisionTableNode.objects.create(
        graph=graph_a, node_name="cdt_a"
    )
    resp = client_a.patch(
        f"{CDT_URL}{node_a.id}/",
        {
            "condition_groups": [
                {"group_name": "g1", "order": 0, "prompt_id": foreign_prompt.id}
            ]
        },
        format="json",
    )
    # The request may succeed, but the cross-org prompt must never be attached.
    assert not ClassificationConditionGroup.objects.filter(
        prompt=foreign_prompt
    ).exists()


# ---- bulk-save path (graphs/<id>/save/): exercises the serializer -> sync
# org_id threading, which the single-node service path does not ----


@pytest.mark.django_db
def test_cdt_bulk_save_prompt_config_llm_config_same_org_ok(client_a, org_a):
    graph_a = _graph(org_a, "a")
    mine = LLMConfig.objects.create(custom_name="a-cfg", org=org_a)
    payload = {
        "save_version": graph_a.save_version,
        "classification_decision_table_node_list": [
            {
                "graph": graph_a.id,
                "node_name": "cdt_bulk",
                "prompt_configs": [{"prompt_key": "p1", "llm_config": mine.id}],
                "condition_groups": [{"group_name": "g1", "order": 0}],
            }
        ],
    }
    resp = client_a.post(_save_url(graph_a.id), payload, format="json")
    assert resp.status_code == 200, resp.content
    prompt = ClassificationDecisionTablePrompt.objects.get(prompt_key="p1")
    assert prompt.llm_config_id == mine.id


@pytest.mark.django_db
def test_cdt_bulk_save_prompt_config_llm_config_cross_org_rejected(
    client_a, org_a, org_b
):
    graph_a = _graph(org_a, "a")
    other = LLMConfig.objects.create(custom_name="b-cfg", org=org_b)
    payload = {
        "save_version": graph_a.save_version,
        "classification_decision_table_node_list": [
            {
                "graph": graph_a.id,
                "node_name": "cdt_bulk",
                "prompt_configs": [{"prompt_key": "p1", "llm_config": other.id}],
            }
        ],
    }
    resp = client_a.post(_save_url(graph_a.id), payload, format="json")
    assert resp.status_code == 400, resp.content
    assert not ClassificationDecisionTablePrompt.objects.filter(
        llm_config=other
    ).exists()


# ---- group_name non-empty (enforced by the group serializer) ----


@pytest.mark.django_db
def test_cdt_condition_group_blank_group_name_rejected(client_a, org_a):
    graph_a = _graph(org_a, "a")
    resp = client_a.post(
        CDT_URL,
        {
            "graph": graph_a.id,
            "node_name": "cdt1",
            "condition_groups": [{"group_name": "", "order": 0}],
        },
        format="json",
    )
    assert resp.status_code == 400, resp.data
    assert "group_name" in str(resp.data)
    assert not ClassificationDecisionTableNode.objects.filter(node_name="cdt1").exists()


@pytest.mark.django_db
def test_cdt_condition_group_whitespace_group_name_rejected(client_a, org_a):
    graph_a = _graph(org_a, "a")
    resp = client_a.post(
        CDT_URL,
        {
            "graph": graph_a.id,
            "node_name": "cdt1",
            "condition_groups": [{"group_name": "   ", "order": 0}],
        },
        format="json",
    )
    assert resp.status_code == 400, resp.data
    assert "group_name" in str(resp.data)


# ---- sparse per-item update: renaming one prompt field must not wipe the rest
# (guards the partial=True child-validation choice against default-fill clobber) ----


@pytest.mark.django_db
def test_cdt_prompt_partial_update_preserves_other_fields(client_a, org_a):
    graph_a = _graph(org_a, "a")
    mine = LLMConfig.objects.create(custom_name="a-cfg", org=org_a)
    node = ClassificationDecisionTableNode.objects.create(
        graph=graph_a, node_name="cdt1"
    )
    ClassificationDecisionTablePrompt.objects.create(
        cdt_node=node,
        prompt_key="p1",
        prompt_text="keep me",
        result_variable="old",
        llm_config=mine,
    )
    resp = client_a.patch(
        f"{CDT_URL}{node.id}/",
        {"prompt_configs": [{"prompt_key": "p1", "result_variable": "new"}]},
        format="json",
    )
    assert resp.status_code == 200, resp.data
    prompt = ClassificationDecisionTablePrompt.objects.get(
        cdt_node=node, prompt_key="p1"
    )
    assert prompt.result_variable == "new"  # changed field applied
    assert prompt.prompt_text == "keep me"  # untouched field preserved
    assert prompt.llm_config_id == mine.id  # untouched FK preserved


# ---- condition group `prompt` (raw pk passed through) resolves node-locally ----


@pytest.mark.django_db
def test_cdt_condition_group_prompt_same_node_attached(client_a, org_a):
    graph_a = _graph(org_a, "a")
    node = ClassificationDecisionTableNode.objects.create(
        graph=graph_a, node_name="cdt1"
    )
    prompt = ClassificationDecisionTablePrompt.objects.create(
        cdt_node=node, prompt_key="p1"
    )
    resp = client_a.patch(
        f"{CDT_URL}{node.id}/",
        {"condition_groups": [{"group_name": "g1", "order": 0, "prompt": prompt.id}]},
        format="json",
    )
    assert resp.status_code == 200, resp.data
    group = ClassificationConditionGroup.objects.get(
        classification_decision_table_node=node
    )
    assert group.prompt_id == prompt.id


@pytest.mark.django_db
def test_cdt_condition_group_prompt_other_node_resolves_none(client_a, org_a):
    graph_a = _graph(org_a, "a")
    node_a = ClassificationDecisionTableNode.objects.create(
        graph=graph_a, node_name="cdt_a"
    )
    other_node = ClassificationDecisionTableNode.objects.create(
        graph=graph_a, node_name="cdt_other"
    )
    foreign_prompt = ClassificationDecisionTablePrompt.objects.create(
        cdt_node=other_node, prompt_key="pother"
    )
    resp = client_a.patch(
        f"{CDT_URL}{node_a.id}/",
        {
            "condition_groups": [
                {"group_name": "g1", "order": 0, "prompt": foreign_prompt.id}
            ]
        },
        format="json",
    )
    assert resp.status_code == 200, resp.data
    group = ClassificationConditionGroup.objects.get(
        classification_decision_table_node=node_a
    )
    # A prompt from another node is not node-local -> resolves to None.
    assert group.prompt_id is None
