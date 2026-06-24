"""Cross-org reference rejection (security regression tests).

A write in org A must never be able to attach / reference an org B object via
tool_ids, knowledge_collection, rag, or config FKs. Each is rejected exactly
like a non-existent pk (no existence leak).
"""

import pytest
from rest_framework.test import APIClient

from tables.models import Agent, Crew, SourceCollection
from tables.models.llm_models import LLMConfig
from tables.models.mcp_models import McpTool
from tables.models.python_models import PythonCode, PythonCodeTool
from tables.models.knowledge_models import BaseRagType, NaiveRag
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
        args_schema={},
        python_code=code,
        built_in=built_in,
        org=org,
    )


def _mcp(org, name="mcp"):
    return McpTool.objects.create(name=name, transport="t", tool_name="x", org=org)


def _llm_config(org, name="cfg"):
    return LLMConfig.objects.create(custom_name=name, org=org)


def _naive_rag(org):
    coll = SourceCollection.objects.create(collection_name="c", org=org)
    brt = BaseRagType.objects.create(
        rag_type=BaseRagType.RagType.NAIVE, source_collection=coll
    )
    return coll, NaiveRag.objects.create(base_rag_type=brt)


def _agent_payload(**extra):
    return {"role": "r", "goal": "g", "backstory": "b", **extra}


def _rejected(resp):
    return resp.status_code == 400 and "does not exist" in str(resp.data)


# ---- Agent: tool_ids ----


@pytest.mark.django_db
def test_agent_rejects_cross_org_python_tool(client_admin_a, org_b):
    b_tool = _python_tool(org_b, name="b-tool")
    resp = client_admin_a.post(
        "/api/agents/",
        _agent_payload(tool_ids=[f"python-code-tool:{b_tool.id}"]),
        format="json",
    )
    assert _rejected(resp), resp.data


@pytest.mark.django_db
def test_agent_rejects_cross_org_mcp_tool(client_admin_a, org_b):
    b_mcp = _mcp(org_b, name="b-mcp")
    resp = client_admin_a.post(
        "/api/agents/",
        _agent_payload(tool_ids=[f"mcp-tool:{b_mcp.id}"]),
        format="json",
    )
    assert _rejected(resp), resp.data


@pytest.mark.django_db
def test_agent_allows_builtin_python_tool(client_admin_a):
    builtin = _python_tool(None, built_in=True, name="builtin-tool")
    resp = client_admin_a.post(
        "/api/agents/",
        _agent_payload(tool_ids=[f"python-code-tool:{builtin.id}"]),
        format="json",
    )
    assert resp.status_code == 201, resp.data  # built-ins are global


@pytest.mark.django_db
def test_agent_allows_same_org_python_tool(client_admin_a, org_a):
    a_tool = _python_tool(org_a, name="a-tool")
    resp = client_admin_a.post(
        "/api/agents/",
        _agent_payload(tool_ids=[f"python-code-tool:{a_tool.id}"]),
        format="json",
    )
    assert resp.status_code == 201, resp.data


# ---- Agent: knowledge_collection + rag ----


@pytest.mark.django_db
def test_agent_rejects_cross_org_knowledge_collection(client_admin_a, org_b):
    b_coll, b_rag = _naive_rag(org_b)
    resp = client_admin_a.post(
        "/api/agents/",
        _agent_payload(
            knowledge_collection=b_coll.collection_id,
            rag={"rag_id": b_rag.naive_rag_id, "rag_type": "naive"},
        ),
        format="json",
    )
    assert _rejected(resp), resp.data


@pytest.mark.django_db
def test_agent_rejects_cross_org_rag(client_admin_a, org_a, org_b):
    a_coll = SourceCollection.objects.create(collection_name="a", org=org_a)
    _, b_rag = _naive_rag(org_b)
    resp = client_admin_a.post(
        "/api/agents/",
        _agent_payload(
            knowledge_collection=a_coll.collection_id,  # valid (own org)
            rag={"rag_id": b_rag.naive_rag_id, "rag_type": "naive"},  # cross-org
        ),
        format="json",
    )
    assert _rejected(resp), resp.data


# ---- Task: tool_ids ----


@pytest.mark.django_db
def test_task_rejects_cross_org_python_tool(client_admin_a, org_a, org_b):
    crew = Crew.objects.create(name="c", org=org_a)
    agent = Agent.objects.create(role="r", goal="g", backstory="b", org=org_a)
    b_tool = _python_tool(org_b, name="b-tool")
    resp = client_admin_a.post(
        "/api/tasks/",
        {
            "name": "t",
            "instructions": "i",
            "expected_output": "o",
            "order": 1,
            "crew": crew.id,
            "agent": agent.id,
            "tool_ids": [f"python-code-tool:{b_tool.id}"],
        },
        format="json",
    )
    assert _rejected(resp), resp.data


# ---- Crew: config FK ----


@pytest.mark.django_db
def test_crew_rejects_cross_org_manager_llm_config(client_admin_a, org_a, org_b):
    crew = Crew.objects.create(name="c", org=org_a)
    b_cfg = _llm_config(org_b, name="b-cfg")
    resp = client_admin_a.patch(
        f"/api/crews/{crew.id}/",
        {"manager_llm_config": b_cfg.id},
        format="json",
    )
    assert _rejected(resp), resp.data
