import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from tables.constants.organization_constants import DEFAULT_ORGANIZATION_NAME
from agents.models import AgentDefinition
from rbac.models import Organization


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
            instruction_list=[{"name": "Instruction_1.md", "content": "do things"}],
        )

        url = reverse("agentdefinition-list")
        response = client.post(
            url,
            {"name": "duplicate-agent", "instruction_list": [{"name": "Instruction_1.md", "content": "do other things"}]},
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
            instruction_list=[{"name": "Instruction_1.md", "content": "do things"}],
        )
        other_agent = AgentDefinition.objects.create(
            organization=default_organization,
            name="other-agent",
            instruction_list=[{"name": "Instruction_1.md", "content": "do other things"}],
        )

        url = reverse("agentdefinition-detail", args=[other_agent.id])
        response = client.put(
            url,
            {"name": "existing-agent", "instruction_list": [{"name": "Instruction_1.md", "content": "do other things"}]},
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
            {"name": "new-agent", "instruction_list": [{"name": "Instruction_1.md", "content": "do things"}]},
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
            {"name": "zero-agent", "instruction_list": [{"name": "Instruction_1.md", "content": "do things"}], "max_tool_calls": 0},
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
            {"name": "null-agent", "instruction_list": [{"name": "Instruction_1.md", "content": "do things"}], "max_tool_calls": None},
            format="json",
        )

        body = response.json()
        assert response.status_code == 201
        assert body["max_tool_calls"] is None


@pytest.mark.django_db
class TestAgentDefinitionSchemaMaxRetriesValidation:
    def test_create_with_schema_max_retries_negative_returns_400(
        self, client, default_organization
    ):
        url = reverse("agentdefinition-list")
        response = client.post(
            url,
            {
                "name": "negative-agent",
                "instruction_list": [{"name": "Instruction_1.md", "content": "do things"}],
                "schema_max_retries": -1,
            },
            format="json",
        )

        assert response.status_code == 400
        assert "schema_max_retries" in response.json()["message"]

    def test_create_with_schema_max_retries_zero_returns_201(
        self, client, default_organization
    ):
        url = reverse("agentdefinition-list")
        response = client.post(
            url,
            {
                "name": "zero-retries-agent",
                "instruction_list": [{"name": "Instruction_1.md", "content": "do things"}],
                "schema_max_retries": 0,
            },
            format="json",
        )

        body = response.json()
        assert response.status_code == 201
        assert body["schema_max_retries"] == 0

    def test_create_with_schema_max_retries_positive_returns_201(
        self, client, default_organization
    ):
        url = reverse("agentdefinition-list")
        response = client.post(
            url,
            {
                "name": "positive-retries-agent",
                "instruction_list": [{"name": "Instruction_1.md", "content": "do things"}],
                "schema_max_retries": 3,
            },
            format="json",
        )

        body = response.json()
        assert response.status_code == 201
        assert body["schema_max_retries"] == 3

    def test_create_with_schema_max_retries_null_returns_201(
        self, client, default_organization
    ):
        url = reverse("agentdefinition-list")
        response = client.post(
            url,
            {
                "name": "null-retries-agent",
                "instruction_list": [{"name": "Instruction_1.md", "content": "do things"}],
                "schema_max_retries": None,
            },
            format="json",
        )

        body = response.json()
        assert response.status_code == 201
        assert body["schema_max_retries"] is None


DUPLICATE_INSTRUCTION_NAME_MESSAGE = (
    "An instruction with that name already exists. Please enter a unique name."
)


@pytest.mark.django_db
class TestAgentDefinitionInstructionList:
    def test_create_round_trips_ordered_instruction_list_and_compiled_instructions(
        self, client, default_organization
    ):
        instruction_list = [
            {"name": "Persona.md", "content": "You are a researcher."},
            {"name": "Empty.md", "content": "   "},
            {"name": "Rules.md", "content": "Cite sources."},
        ]

        response = client.post(
            reverse("agentdefinition-list"),
            {"name": "multi-instruction-agent", "instruction_list": instruction_list},
            format="json",
        )

        assert response.status_code == 201
        body = response.json()
        assert body["instruction_list"] == instruction_list
        assert body["instructions"] == "You are a researcher.\n\nCite sources."
        agent_definition = AgentDefinition.objects.get(id=body["id"])
        assert agent_definition.instruction_list == instruction_list

    def test_create_strips_instruction_name(self, client, default_organization):
        response = client.post(
            reverse("agentdefinition-list"),
            {
                "name": "stripped-name-agent",
                "instruction_list": [{"name": "  Rules.md  ", "content": "x"}],
            },
            format="json",
        )

        assert response.status_code == 201
        assert response.json()["instruction_list"] == [{"name": "Rules.md", "content": "x"}]

    def test_create_with_duplicate_instruction_names_case_insensitive_returns_400(
        self, client, default_organization
    ):
        response = client.post(
            reverse("agentdefinition-list"),
            {
                "name": "duplicate-instruction-agent",
                "instruction_list": [
                    {"name": "Rules.md", "content": "a"},
                    {"name": "RULES.md", "content": "b"},
                ],
            },
            format="json",
        )

        assert response.status_code == 400
        assert DUPLICATE_INSTRUCTION_NAME_MESSAGE in str(response.json())
        assert not AgentDefinition.objects.filter(name="duplicate-instruction-agent").exists()

    @pytest.mark.parametrize(
        "instruction",
        [
            {"name": "   ", "content": "x"},
            {"name": "a" * 256, "content": "x"},
            {"content": "x"},
            {"name": "Rules.md"},
            {"name": "Rules.md", "content": "x", "extra": "y"},
            "plain string",
        ],
    )
    def test_create_with_invalid_instruction_returns_400(
        self, client, default_organization, instruction
    ):
        response = client.post(
            reverse("agentdefinition-list"),
            {"name": "invalid-instruction-agent", "instruction_list": [instruction]},
            format="json",
        )

        assert response.status_code == 400
        assert not AgentDefinition.objects.filter(name="invalid-instruction-agent").exists()

    def test_create_with_legacy_instructions_field_returns_400(self, client, default_organization):
        response = client.post(
            reverse("agentdefinition-list"),
            {"name": "legacy-instructions-agent", "instructions": "You are a researcher."},
            format="json",
        )

        assert response.status_code == 400
        assert "instructions" in response.json()
        assert not AgentDefinition.objects.filter(name="legacy-instructions-agent").exists()

    def test_partial_update_replaces_instruction_list_in_new_order(
        self, client, default_organization
    ):
        agent_definition = AgentDefinition.objects.create(
            organization=default_organization,
            name="reorder-agent",
            instruction_list=[
                {"name": "First.md", "content": "one"},
                {"name": "Second.md", "content": "two"},
            ],
        )

        response = client.patch(
            reverse("agentdefinition-detail", args=[agent_definition.id]),
            {
                "instruction_list": [
                    {"name": "Second.md", "content": "two"},
                    {"name": "First.md", "content": "one"},
                ]
            },
            format="json",
        )

        assert response.status_code == 200
        agent_definition.refresh_from_db()
        assert [item["name"] for item in agent_definition.instruction_list] == [
            "Second.md",
            "First.md",
        ]
        assert agent_definition.instructions == "two\n\none"
