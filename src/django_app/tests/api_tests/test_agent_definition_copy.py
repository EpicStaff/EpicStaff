"""POST /api/agent-definitions/{id}/copy/ duplicates an agent server-side.

Shared default surfaces are re-linked; surfaces the agent owns are cloned for the
copy, with their content, so the copy never points at the source's own surfaces.
"""

from decimal import Decimal

import pytest
from django.contrib.contenttypes.models import ContentType

from agents.models import AgentDefaultSurface, AgentDefinition, Surface, SurfacePlace, ToolMode
from agents.models.surface_models import (
    StorageAccess,
    SurfaceGraphBasicSearchConfig,
    SurfaceKnowledge,
    SurfaceMcpTool,
    SurfaceNaiveSearchConfig,
    SurfacePythonTool,
    SurfaceStorageItem,
)
from rbac.access.catalog import grantable_bits_for
from rbac.models import ResourceLastEdit
from rbac.models.enums import Permission, ResourceType
from tables.models import Label, LLMConfig, McpTool, SourceCollection, StorageFile
from tables.models.realtime_models import OpenAIRealtimeConfig, RealtimeAgentDefinition
from tests.fixtures import *  # noqa: F401,F403
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


def _copy_url(agent_id: int) -> str:
    return f"/api/agent-definitions/{agent_id}/copy/"


def _default_surfaces_of(agent: AgentDefinition) -> set[tuple[int, str]]:
    return {
        (row.surface_id, row.place)
        for row in AgentDefaultSurface.objects.filter(agent_definition=agent)
    }


def _last_editor_id(instance) -> int | None:
    last_edit = ResourceLastEdit.objects.filter(
        content_type=ContentType.objects.get_for_model(instance), object_id=instance.pk
    ).first()
    return last_edit.edited_by_id if last_edit else None


@pytest.fixture
def source_agent(default_org) -> AgentDefinition:
    return AgentDefinition.objects.create(org=default_org, name="Writer")


@pytest.mark.django_db
class TestDefaultSurfaces:
    def test_shared_surfaces_are_relinked_and_owned_ones_cloned(
        self, auth_client, default_org, source_agent
    ):
        shared = Surface.objects.create(org=default_org, name="Shared")
        owned_explicit = Surface.objects.create(
            org=default_org, name="Owned explicit", owner_agent=source_agent
        )
        owned_implicit = Surface.objects.create(
            org=default_org, name="Owned implicit", owner_agent=source_agent
        )
        AgentDefaultSurface.objects.create(
            agent_definition=source_agent, surface=shared, place=SurfacePlace.FLOW
        )
        AgentDefaultSurface.objects.create(
            agent_definition=source_agent, surface=owned_explicit, place=SurfacePlace.CHAT
        )
        source_defaults_before = _default_surfaces_of(source_agent)

        response = auth_client.post(_copy_url(source_agent.id), {}, format="json")

        assert response.status_code == 201, response.data
        new_agent = AgentDefinition.objects.get(pk=response.data["id"])
        assert new_agent.org_id == default_org.id
        explicit_clone = Surface.objects.get(owner_agent=new_agent, name="Owned explicit #2")
        implicit_clone = Surface.objects.get(owner_agent=new_agent, name="Owned implicit #2")
        assert {explicit_clone.id, implicit_clone.id}.isdisjoint(
            {owned_explicit.id, owned_implicit.id}
        )
        assert explicit_clone.org_id == default_org.id
        assert explicit_clone.group_id is None
        # The implicit "applies everywhere" owned surface stays implicit: no row.
        assert _default_surfaces_of(new_agent) == {
            (shared.id, SurfacePlace.FLOW),
            (explicit_clone.id, SurfacePlace.CHAT),
        }
        assert sorted(
            response.data["default_surfaces"], key=lambda item: item["surface"]
        ) == sorted(
            [
                {"surface": shared.id, "place": SurfacePlace.FLOW},
                {"surface": explicit_clone.id, "place": SurfacePlace.CHAT},
                {"surface": implicit_clone.id, "place": SurfacePlace.ALL},
            ],
            key=lambda item: item["surface"],
        )
        # The source keeps its own surfaces and links.
        assert _default_surfaces_of(source_agent) == source_defaults_before
        assert set(Surface.objects.filter(owner_agent=source_agent).values_list("id", flat=True)) == {
            owned_explicit.id,
            owned_implicit.id,
        }
        assert Surface.objects.get(pk=shared.id).owner_agent_id is None

    def test_binned_owned_surface_is_not_cloned(self, auth_client, default_org, source_agent):
        owned = Surface.objects.create(org=default_org, name="Gone", owner_agent=source_agent)
        AgentDefaultSurface.objects.create(
            agent_definition=source_agent, surface=owned, place=SurfacePlace.FLOW
        )
        owned.delete()

        response = auth_client.post(_copy_url(source_agent.id), {}, format="json")

        assert response.status_code == 201, response.data
        new_agent = AgentDefinition.objects.get(pk=response.data["id"])
        assert not Surface.all_objects.filter(owner_agent=new_agent).exists()
        assert not AgentDefaultSurface.all_objects.filter(agent_definition=new_agent).exists()
        assert response.data["default_surfaces"] == []

    def test_binned_shared_surface_is_not_linked(self, auth_client, default_org, source_agent):
        shared = Surface.objects.create(org=default_org, name="Shared gone")
        AgentDefaultSurface.objects.create(
            agent_definition=source_agent, surface=shared, place=SurfacePlace.CHAT
        )
        shared.delete()

        response = auth_client.post(_copy_url(source_agent.id), {}, format="json")

        assert response.status_code == 201, response.data
        new_agent = AgentDefinition.objects.get(pk=response.data["id"])
        assert not AgentDefaultSurface.all_objects.filter(agent_definition=new_agent).exists()


