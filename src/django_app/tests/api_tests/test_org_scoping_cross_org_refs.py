"""Cross-org reference rejection (security regression tests).

A write in org A must never be able to attach / reference an org B object via
a node reference or a config FK. Each is rejected exactly like a non-existent
pk (no existence leak).
"""

import pytest
from rest_framework.test import APIClient

from tables.models.embedding_models import EmbeddingModel
from tables.models.graph_models import Graph, SubGraphNode
from tables.models.llm_models import (
    LLMConfig,
    LLMModel,
    RealtimeModel,
    RealtimeTranscriptionModel,
)
from tables.models.python_models import PythonCode, PythonCodeTool
from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="Org A")


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="Org B")


@pytest.fixture
def client_admin_a(db, django_user_model, org_a):  # full CRUD in A
    role = Role.objects.get(
        name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True
    )
    user = django_user_model.objects.create_user(
        email="xa@e.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org_a, role=role)
    c = APIClient()
    c.force_authenticate(user=user)
    c.credentials(HTTP_X_ORGANIZATION_ID=str(org_a.id))
    return c


# ---- factories ----


def _python_tool(org, *, built_in=False, name="tool"):
    code = PythonCode.objects.create(code="x", entrypoint="main")
    return PythonCodeTool.objects.create(
        name=name,
        description="",
        python_code=code,
        built_in=built_in,
        org=org,
    )


def _llm_config(org, name="cfg"):
    return LLMConfig.objects.create(custom_name=name, org=org)


# Hybrid models: built-ins have org=None/is_custom=False (visible to every org);
# custom rows are org-owned/is_custom=True (visible only to that org).
def _llm_model(org, *, is_custom, name="llm"):
    return LLMModel.objects.create(name=name, is_custom=is_custom, org=org)


def _embedding_model(org, *, is_custom, name="emb"):
    return EmbeddingModel.objects.create(name=name, is_custom=is_custom, org=org)


def _realtime_model(org, *, is_custom, name="rt"):
    return RealtimeModel.objects.create(name=name, is_custom=is_custom, org=org)


def _realtime_transcription_model(org, *, is_custom, name="rtt"):
    return RealtimeTranscriptionModel.objects.create(
        name=name, is_custom=is_custom, org=org
    )


def _rejected(resp):
    return resp.status_code == 400 and "does not exist" in str(resp.data)


# ---- Bulk-save (save_flow): cross-org node references ----
#
# Regression for the bulk-save request-context gap: GraphBulkSaveService now
# threads the request into every node serializer's context, so org-scoped FK
# fields (SubGraphNode.subgraph, CodeAgentNode.llm_config) resolve the active
# org and reject cross-org ids. The same-org (positive) cases prove the request
# is in fact threaded — without it the deny-on-no-request fallback would 400
# those too.


def _save_url(graph_id: int) -> str:
    return f"/api/graphs/{graph_id}/save/"


@pytest.mark.django_db
def test_bulk_save_rejects_cross_org_subgraph(client_admin_a, org_a, org_b):
    graph = Graph.objects.create(name="a-graph", org=org_a)
    b_subgraph = Graph.objects.create(name="b-subgraph", org=org_b)
    resp = client_admin_a.post(
        _save_url(graph.id),
        {
            "save_version": graph.save_version,
            "subgraph_node_list": [{"graph": graph.id, "subgraph": b_subgraph.id}],
        },
        format="json",
    )
    assert _rejected(resp), resp.data
    assert not SubGraphNode.objects.filter(graph=graph).exists()


@pytest.mark.django_db
def test_bulk_save_allows_same_org_subgraph(client_admin_a, org_a):
    graph = Graph.objects.create(name="a-graph", org=org_a)
    a_subgraph = Graph.objects.create(name="a-subgraph", org=org_a)
    resp = client_admin_a.post(
        _save_url(graph.id),
        {
            "save_version": graph.save_version,
            "subgraph_node_list": [{"graph": graph.id, "subgraph": a_subgraph.id}],
        },
        format="json",
    )
    assert resp.status_code == 200, resp.data
    assert SubGraphNode.objects.filter(graph=graph, subgraph=a_subgraph).count() == 1


# ---- #3 CodeAgentNode.llm_config (strict, via bulk-save) ----


@pytest.mark.django_db
def test_bulk_save_rejects_cross_org_code_agent_llm_config(
    client_admin_a, org_a, org_b
):
    graph = Graph.objects.create(name="a-graph", org=org_a)
    b_cfg = _llm_config(org_b, name="b-cfg")
    resp = client_admin_a.post(
        _save_url(graph.id),
        {
            "save_version": graph.save_version,
            "code_agent_node_list": [{"graph": graph.id, "llm_config": b_cfg.id}],
        },
        format="json",
    )
    assert _rejected(resp), resp.data


@pytest.mark.django_db
def test_bulk_save_allows_same_org_code_agent_llm_config(client_admin_a, org_a):
    graph = Graph.objects.create(name="a-graph", org=org_a)
    a_cfg = _llm_config(org_a, name="a-cfg")
    resp = client_admin_a.post(
        _save_url(graph.id),
        {
            "save_version": graph.save_version,
            "code_agent_node_list": [{"graph": graph.id, "llm_config": a_cfg.id}],
        },
        format="json",
    )
    assert resp.status_code == 200, resp.data


# ---- #4 config -> model (hybrid): reject cross-org custom, allow shared built-ins ----


@pytest.mark.django_db
def test_llmconfig_rejects_cross_org_custom_model(client_admin_a, org_b):
    b_model = _llm_model(org_b, is_custom=True, name="b-llm")
    resp = client_admin_a.post(
        "/api/llm-configs/", {"custom_name": "c", "model": b_model.id}, format="json"
    )
    assert _rejected(resp), resp.data


@pytest.mark.django_db
def test_llmconfig_allows_builtin_model(client_admin_a):
    builtin = _llm_model(None, is_custom=False, name="builtin-llm")
    resp = client_admin_a.post(
        "/api/llm-configs/", {"custom_name": "c", "model": builtin.id}, format="json"
    )
    assert resp.status_code == 201, resp.data


@pytest.mark.django_db
def test_llmconfig_allows_same_org_custom_model(client_admin_a, org_a):
    a_model = _llm_model(org_a, is_custom=True, name="a-llm")
    resp = client_admin_a.post(
        "/api/llm-configs/", {"custom_name": "c", "model": a_model.id}, format="json"
    )
    assert resp.status_code == 201, resp.data


@pytest.mark.django_db
def test_embeddingconfig_rejects_cross_org_custom_model(client_admin_a, org_b):
    b_model = _embedding_model(org_b, is_custom=True, name="b-emb")
    resp = client_admin_a.post(
        "/api/embedding-configs/",
        {"custom_name": "c", "model": b_model.id},
        format="json",
    )
    assert _rejected(resp), resp.data


@pytest.mark.django_db
def test_embeddingconfig_allows_builtin_model(client_admin_a):
    builtin = _embedding_model(None, is_custom=False, name="builtin-emb")
    resp = client_admin_a.post(
        "/api/embedding-configs/",
        {"custom_name": "c", "model": builtin.id},
        format="json",
    )
    assert resp.status_code == 201, resp.data


@pytest.mark.django_db
def test_realtimeconfig_rejects_cross_org_custom_model(client_admin_a, org_b):
    b_model = _realtime_model(org_b, is_custom=True, name="b-rm")
    resp = client_admin_a.post(
        "/api/realtime-model-configs/",
        {"custom_name": "c", "realtime_model": b_model.id},
        format="json",
    )
    assert _rejected(resp), resp.data


@pytest.mark.django_db
def test_realtimeconfig_allows_builtin_model(client_admin_a):
    builtin = _realtime_model(None, is_custom=False, name="builtin-rm")
    resp = client_admin_a.post(
        "/api/realtime-model-configs/",
        {"custom_name": "c", "realtime_model": builtin.id},
        format="json",
    )
    assert resp.status_code == 201, resp.data


@pytest.mark.django_db
def test_realtimetranscriptionconfig_rejects_cross_org_custom_model(
    client_admin_a, org_b
):
    b_model = _realtime_transcription_model(org_b, is_custom=True, name="b-rtm")
    resp = client_admin_a.post(
        "/api/realtime-transcription-model-configs/",
        {"custom_name": "c", "realtime_transcription_model": b_model.id},
        format="json",
    )
    assert _rejected(resp), resp.data


# ---- #7 PythonCodeToolConfig.tool (hybrid) ----


@pytest.mark.django_db
def test_pythoncodetoolconfig_rejects_cross_org_tool(client_admin_a, org_b):
    b_tool = _python_tool(org_b, name="b-tool")
    resp = client_admin_a.post(
        "/api/python-code-tool-configs/",
        {"name": "c", "tool": b_tool.id, "configuration": {}},
        format="json",
    )
    assert _rejected(resp), resp.data


@pytest.mark.django_db
def test_pythoncodetoolconfig_allows_builtin_tool(client_admin_a):
    builtin = _python_tool(None, built_in=True, name="builtin-tool-cfg")
    resp = client_admin_a.post(
        "/api/python-code-tool-configs/",
        {"name": "c", "tool": builtin.id, "configuration": {}},
        format="json",
    )
    assert resp.status_code == 201, resp.data
