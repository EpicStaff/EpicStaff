import pytest
from django.urls import reverse

from agents.models import AgentDefinition, Surface
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

EXECUTION_FIELD_BOUNDS = [
    ("max_iter", 1, 90, 15),
    ("max_rpm", 1, 240, 30),
    ("max_execution_time", 60, 1800, 600),
    ("max_retry_limit", 0, 10, 3),
    ("schema_max_retries", 0, 20, 2),
    ("max_tool_calls", 1, 300, 15),
    ("tool_timeout", 10, 1800, 300),
    ("max_consecutive_failures", 1, 20, 3),
]


@pytest.fixture
def client(client_as, admin_acme, acme):
    api_client = client_as(admin_acme)
    api_client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return api_client


def _create(client, **fields):
    return client.post(
        reverse("agentdefinition-list"),
        {"name": "agent", "instruction_list": [{"name": "Instruction_1.md", "content": "do things"}], **fields},
        format="json",
    )


def _assert_invalid(response, field_name, code="invalid"):
    body = response.json()
    assert response.status_code == 400, body
    assert body["status_code"] == 400
    assert body["code"] == code
    assert field_name in body["message"]


@pytest.mark.django_db
class TestAgentDefinitionNameUniqueness:
    def test_create_duplicate_name_returns_400(self, client, acme):
        AgentDefinition.objects.create(organization=acme, name="duplicate-agent")

        response = _create(client, name="duplicate-agent")

        _assert_invalid(response, "name")
        assert AgentDefinition.objects.filter(name="duplicate-agent").count() == 1

    def test_put_duplicate_name_returns_400(self, client, acme):
        AgentDefinition.objects.create(organization=acme, name="existing-agent")
        other_agent = AgentDefinition.objects.create(organization=acme, name="other-agent")

        response = client.put(
            reverse("agentdefinition-detail", args=[other_agent.id]),
            {"name": "existing-agent", "instruction_list": [{"name": "Instruction_1.md", "content": "do other things"}]},
            format="json",
        )

        _assert_invalid(response, "name")
        other_agent.refresh_from_db()
        assert other_agent.name == "other-agent"

    def test_patch_keeping_own_name_returns_200(self, client, acme):
        agent = AgentDefinition.objects.create(organization=acme, name="same-agent")

        response = client.patch(
            reverse("agentdefinition-detail", args=[agent.id]),
            {"name": "same-agent", "description": "changed"},
            format="json",
        )

        assert response.status_code == 200, response.json()
        assert response.json()["description"] == "changed"

    def test_same_name_in_other_organization_returns_201(self, client, beta):
        AgentDefinition.objects.create(organization=beta, name="shared-name")

        response = _create(client, name="shared-name")

        assert response.status_code == 201, response.json()

    def test_create_success_returns_201(self, client):
        response = _create(client, name="new-agent")

        assert response.status_code == 201
        assert response.json()["name"] == "new-agent"

    def test_name_is_trimmed(self, client):
        response = _create(client, name="  padded-agent  ")

        assert response.status_code == 201, response.json()
        assert response.json()["name"] == "padded-agent"

    @pytest.mark.parametrize("name", ["", "   ", "x" * 256])
    def test_invalid_name_returns_400(self, client, name):
        _assert_invalid(_create(client, name=name), "name")

    def test_name_of_255_characters_returns_201(self, client):
        response = _create(client, name="x" * 255)

        assert response.status_code == 201, response.json()

    def test_other_organization_agent_is_not_found(self, client, beta):
        foreign_agent = AgentDefinition.objects.create(organization=beta, name="foreign")

        response = client.patch(
            reverse("agentdefinition-detail", args=[foreign_agent.id]),
            {"description": "hijacked"},
            format="json",
        )

        assert response.status_code == 404
        foreign_agent.refresh_from_db()
        assert foreign_agent.description == ""