@pytest.mark.django_db
def test_owned_surface_content_is_cloned_independently(
    auth_client, default_org, source_agent, python_code_tool
):
    owned = Surface.objects.create(
        org=default_org, name="Toolbox", instructions="use tools", owner_agent=source_agent
    )
    mcp_tool = McpTool.objects.create(
        org=default_org, name="copy-mcp", transport="https://example.com/mcp", tool_name="search"
    )
    storage_file = StorageFile.objects.create(org=default_org, path="notes.txt", name="notes.txt")
    collection = SourceCollection.objects.create(org=default_org, collection_name="docs")
    SurfacePythonTool.objects.create(surface=owned, python_tool=python_code_tool, mode=ToolMode.ALLOW)
    SurfaceMcpTool.objects.create(surface=owned, mcp_tool=mcp_tool, mode=ToolMode.DENY)
    SurfaceStorageItem.objects.create(
        surface=owned,
        storage_file=storage_file,
        can_list=StorageAccess.ALLOW,
        can_view=StorageAccess.DENY,
        can_edit=StorageAccess.UNSET,
        can_delete=StorageAccess.ALLOW,
    )
    knowledge = SurfaceKnowledge.objects.create(surface=owned, collection=collection)
    SurfaceNaiveSearchConfig.objects.create(
        surface_knowledge=knowledge, search_limit=7, similarity_threshold=Decimal("0.55")
    )
    SurfaceGraphBasicSearchConfig.objects.create(surface_knowledge=knowledge, k=4)

    response = auth_client.post(_copy_url(source_agent.id), {}, format="json")

    assert response.status_code == 201, response.data
    clone = Surface.objects.get(owner_agent_id=response.data["id"])
    assert clone.instructions == "use tools"
    assert list(SurfacePythonTool.objects.filter(surface=clone).values_list("python_tool_id", "mode")) == [
        (python_code_tool.id, ToolMode.ALLOW)
    ]
    assert list(SurfaceMcpTool.objects.filter(surface=clone).values_list("mcp_tool_id", "mode")) == [
        (mcp_tool.id, ToolMode.DENY)
    ]
    assert list(
        SurfaceStorageItem.objects.filter(surface=clone).values_list(
            "storage_file_id", "can_list", "can_view", "can_edit", "can_delete"
        )
    ) == [
        (
            storage_file.id,
            StorageAccess.ALLOW,
            StorageAccess.DENY,
            StorageAccess.UNSET,
            StorageAccess.ALLOW,
        )
    ]
    clone_knowledge = SurfaceKnowledge.objects.get(surface=clone)
    assert clone_knowledge.collection_id == collection.collection_id
    assert clone_knowledge.naive_search_config.search_limit == 7
    assert clone_knowledge.naive_search_config.similarity_threshold == Decimal("0.55")
    assert clone_knowledge.graph_basic_search_config.k == 4
    assert not hasattr(clone_knowledge, "graph_local_search_config")

    # Editing the clone leaves the source alone.
    SurfacePythonTool.objects.filter(surface=clone).delete()
    SurfaceKnowledge.objects.filter(surface=clone).delete()
    assert SurfacePythonTool.objects.filter(surface=owned).count() == 1
    assert SurfaceKnowledge.objects.filter(surface=owned).count() == 1


