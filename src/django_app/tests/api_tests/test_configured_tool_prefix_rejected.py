"""Regression: the deprecated `configured-tool:` tool_ids prefix must stay rejected.

`src/tool/` (the per-tool Docker container microservice) and the `ToolConfig`
model it backed are being retired. `AgentWriteSerializer._get_tools_models_map`
and `TaskWriteSerializer._get_tools_models_map` no longer list `ToolConfig`, so
`ToolsConnectionMixin.validate_tool_ids` has no entry for the "configured-tool"
prefix and rejects it with a 400 before any row is written (see
`tables/serializers/utils/mixins.py::validate_tool_ids`). If a future refactor
reintroduces that map entry, these tests must fail.

Deliberately does not create any `ToolConfig` row — the deployed DB has 0 rows
and the model is slated for removal. A live `python-code-tool:` prefix is used
as the positive control proving the assertion actually exercises the unknown-
prefix branch, not something incidental (auth, org scoping, missing field).
"""

import pytest
from rest_framework.test import APIClient

from tables.models import Agent, Crew
from tables.models.python_models import PythonCode, PythonCodeTool
from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="Org A")


@pytest.fixture
def client_admin_a(db, django_user_model, org_a):
    role = Role.objects.get(
        name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True
    )
    user = django_user_model.objects.create_user(
        email="configured-tool-prefix@e.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org_a, role=role)
    c = APIClient()
    c.force_authenticate(user=user)
    c.credentials(HTTP_X_ORGANIZATION_ID=str(org_a.id))
    return c


@pytest.fixture
def python_tool(org_a):
    code = PythonCode.objects.create(code="x", entrypoint="main")
    return PythonCodeTool.objects.create(
        name="tool", description="", python_code=code, org=org_a
    )


def _agent_payload(**extra):
    return {"role": "r", "goal": "g", "backstory": "b", **extra}


def _unknown_type_rejected(resp):
    # The global DRF exception handler (utils/exception_handler.py) wraps the
    # raised ValidationError's dict into {"code", "message", "status_code"},
    # stringifying the original {"tool_ids": [...]} payload into "message" —
    # so both checks must match on the stringified body rather than a key
    # lookup on resp.data itself.
    body = str(resp.data)
    return resp.status_code == 400 and "tool_ids" in body and "Unknown tool type" in body


# ---- Agent write path ----


@pytest.mark.django_db
def test_agent_rejects_configured_tool_prefix(client_admin_a):
    resp = client_admin_a.post(
        "/api/agents/",
        _agent_payload(tool_ids=["configured-tool:5"]),
        format="json",
    )
    assert _unknown_type_rejected(resp), resp.data
    assert not Agent.objects.filter(role="r").exists()


@pytest.mark.django_db
def test_agent_allows_live_python_code_tool_prefix(client_admin_a, python_tool):
    resp = client_admin_a.post(
        "/api/agents/",
        _agent_payload(tool_ids=[f"python-code-tool:{python_tool.id}"]),
        format="json",
    )
    assert resp.status_code == 201, resp.data


# ---- Task write path ----


@pytest.mark.django_db
def test_task_rejects_configured_tool_prefix(client_admin_a, org_a):
    crew = Crew.objects.create(name="c", org=org_a)
    agent = Agent.objects.create(role="r", goal="g", backstory="b", org=org_a)
    resp = client_admin_a.post(
        "/api/tasks/",
        {
            "name": "t",
            "instructions": "i",
            "expected_output": "o",
            "order": 1,
            "crew": crew.id,
            "agent": agent.id,
            "tool_ids": ["configured-tool:5"],
        },
        format="json",
    )
    assert _unknown_type_rejected(resp), resp.data


@pytest.mark.django_db
def test_task_allows_live_python_code_tool_prefix(client_admin_a, org_a, python_tool):
    crew = Crew.objects.create(name="c", org=org_a)
    agent = Agent.objects.create(role="r", goal="g", backstory="b", org=org_a)
    resp = client_admin_a.post(
        "/api/tasks/",
        {
            "name": "t",
            "instructions": "i",
            "expected_output": "o",
            "order": 1,
            "crew": crew.id,
            "agent": agent.id,
            "tool_ids": [f"python-code-tool:{python_tool.id}"],
        },
        format="json",
    )
    assert resp.status_code == 201, resp.data
