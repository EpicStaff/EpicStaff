import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from agents.models import AgentDefinition, Surface
from ai_models.models import LLMConfig, LLMModel, Provider
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
        AgentDefinition.objects.create(org=acme, name="duplicate-agent")

        response = _create(client, name="duplicate-agent")

        _assert_invalid(response, "name")
        assert AgentDefinition.objects.filter(name="duplicate-agent").count() == 1

    def test_put_duplicate_name_returns_400(self, client, acme):
        AgentDefinition.objects.create(org=acme, name="existing-agent")
        other_agent = AgentDefinition.objects.create(org=acme, name="other-agent")

        response = client.put(
            reverse("agentdefinition-detail", args=[other_agent.id]),
            {"name": "existing-agent", "instruction_list": [{"name": "Instruction_1.md", "content": "do other things"}]},
            format="json",
        )

        _assert_invalid(response, "name")
        other_agent.refresh_from_db()
        assert other_agent.name == "other-agent"

    def test_patch_keeping_own_name_returns_200(self, client, acme):
        agent = AgentDefinition.objects.create(org=acme, name="same-agent")

        response = client.patch(
            reverse("agentdefinition-detail", args=[agent.id]),
            {"name": "same-agent", "description": "changed"},
            format="json",
        )

        assert response.status_code == 200, response.json()
        assert response.json()["description"] == "changed"

    @pytest.mark.parametrize(
        ("name", "stored"),
        [
            ("new-agent", "new-agent"),
            ("  padded-agent  ", "padded-agent"),
            ("x" * 255, "x" * 255),
            # Names are unique per organization only.
            ("shared-name", "shared-name"),
        ],
        ids=["plain", "trimmed", "255-characters", "taken-in-another-org"],
    )
    def test_valid_name_is_created(self, client, beta, name, stored):
        AgentDefinition.objects.create(org=beta, name="shared-name")

        response = _create(client, name=name)

        assert response.status_code == 201, response.json()
        assert response.json()["name"] == stored

    @pytest.mark.parametrize("name", ["", "   ", "x" * 256])
    def test_invalid_name_returns_400(self, client, name):
        _assert_invalid(_create(client, name=name), "name")

    def test_other_organization_agent_is_not_found(self, client, beta):
        foreign_agent = AgentDefinition.objects.create(org=beta, name="foreign")

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
        "field_name",
        [field_name for field_name, *_ in EXECUTION_FIELD_BOUNDS] + ["prompt_caching_enabled"],
    )
    def test_null_is_rejected(self, client, field_name):
        _assert_invalid(_create(client, **{field_name: None}), field_name)

    def test_omitted_fields_take_model_defaults(self, client):
        response = _create(client)

        body = response.json()
        assert response.status_code == 201, body
        for field_name, _minimum, _maximum, default in EXECUTION_FIELD_BOUNDS:
            assert body[field_name] == default
        assert body["prompt_caching_enabled"] is False
        assert "cache" not in body
        assert body["default_temperature"] is None

    def test_patch_out_of_range_value_returns_400(self, client, acme):
        agent = AgentDefinition.objects.create(org=acme, name="patched")

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


def _llm_config(org, custom_name, provider_name, model_name):
    model = None
    if model_name is not None:
        provider = Provider.objects.get_or_create(name=provider_name)[0] if provider_name else None
        model = LLMModel.objects.get_or_create(name=model_name, llm_provider=provider)[0]
    return LLMConfig.objects.create(custom_name=custom_name, model=model, org=org)


@pytest.fixture
def claude_config(acme):
    return _llm_config(acme, "claude", "anthropic", "claude-sonnet-5-5")


@pytest.fixture
def gpt_config(acme):
    return _llm_config(acme, "gpt", "openai", "gpt-4o")


@pytest.fixture
def second_gpt_config(acme):
    return _llm_config(acme, "second-gpt", "openai", "gpt-4o-mini")


def _patch(client, agent, **fields):
    return client.patch(
        reverse("agentdefinition-detail", args=[agent.id]), fields, format="json"
    )