@pytest.mark.django_db
class TestAgentFields:
    def test_every_setting_is_copied(self, auth_client, default_org, llm_config, gpt_4o_llm):
        fallback = LLMConfig.objects.create(custom_name="fallback", model=gpt_4o_llm, org=default_org)
        fcm = LLMConfig.objects.create(custom_name="fcm", model=gpt_4o_llm, org=default_org)
        group = Label.objects.create(name="Sales", org=default_org, scope=Label.Scope.AGENT)
        source = AgentDefinition.objects.create(
            org=default_org,
            name="Tuned",
            description="does research",
            instruction_list=[{"name": "Goal.md", "content": "find things"}],
            metadata={"color": "red"},
            llm_config=llm_config,
            fallback_llm_config=fallback,
            fcm_llm_config=fcm,
            max_iter=20,
            max_rpm=40,
            max_execution_time=900,
            cache=True,
            max_retry_limit=5,
            default_temperature=1.3,
            max_tool_calls=50,
            tool_timeout=120,
            max_consecutive_failures=6,
            schema_max_retries=4,
            group=group,
        )

        response = auth_client.post(_copy_url(source.id), {}, format="json")

        assert response.status_code == 201, response.data
        new_agent = AgentDefinition.objects.get(pk=response.data["id"])
        assert {
            "description": new_agent.description,
            "instruction_list": new_agent.instruction_list,
            "metadata": new_agent.metadata,
            "llm_config_id": new_agent.llm_config_id,
            "fallback_llm_config_id": new_agent.fallback_llm_config_id,
            "fcm_llm_config_id": new_agent.fcm_llm_config_id,
            "max_iter": new_agent.max_iter,
            "max_rpm": new_agent.max_rpm,
            "max_execution_time": new_agent.max_execution_time,
            "cache": new_agent.cache,
            "max_retry_limit": new_agent.max_retry_limit,
            "default_temperature": new_agent.default_temperature,
            "max_tool_calls": new_agent.max_tool_calls,
            "tool_timeout": new_agent.tool_timeout,
            "max_consecutive_failures": new_agent.max_consecutive_failures,
            "schema_max_retries": new_agent.schema_max_retries,
            "group_id": new_agent.group_id,
        } == {
            "description": "does research",
            "instruction_list": [{"name": "Goal.md", "content": "find things"}],
            "metadata": {"color": "red"},
            "llm_config_id": llm_config.id,
            "fallback_llm_config_id": fallback.id,
            "fcm_llm_config_id": fcm.id,
            "max_iter": 20,
            "max_rpm": 40,
            "max_execution_time": 900,
            "cache": True,
            "max_retry_limit": 5,
            "default_temperature": 1.3,
            "max_tool_calls": 50,
            "tool_timeout": 120,
            "max_consecutive_failures": 6,
            "schema_max_retries": 4,
            "group_id": group.id,
        }

    def test_fallback_is_dropped_when_the_source_has_no_primary(
        self, auth_client, default_org, gpt_4o_llm
    ):
        # Deleting the primary config (SET_NULL) leaves a fallback without a primary.
        fallback = LLMConfig.objects.create(custom_name="fallback", model=gpt_4o_llm, org=default_org)
        source = AgentDefinition.objects.create(
            org=default_org, name="Orphan fallback", fallback_llm_config=fallback
        )

        response = auth_client.post(_copy_url(source.id), {}, format="json")

        assert response.status_code == 201, response.data
        assert response.data["llm_config"] is None
        assert response.data["fallback_llm_config"] is None


