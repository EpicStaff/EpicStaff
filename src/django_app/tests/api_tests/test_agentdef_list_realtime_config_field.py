"""Regression test: agent_definition_realtime_config_id must be present on
GET /api/agent-definitions/ (list), matching what retrieve returns, for both
an AgentDefinition with a related RealtimeAgentDefinition and one without.
"""

import pytest
from django.test.utils import CaptureQueriesContext
from django.db import connection
from rest_framework.test import APIClient

from agents.models import AgentDefinition
from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole
from tables.models.realtime_models import OpenAIRealtimeConfig, RealtimeAgentDefinition


@pytest.fixture
def role_member(db):
    return Role.objects.get(name=BuiltInRole.MEMBER, is_built_in=True, org__isnull=True)


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="Org A")


@pytest.fixture
def member_a(db, django_user_model, org_a, role_member):
    user = django_user_model.objects.create_user(
        email="member_a@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org_a, role=role_member)
    return user


@pytest.fixture
def client_a(member_a, org_a):
    client = APIClient()
    client.force_authenticate(user=member_a)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org_a.id))
    return client


def _rows(body):
    return body["results"] if isinstance(body, dict) and "results" in body else body


@pytest.mark.django_db
def test_agentdef_list_includes_realtime_config_id_with_and_without_realtime_agent(
    client_a, org_a
):
    agent_definition_with_realtime = AgentDefinition.objects.create(
        name="ad-with-realtime", organization=org_a
    )
    realtime_config = OpenAIRealtimeConfig.objects.create(
        custom_name="c", org=org_a
    )
    RealtimeAgentDefinition.objects.create(
        agent_definition=agent_definition_with_realtime,
        openai_config=realtime_config,
    )

    agent_definition_without_realtime = AgentDefinition.objects.create(
        name="ad-without-realtime", organization=org_a
    )

    list_response = client_a.get("/api/agent-definitions/")
    assert list_response.status_code == 200
    list_items_by_id = {row["id"]: row for row in _rows(list_response.data)}

    with_realtime_row = list_items_by_id[agent_definition_with_realtime.id]
    without_realtime_row = list_items_by_id[agent_definition_without_realtime.id]

    assert "agent_definition_realtime_config_id" in with_realtime_row
    assert "agent_definition_realtime_config_id" in without_realtime_row
    assert (
        with_realtime_row["agent_definition_realtime_config_id"] == realtime_config.id
    )
    assert without_realtime_row["agent_definition_realtime_config_id"] is None

    assert with_realtime_row["has_realtime_definition"] is True
    assert without_realtime_row["has_realtime_definition"] is False

    retrieve_with_realtime = client_a.get(
        f"/api/agent-definitions/{agent_definition_with_realtime.id}/"
    )
    retrieve_without_realtime = client_a.get(
        f"/api/agent-definitions/{agent_definition_without_realtime.id}/"
    )
    assert retrieve_with_realtime.status_code == 200
    assert retrieve_without_realtime.status_code == 200

    assert (
        with_realtime_row["agent_definition_realtime_config_id"]
        == retrieve_with_realtime.data["agent_definition_realtime_config_id"]
    )
    assert (
        without_realtime_row["agent_definition_realtime_config_id"]
        == retrieve_without_realtime.data["agent_definition_realtime_config_id"]
    )
    assert retrieve_with_realtime.data["has_realtime_definition"] is True
    assert retrieve_without_realtime.data["has_realtime_definition"] is False


def _create_agent_definitions_with_realtime_config(org, count, name_prefix):
    for index in range(count):
        agent_definition = AgentDefinition.objects.create(
            name=f"ad-{name_prefix}-{index}", organization=org
        )
        realtime_config = OpenAIRealtimeConfig.objects.create(
            custom_name=f"c-{name_prefix}-{index}",
            org=org,
        )
        RealtimeAgentDefinition.objects.create(
            agent_definition=agent_definition, openai_config=realtime_config
        )


@pytest.mark.django_db
def test_agentdef_list_does_not_issue_per_row_query_for_realtime_config(
    client_a, org_a
):
    _create_agent_definitions_with_realtime_config(
        org_a, count=2, name_prefix="small"
    )

    with CaptureQueriesContext(connection) as captured_queries_small:
        small_response = client_a.get("/api/agent-definitions/")

    assert small_response.status_code == 200
    assert len(_rows(small_response.data)) == 2
    small_query_count = len(captured_queries_small.captured_queries)

    _create_agent_definitions_with_realtime_config(
        org_a, count=6, name_prefix="large"
    )

    with CaptureQueriesContext(connection) as captured_queries_large:
        large_response = client_a.get("/api/agent-definitions/")

    assert large_response.status_code == 200
    assert len(_rows(large_response.data)) == 8
    large_query_count = len(captured_queries_large.captured_queries)

    assert large_query_count == small_query_count, (
        "expected query count to stay constant as row count grows (no N+1 for "
        f"realtime config); got {small_query_count} queries for 2 rows and "
        f"{large_query_count} queries for 8 rows: "
        f"{[q['sql'] for q in captured_queries_large.captured_queries]}"
    )