def _assert_prompt_caching(response, agent_id, expected):
    body = response.json()
    assert response.status_code in (200, 201), body
    assert body["prompt_caching_enabled"] is expected
    assert AgentDefinition.objects.get(id=agent_id).prompt_caching_enabled is expected


@pytest.mark.django_db
class TestAgentDefinitionPromptCaching:
    def test_patch_enables_prompt_caching(self, client, acme, claude_config):
        agent = AgentDefinition.objects.create(org=acme, name="caching", llm_config=claude_config)

        response = _patch(client, agent, prompt_caching_enabled=True)

        _assert_prompt_caching(response, agent.id, True)

    def test_create_with_removed_cache_field_ignores_it(self, client):
        response = _create(client, cache=True)

        body = response.json()
        assert response.status_code == 201, body
        assert body["prompt_caching_enabled"] is False
        assert AgentDefinition.objects.get(id=body["id"]).prompt_caching_enabled is False

    def test_patch_with_removed_cache_field_ignores_it(self, client, acme):
        agent = AgentDefinition.objects.create(org=acme, name="legacy-client")

        response = client.patch(
            reverse("agentdefinition-detail", args=[agent.id]),
            {"cache": True, "description": "changed"},
            format="json",
        )

        assert response.status_code == 200, response.json()
        agent.refresh_from_db()
        assert agent.description == "changed"
        assert agent.prompt_caching_enabled is False

    def test_member_of_other_organization_cannot_enable_prompt_caching(
        self, client_as, member_only, acme, beta
    ):
        foreign_agent = AgentDefinition.objects.create(org=beta, name="foreign")
        member_client = client_as(member_only)
        member_client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

        response = member_client.patch(
            reverse("agentdefinition-detail", args=[foreign_agent.id]),
            {"prompt_caching_enabled": True},
            format="json",
        )

        assert response.status_code == 404
        foreign_agent.refresh_from_db()
        assert foreign_agent.prompt_caching_enabled is False