@pytest.mark.django_db
class TestNames:
    def test_repeated_copies_get_distinct_names(self, auth_client, default_org, source_agent):
        Surface.objects.create(org=default_org, name="Notes", owner_agent=source_agent)

        first = auth_client.post(_copy_url(source_agent.id), {}, format="json")
        second = auth_client.post(_copy_url(source_agent.id), {}, format="json")

        assert (first.status_code, second.status_code) == (201, 201)
        assert (first.data["name"], second.data["name"]) == ("Writer #2", "Writer #3")
        assert Surface.objects.get(owner_agent_id=first.data["id"]).name == "Notes #2"
        assert Surface.objects.get(owner_agent_id=second.data["id"]).name == "Notes #3"

    def test_owned_surfaces_of_one_family_get_distinct_names(
        self, auth_client, default_org, source_agent
    ):
        Surface.objects.create(org=default_org, name="Notes", owner_agent=source_agent)
        Surface.objects.create(org=default_org, name="Notes #2", owner_agent=source_agent)

        response = auth_client.post(_copy_url(source_agent.id), {}, format="json")

        assert response.status_code == 201, response.data
        assert set(
            Surface.objects.filter(owner_agent_id=response.data["id"]).values_list("name", flat=True)
        ) == {"Notes #3", "Notes #4"}

    def test_a_free_requested_name_is_used_verbatim(self, auth_client, source_agent):
        response = auth_client.post(_copy_url(source_agent.id), {"name": "Editor"}, format="json")

        assert response.status_code == 201, response.data
        assert response.data["name"] == "Editor"

    def test_a_taken_requested_name_gets_a_number(self, auth_client, source_agent):
        response = auth_client.post(_copy_url(source_agent.id), {"name": "Writer"}, format="json")

        assert response.status_code == 201, response.data
        assert response.data["name"] == "Writer #2"

    def test_a_requested_name_is_trimmed(self, auth_client, source_agent):
        response = auth_client.post(
            _copy_url(source_agent.id), {"name": "  Editor  "}, format="json"
        )

        assert response.status_code == 201, response.data
        assert response.data["name"] == "Editor"


@pytest.mark.django_db
class TestLongNames:
    """Names near the 255-char column limit still leave room for a " #N" suffix.

    A family too long for a suffix is cut to 249 chars (255 minus room for " #9999"),
    and every later copy is numbered within that cut family.
    """

    def test_a_max_length_agent_name_is_cut_to_fit_its_copy_number(
        self, auth_client, default_org
    ):
        source = AgentDefinition.objects.create(org=default_org, name="A" * 255)

        first = auth_client.post(_copy_url(source.id), {}, format="json")
        second = auth_client.post(_copy_url(source.id), {}, format="json")

        assert (first.status_code, second.status_code) == (201, 201), (first.data, second.data)
        assert first.data["name"] == "A" * 249
        assert second.data["name"] == "A" * 249 + " #2"

    def test_a_max_length_owned_surface_name_is_cut_to_fit_its_copy_number(
        self, auth_client, default_org, source_agent
    ):
        Surface.objects.create(org=default_org, name="S" * 255, owner_agent=source_agent)

        first = auth_client.post(_copy_url(source_agent.id), {}, format="json")
        second = auth_client.post(_copy_url(source_agent.id), {}, format="json")

        assert (first.status_code, second.status_code) == (201, 201), (first.data, second.data)
        assert Surface.objects.get(owner_agent_id=first.data["id"]).name == "S" * 249
        assert Surface.objects.get(owner_agent_id=second.data["id"]).name == "S" * 249 + " #2"

    def test_a_numbered_max_length_name_is_cut_within_its_family(
        self, auth_client, default_org
    ):
        source = AgentDefinition.objects.create(org=default_org, name="B" * 250 + " #12")
        AgentDefinition.objects.create(org=default_org, name="B" * 249)

        response = auth_client.post(_copy_url(source.id), {}, format="json")

        assert response.status_code == 201, response.data
        assert response.data["name"] == "B" * 249 + " #2"

    def test_a_requested_max_length_name_is_accepted(self, auth_client, source_agent):
        response = auth_client.post(_copy_url(source_agent.id), {"name": "R" * 255}, format="json")

        assert response.status_code == 201, response.data
        assert response.data["name"] == "R" * 249