@pytest.mark.django_db
class TestAgentDefinitionExecutionFieldBounds:
    @pytest.mark.parametrize("field_name,minimum,maximum,default", EXECUTION_FIELD_BOUNDS)
    def test_values_inside_bounds_are_accepted(
        self, client, field_name, minimum, maximum, default
    ):
        for value in (minimum, maximum):
            response = _create(client, name=f"agent-{value}", **{field_name: value})

            assert response.status_code == 201, response.json()
            assert response.json()[field_name] == value

    @pytest.mark.parametrize("field_name,minimum,maximum,default", EXECUTION_FIELD_BOUNDS)
    def test_values_outside_bounds_are_rejected(
        self, client, field_name, minimum, maximum, default
    ):
        for value in (minimum - 1, maximum + 1):
            _assert_invalid(_create(client, **{field_name: value}), field_name)

        assert not AgentDefinition.objects.exists()

    @pytest.mark.parametrize(
        "field_name", [field_name for field_name, *_ in EXECUTION_FIELD_BOUNDS] + ["cache"]
    )
    def test_null_is_rejected(self, client, field_name):
        _assert_invalid(_create(client, **{field_name: None}), field_name)

    def test_omitted_fields_take_model_defaults(self, client):
        response = _create(client)

        body = response.json()
        assert response.status_code == 201, body
        for field_name, _minimum, _maximum, default in EXECUTION_FIELD_BOUNDS:
            assert body[field_name] == default
        assert body["cache"] is False
        assert body["default_temperature"] is None

    def test_patch_out_of_range_value_returns_400(self, client, acme):
        agent = AgentDefinition.objects.create(organization=acme, name="patched")

        response = client.patch(
            reverse("agentdefinition-detail", args=[agent.id]),
            {"max_iter": 91},
            format="json",
        )

        _assert_invalid(response, "max_iter")
        agent.refresh_from_db()
        assert agent.max_iter == 15

    @pytest.mark.parametrize("value", [0, 2.0, None])
    def test_default_temperature_inside_bounds_or_null_is_accepted(self, client, value):
        response = _create(client, default_temperature=value)

        assert response.status_code == 201, response.json()
        assert response.json()["default_temperature"] == value

    @pytest.mark.parametrize("value", [-0.01, 2.01, "nan", "inf", "-inf"])
    def test_default_temperature_outside_bounds_is_rejected(self, client, value):
        _assert_invalid(_create(client, default_temperature=value), "default_temperature")


@pytest.mark.django_db
class TestAgentDefinitionDefaultSurfaces:
    def test_duplicate_surface_and_place_returns_400(self, client, acme):
        surface = Surface.objects.create(organization=acme, name="shared-surface")

        response = _create(
            client,
            default_surfaces=[
                {"surface": surface.id, "place": "flow"},
                {"surface": surface.id, "place": "flow"},
            ],
        )

        _assert_invalid(response, "default_surfaces", code="surface_invalid")
        assert not AgentDefinition.objects.exists()

    def test_same_surface_in_different_places_returns_201(self, client, acme):
        surface = Surface.objects.create(organization=acme, name="shared-surface")

        response = _create(
            client,
            default_surfaces=[
                {"surface": surface.id, "place": "flow"},
                {"surface": surface.id, "place": "chat"},
            ],
        )

        assert response.status_code == 201, response.json()
        assert len(response.json()["default_surfaces"]) == 2


DUPLICATE_INSTRUCTION_NAME_MESSAGE = (
    "An instruction with that name already exists. Please enter a unique name."
)


@pytest.mark.django_db
class TestAgentDefinitionInstructionList:
    def test_create_round_trips_ordered_instruction_list_and_compiled_instructions(
        self, client
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

    def test_create_strips_instruction_name(self, client):
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
        self, client
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
        self, client, instruction
    ):
        response = client.post(
            reverse("agentdefinition-list"),
            {"name": "invalid-instruction-agent", "instruction_list": [instruction]},
            format="json",
        )

        assert response.status_code == 400
        assert not AgentDefinition.objects.filter(name="invalid-instruction-agent").exists()

    def test_create_with_legacy_instructions_field_returns_400(self, client):
        response = client.post(
            reverse("agentdefinition-list"),
            {"name": "legacy-instructions-agent", "instructions": "You are a researcher."},
            format="json",
        )

        assert response.status_code == 400
        assert "instructions" in str(response.json())
        assert not AgentDefinition.objects.filter(name="legacy-instructions-agent").exists()

    def test_partial_update_replaces_instruction_list_in_new_order(self, client, acme):
        agent_definition = AgentDefinition.objects.create(
            organization=acme,
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