@pytest.mark.django_db
class TestAgentDefinitionPromptCachingFollowsTheModels:
    """Caching is stored only while the primary or the fallback config takes cache markers."""

    @pytest.mark.parametrize(
        "provider_name, model_name",
        [
            ("openai", "gpt-4o"),
            # A model whose provider was deleted cannot run at all.
            (None, "claude-sonnet-5-5"),
            (None, None),
        ],
        ids=["openai-model", "model-without-provider", "config-without-model"],
    )
    def test_create_with_a_primary_taking_no_markers_saves_it_off(
        self, client, acme, provider_name, model_name
    ):
        config = _llm_config(acme, "primary", provider_name, model_name)

        response = _create(client, llm_config=config.id, prompt_caching_enabled=True)

        _assert_prompt_caching(response, response.json()["id"], False)

    def test_create_without_configs_saves_it_off(self, client):
        response = _create(client, prompt_caching_enabled=True)

        _assert_prompt_caching(response, response.json()["id"], False)

    def test_create_with_a_claude_primary_keeps_it_on(self, client, claude_config):
        response = _create(client, llm_config=claude_config.id, prompt_caching_enabled=True)

        _assert_prompt_caching(response, response.json()["id"], True)

    def test_create_with_a_claude_fallback_keeps_it_on(self, client, gpt_config, claude_config):
        response = _create(
            client,
            llm_config=gpt_config.id,
            fallback_llm_config=claude_config.id,
            prompt_caching_enabled=True,
        )

        _assert_prompt_caching(response, response.json()["id"], True)

    def test_patching_the_primary_to_another_model_turns_it_off(
        self, client, acme, claude_config, gpt_config
    ):
        agent = AgentDefinition.objects.create(
            org=acme, name="caching", llm_config=claude_config, prompt_caching_enabled=True
        )

        response = _patch(client, agent, llm_config=gpt_config.id)

        _assert_prompt_caching(response, agent.id, False)

    def test_put_with_another_primary_turns_it_off(self, client, acme, claude_config, gpt_config):
        agent = AgentDefinition.objects.create(
            org=acme, name="caching", llm_config=claude_config, prompt_caching_enabled=True
        )

        response = client.put(
            reverse("agentdefinition-detail", args=[agent.id]),
            {"name": "caching", "llm_config": gpt_config.id, "prompt_caching_enabled": True},
            format="json",
        )

        _assert_prompt_caching(response, agent.id, False)

    def test_patching_the_primary_keeps_it_on_while_the_fallback_is_claude(
        self, client, acme, claude_config, gpt_config, second_gpt_config
    ):
        agent = AgentDefinition.objects.create(
            org=acme,
            name="caching",
            llm_config=gpt_config,
            fallback_llm_config=claude_config,
            prompt_caching_enabled=True,
        )

        response = _patch(client, agent, llm_config=second_gpt_config.id)

        _assert_prompt_caching(response, agent.id, True)

    def test_enabling_it_on_an_agent_without_claude_configs_keeps_it_off(
        self, client, acme, gpt_config, second_gpt_config
    ):
        agent = AgentDefinition.objects.create(
            org=acme, name="caching", llm_config=gpt_config, fallback_llm_config=second_gpt_config
        )

        response = _patch(client, agent, prompt_caching_enabled=True)

        _assert_prompt_caching(response, agent.id, False)

    def test_switching_back_to_claude_does_not_turn_it_on_again(
        self, client, acme, claude_config, gpt_config
    ):
        agent = AgentDefinition.objects.create(
            org=acme, name="caching", llm_config=claude_config, prompt_caching_enabled=True
        )
        _patch(client, agent, llm_config=gpt_config.id)

        response = _patch(client, agent, llm_config=claude_config.id)

        _assert_prompt_caching(response, agent.id, False)

    def test_claude_config_of_another_organization_is_rejected(
        self, client, acme, beta, gpt_config
    ):
        foreign_config = _llm_config(beta, "foreign-claude", "anthropic", "claude-sonnet-5-5")
        agent = AgentDefinition.objects.create(org=acme, name="caching", llm_config=gpt_config)

        response = _patch(
            client, agent, llm_config=foreign_config.id, prompt_caching_enabled=True
        )

        _assert_invalid(response, "llm_config")
        agent.refresh_from_db()
        assert agent.llm_config_id == gpt_config.id
        assert agent.prompt_caching_enabled is False

    @pytest.mark.parametrize("configs_sent", [False, True], ids=["stored-configs", "sent-configs"])
    def test_the_rule_adds_no_query_per_config(self, client, acme, claude_config, configs_sent):
        # Configs without a model have nothing to load, so a lazy load of the Claude
        # configs' model or provider would show up as extra queries.
        claude_fallback = _llm_config(acme, "claude-fallback", "anthropic", "claude-sonnet-5-5")
        modelless_primary = _llm_config(acme, "modelless-primary", None, None)
        modelless_fallback = _llm_config(acme, "modelless-fallback", None, None)

        def patch_query_count(name, primary, fallback):
            if configs_sent:
                agent = AgentDefinition.objects.create(org=acme, name=name)
                fields = {"llm_config": primary.id, "fallback_llm_config": fallback.id}
            else:
                agent = AgentDefinition.objects.create(
                    org=acme, name=name, llm_config=primary, fallback_llm_config=fallback
                )
                fields = {}
            # A changed description makes both requests record the edit: without it only
            # the Claude agent, whose switch stays on, would change and pay for that record.
            fields["description"] = f"{name} edited"
            with CaptureQueriesContext(connection) as queries:
                response = _patch(client, agent, prompt_caching_enabled=True, **fields)
            assert response.status_code == 200, response.json()
            return len(queries)

        # The first request warms caches (content types) that the measured ones share.
        patch_query_count("warm-up", modelless_primary, modelless_fallback)
        assert patch_query_count("claude", claude_config, claude_fallback) == patch_query_count(
            "modelless", modelless_primary, modelless_fallback
        )


@pytest.mark.django_db
class TestAgentDefinitionDefaultSurfaces:
    def test_duplicate_surface_and_place_returns_400(self, client, acme):
        surface = Surface.objects.create(org=acme, name="shared-surface")

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
        surface = Surface.objects.create(org=acme, name="shared-surface")

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
            org=acme,
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