@pytest.mark.django_db
class TestInvalidRequest:
    @pytest.mark.parametrize(
        "body",
        [
            {"name": "R" * 256},
            {"name": "R" * 300},
            {"name": 5},
            {"name": True},
            {"name": ["Editor"]},
            {"name": "   "},
            {"name": ""},
        ],
    )
    def test_an_invalid_name_is_refused_and_nothing_is_written(
        self, auth_client, default_org, source_agent, body
    ):
        Surface.objects.create(org=default_org, name="Owned", owner_agent=source_agent)
        agents_before = AgentDefinition.all_objects.count()
        surfaces_before = Surface.all_objects.count()

        response = auth_client.post(_copy_url(source_agent.id), body, format="json")

        assert response.status_code == 400, response.data
        assert response.data["message"].startswith("name: ")
        assert AgentDefinition.all_objects.count() == agents_before
        assert Surface.all_objects.count() == surfaces_before

    def test_a_null_name_copies_under_the_source_name(self, auth_client, source_agent):
        response = auth_client.post(_copy_url(source_agent.id), {"name": None}, format="json")

        assert response.status_code == 201, response.data
        assert response.data["name"] == "Writer #2"

    def test_another_orgs_agent_is_not_found_before_the_body_is_checked(
        self, client_as, admin_acme, acme, beta
    ):
        foreign = AgentDefinition.objects.create(org=beta, name="Foreign")
        client = client_as(admin_acme)
        client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

        response = client.post(_copy_url(foreign.id), {"name": 5}, format="json")

        assert response.status_code == 404


@pytest.mark.django_db
def test_the_caller_authors_the_agent_and_its_cloned_surfaces(
    auth_client, default_org, regular_user, source_agent
):
    Surface.objects.create(org=default_org, name="Mine", owner_agent=source_agent)

    response = auth_client.post(_copy_url(source_agent.id), {}, format="json")

    assert response.status_code == 201, response.data
    new_agent = AgentDefinition.objects.get(pk=response.data["id"])
    clone = Surface.objects.get(owner_agent=new_agent)
    assert new_agent.created_by_id == regular_user.id
    assert clone.created_by_id == regular_user.id
    assert _last_editor_id(new_agent) == regular_user.id
    assert _last_editor_id(clone) == regular_user.id
    assert response.data["created_by"]["id"] == regular_user.id


@pytest.mark.django_db
class TestRealtime:
    def test_realtime_settings_are_copied(self, auth_client, default_org, source_agent):
        openai_config = OpenAIRealtimeConfig.objects.create(custom_name="voice", org=default_org)
        source_realtime = RealtimeAgentDefinition.objects.create(
            agent_definition=source_agent,
            wake_word="hey writer",
            stop_prompt="halt",
            language="de",
            voice_recognition_prompt="expect tech words",
            voice="verse",
            openai_config=openai_config,
        )

        response = auth_client.post(_copy_url(source_agent.id), {}, format="json")

        assert response.status_code == 201, response.data
        assert response.data["has_realtime_definition"] is True
        assert response.data["agent_definition_realtime_config_id"] == openai_config.id
        copied = RealtimeAgentDefinition.objects.get(agent_definition_id=response.data["id"])
        fields = (
            "wake_word",
            "stop_prompt",
            "language",
            "voice_recognition_prompt",
            "voice",
            "openai_config_id",
            "elevenlabs_config_id",
            "gemini_config_id",
        )
        assert {field: getattr(copied, field) for field in fields} == {
            field: getattr(source_realtime, field) for field in fields
        }
        assert RealtimeAgentDefinition.objects.get(agent_definition=source_agent) == source_realtime

    def test_no_realtime_when_the_source_has_none(self, auth_client, source_agent):
        response = auth_client.post(_copy_url(source_agent.id), {}, format="json")

        assert response.status_code == 201, response.data
        assert response.data["has_realtime_definition"] is False
        assert not RealtimeAgentDefinition.all_objects.filter(
            agent_definition_id=response.data["id"]
        ).exists()


