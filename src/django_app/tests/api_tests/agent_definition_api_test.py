import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from tables.constants.organization_constants import DEFAULT_ORGANIZATION_NAME
from tables.models.agent_models import AgentDefinition
from tables.models.rbac_models import Organization


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def default_organization(db) -> Organization:
    """Organization matching AgentDefinitionViewSet._get_organization()."""
    return Organization.objects.get_or_create(name=DEFAULT_ORGANIZATION_NAME)[0]


@pytest.mark.django_db
class TestAgentDefinitionConflict:
    def test_create_duplicate_name_returns_409_with_matching_status_code(
        self, client, default_organization
    ):
        AgentDefinition.objects.create(
            organization=default_organization,
            name="duplicate-agent",
            instructions="do things",
        )

        url = reverse("agentdefinition-list")
        response = client.post(
            url,
            {"name": "duplicate-agent", "instructions": "do other things"},
            format="json",
        )

        body = response.json()
        assert response.status_code == 409
        assert body["status_code"] == 409
        assert body["code"] == "agent_definition_conflict"
        assert AgentDefinition.objects.filter(name="duplicate-agent").count() == 1

    def test_update_duplicate_name_returns_409_with_matching_status_code(
        self, client, default_organization
    ):
        AgentDefinition.objects.create(
            organization=default_organization,
            name="existing-agent",
            instructions="do things",
        )
        other_agent = AgentDefinition.objects.create(
            organization=default_organization,
            name="other-agent",
            instructions="do other things",
        )

        url = reverse("agentdefinition-detail", args=[other_agent.id])
        response = client.put(
            url,
            {"name": "existing-agent", "instructions": "do other things"},
            format="json",
        )

        body = response.json()
        assert response.status_code == 409
        assert body["status_code"] == 409
        assert body["code"] == "agent_definition_conflict"

    def test_create_success_returns_201(self, client, default_organization):
        url = reverse("agentdefinition-list")
        response = client.post(
            url,
            {"name": "new-agent", "instructions": "do things"},
            format="json",
        )

        body = response.json()
        assert response.status_code == 201
        assert body["name"] == "new-agent"


@pytest.mark.django_db
class TestAgentDefinitionRunLimitValidation:
    def test_create_with_max_tool_calls_zero_returns_400(
        self, client, default_organization
    ):
        url = reverse("agentdefinition-list")
        response = client.post(
            url,
            {"name": "zero-agent", "instructions": "do things", "max_tool_calls": 0},
            format="json",
        )

        assert response.status_code == 400
        assert "max_tool_calls" in response.json()["message"]

    def test_create_with_max_tool_calls_null_returns_201(
        self, client, default_organization
    ):
        url = reverse("agentdefinition-list")
        response = client.post(
            url,
            {"name": "null-agent", "instructions": "do things", "max_tool_calls": None},
            format="json",
        )

        body = response.json()
        assert response.status_code == 201
        assert body["max_tool_calls"] is None