def _every_permission_except(resource_type: ResourceType, action: Permission) -> dict:
    permissions = {resource: grantable_bits_for(resource.value) for resource in ResourceType}
    permissions[resource_type] &= ~int(action)
    return permissions


@pytest.mark.django_db
class TestAccess:
    def test_another_orgs_agent_is_not_found_and_nothing_is_written(
        self, client_as, admin_acme, acme, beta
    ):
        foreign = AgentDefinition.objects.create(org=beta, name="Foreign")
        Surface.objects.create(org=beta, name="Foreign owned", owner_agent=foreign)
        client = client_as(admin_acme)
        client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
        agents_before = AgentDefinition.all_objects.count()
        surfaces_before = Surface.all_objects.count()

        response = client.post(_copy_url(foreign.id), {}, format="json")

        assert response.status_code == 404
        assert AgentDefinition.all_objects.count() == agents_before
        assert Surface.all_objects.count() == surfaces_before

    @pytest.mark.parametrize("gone", ["missing", "binned"])
    def test_a_missing_or_binned_agent_is_not_found(
        self, auth_client, default_org, source_agent, gone
    ):
        Surface.objects.create(org=default_org, name="Owned", owner_agent=source_agent)
        if gone == "missing":
            agent_id = AgentDefinition.all_objects.order_by("-pk").first().pk + 1
        else:
            agent_id = source_agent.id
            source_agent.delete()
        agents_before = AgentDefinition.all_objects.count()
        surfaces_before = Surface.all_objects.count()

        response = auth_client.post(_copy_url(agent_id), {}, format="json")

        assert response.status_code == 404
        assert AgentDefinition.all_objects.count() == agents_before
        assert Surface.all_objects.count() == surfaces_before

    def test_without_agents_create_it_is_forbidden_and_nothing_is_written(
        self, client_as, custom_role_user, acme
    ):
        source = AgentDefinition.objects.create(org=acme, name="Locked")
        Surface.objects.create(org=acme, name="Locked owned", owner_agent=source)
        user = custom_role_user(
            acme,
            "agents-no-create@example.com",
            _every_permission_except(ResourceType.AGENTS, Permission.CREATE),
        )
        client = client_as(user)
        client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
        agents_before = AgentDefinition.all_objects.count()
        surfaces_before = Surface.all_objects.count()

        response = client.post(_copy_url(source.id), {}, format="json")

        assert response.status_code == 403
        assert AgentDefinition.all_objects.count() == agents_before
        assert Surface.all_objects.count() == surfaces_before

    def test_cloning_owned_surfaces_needs_surfaces_create(
        self, client_as, custom_role_user, acme
    ):
        source = AgentDefinition.objects.create(org=acme, name="Owner")
        Surface.objects.create(org=acme, name="Owner owned", owner_agent=source)
        client = _client_without_surfaces_create(client_as, custom_role_user, acme)
        agents_before = AgentDefinition.all_objects.count()
        surfaces_before = Surface.all_objects.count()

        response = client.post(_copy_url(source.id), {}, format="json")

        assert response.status_code == 403
        assert AgentDefinition.all_objects.count() == agents_before
        assert Surface.all_objects.count() == surfaces_before

    def test_an_agent_with_only_shared_surfaces_needs_no_surfaces_create(
        self, client_as, custom_role_user, acme
    ):
        source = AgentDefinition.objects.create(org=acme, name="Sharer")
        shared = Surface.objects.create(org=acme, name="Everyone's")
        AgentDefaultSurface.objects.create(
            agent_definition=source, surface=shared, place=SurfacePlace.ALL
        )
        client = _client_without_surfaces_create(client_as, custom_role_user, acme)

        response = client.post(_copy_url(source.id), {}, format="json")

        assert response.status_code == 201, response.data
        assert _default_surfaces_of(AgentDefinition.objects.get(pk=response.data["id"])) == {
            (shared.id, SurfacePlace.ALL)
        }


def _client_without_surfaces_create(client_as, custom_role_user, org):
    user = custom_role_user(
        org,
        "no-surfaces-create@example.com",
        _every_permission_except(ResourceType.SURFACES, Permission.CREATE),
    )
    client = client_as(user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client
