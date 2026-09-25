import pytest

from rbac.access.delete_resource_names import register_resource_names, resource_name
from rbac.governance import organization_deletion
from rbac.governance.organization_deletion import (
    OrganizationDeletionCounts,
    participants,
    register_participant,
)
from rbac.governance.organizations import OrganizationManagementService
from rbac.models import Organization
from tables.services.organization_deletion import TablesOrganizationDeletion
from tables.services.storage_service.manager import StorageManager
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


@pytest.fixture(autouse=True)
def _no_storage_calls(mocker):
    """Storage is a network dependency; stub it for every test in this file."""
    backend = mocker.MagicMock()
    backend.list_all_objects.return_value = [("a.txt", 10, ""), ("b.txt", 5, "")]
    return mocker.patch(
        "tables.services.organization_deletion.get_storage_backend",
        return_value=backend,
    )


@pytest.fixture
def actor(superadmin):
    superadmin.is_superadmin = True
    superadmin.save(update_fields=["is_superadmin"])
    return superadmin


class _FailingCleanupParticipant:
    """A participant whose post-commit cleanup always raises."""

    cleanup_calls = 0

    def count_external_artifacts(self, organization):
        return {}

    def count(self, organization):
        return OrganizationDeletionCounts()

    def sweep(self, organization):
        def failing_cleanup():
            _FailingCleanupParticipant.cleanup_calls += 1
            raise RuntimeError("cleanup exploded")

        return failing_cleanup

    def resource_names(self):
        return {}

    def excluded_resource_labels(self):
        return frozenset()


class _FailingSweepParticipant(_FailingCleanupParticipant):
    """A participant whose sweep raises after earlier participants already swept."""

    def sweep(self, organization):
        raise RuntimeError("sweep exploded")


@pytest.fixture
def extra_participant(monkeypatch):
    """Run the registered participants followed by one test participant for the duration of a test."""

    def _add(participant):
        monkeypatch.setattr(
            organization_deletion, "_participants", [*participants(), participant]
        )

    return _add


def test_tables_participant_is_registered_after_app_load():
    registered = participants()

    assert [type(participant) for participant in registered].count(TablesOrganizationDeletion) == 1


def test_registering_the_same_participant_type_twice_is_refused():
    with pytest.raises(ValueError):
        register_participant(TablesOrganizationDeletion())

    assert len(participants()) == 1


def test_registering_an_already_known_label_is_refused():
    with pytest.raises(ValueError):
        register_resource_names({"tables.Graph": "graphs"}, frozenset())
    with pytest.raises(ValueError):
        register_resource_names({}, frozenset({"rbac.Role"}))

    assert resource_name("tables.Graph") == "flow"
    assert resource_name("rbac.Role") == "roles"


def test_tables_labels_resolve_through_the_registry_for_user_and_org_deletes():
    assert resource_name("tables.McpToolFavorite") == "tool_favorites"
    assert resource_name("tables.FlowAssistantMessage") == "assistant_conversations"
    assert resource_name("agents.Surface") == "surfaces"
    assert resource_name("tables.Task") == "tasks"


@pytest.mark.django_db
def test_storage_prefix_comes_from_the_storage_manager(acme, _no_storage_calls):
    TablesOrganizationDeletion().count_external_artifacts(acme)

    _no_storage_calls.assert_called_once_with(
        organization_prefix=StorageManager.organization_prefix(acme.pk)
    )
    assert StorageManager.organization_prefix(acme.pk) == f"org_{acme.pk}/"


@pytest.mark.django_db
def test_task_referencing_two_organizations_survives_deleting_one_of_them(actor, acme, beta):
    from tables.models.crew_models import Agent, Crew, Task

    acme_crew = Crew.objects.create(org=acme, name="acme-crew")
    beta_agent = Agent.objects.create(org=beta, role="r", goal="g", backstory="b")
    shared_task = Task.objects.create(
        crew=acme_crew, agent=beta_agent, name="shared", instructions="i", expected_output="e"
    )
    acme_only_task = Task.objects.create(
        crew=acme_crew, agent=None, name="acme-only", instructions="i", expected_output="e"
    )

    service = OrganizationManagementService()
    preview = service.preview_delete(actor=actor, org_id=acme.pk)
    actual = service.delete_organization(actor=actor, org_id=acme.pk)

    assert preview.affected_resources.get("tasks") == 1
    assert actual.affected_resources.get("tasks") == 1
    assert not Task.objects.filter(pk=acme_only_task.pk).exists()
    shared_task.refresh_from_db()
    assert shared_task.crew_id is None
    assert shared_task.agent_id == beta_agent.pk


@pytest.mark.django_db
def test_template_agent_referencing_two_organizations_survives_deleting_one_of_them(
    actor, acme, beta
):
    from tables.models.crew_models import TemplateAgent
    from tables.models.llm_models import LLMConfig

    acme_config = LLMConfig.objects.create(custom_name="acme-llm", org=acme)
    beta_config = LLMConfig.objects.create(custom_name="beta-llm", org=beta)
    shared_template = TemplateAgent.objects.create(
        role="r", goal="g", backstory="b", llm_config=acme_config, fcm_llm_config=beta_config
    )

    OrganizationManagementService().delete_organization(actor=actor, org_id=acme.pk)

    shared_template.refresh_from_db()
    assert shared_template.llm_config_id is None
    assert shared_template.fcm_llm_config_id == beta_config.pk


@pytest.mark.django_db
def test_realtime_agent_chat_referencing_two_organizations_survives_deleting_one_of_them(
    actor, acme, beta
):
    from tables.models.realtime_models import (
        ElevenLabsRealtimeConfig,
        OpenAIRealtimeConfig,
        RealtimeAgentChat,
    )

    acme_openai = OpenAIRealtimeConfig.objects.create(org=acme, custom_name="acme-openai")
    beta_elevenlabs = ElevenLabsRealtimeConfig.objects.create(
        org=beta, custom_name="beta-elevenlabs"
    )
    shared_chat = RealtimeAgentChat.objects.create(
        connection_key="shared", openai_config=acme_openai, elevenlabs_config=beta_elevenlabs
    )
    acme_only_chat = RealtimeAgentChat.objects.create(
        connection_key="acme-only", openai_config=acme_openai
    )

    report = OrganizationManagementService().delete_organization(actor=actor, org_id=acme.pk)

    assert report.affected_resources.get("realtime_agent_chats") == 1
    assert not RealtimeAgentChat.objects.filter(pk=acme_only_chat.pk).exists()
    shared_chat.refresh_from_db()
    assert shared_chat.openai_config_id is None
    assert shared_chat.elevenlabs_config_id == beta_elevenlabs.pk


@pytest.mark.django_db
def test_preview_counts_equal_real_delete_counts_with_the_participant_in_place(actor, acme, beta):
    from tables.models.crew_models import Agent, Crew, Task, TemplateAgent
    from tables.models.knowledge_models.collection_models import (
        DocumentContent,
        DocumentMetadata,
        SourceCollection,
    )
    from tables.models.llm_models import LLMConfig
    from tables.models.realtime_models import OpenAIRealtimeConfig, RealtimeAgentChat

    crew = Crew.objects.create(org=acme, name="c")
    agent = Agent.objects.create(org=acme, role="r", goal="g", backstory="b")
    beta_agent = Agent.objects.create(org=beta, role="r", goal="g", backstory="b")
    Task.objects.create(crew=crew, agent=agent, name="t", instructions="i", expected_output="e")
    Task.objects.create(
        crew=crew, agent=beta_agent, name="shared", instructions="i", expected_output="e"
    )
    llm_config = LLMConfig.objects.create(custom_name="acme-llm", org=acme)
    TemplateAgent.objects.create(role="r", goal="g", backstory="b", llm_config=llm_config)
    openai_config = OpenAIRealtimeConfig.objects.create(org=acme, custom_name="acme-openai")
    RealtimeAgentChat.objects.create(connection_key="k", openai_config=openai_config)
    collection = SourceCollection.objects.create(org=acme, collection_name="acme-docs")
    content = DocumentContent.objects.create(content=b"hello")
    DocumentMetadata.objects.create(
        source_collection=collection, document_content=content, file_name="hello.txt"
    )

    service = OrganizationManagementService()
    preview = service.preview_delete(actor=actor, org_id=acme.pk)
    actual = service.delete_organization(actor=actor, org_id=acme.pk)

    assert preview.affected_resources == actual.affected_resources
    assert actual.affected_resources["tasks"] == 1
    assert actual.affected_resources["template_agents"] == 1
    assert actual.affected_resources["realtime_agent_chats"] == 1
    assert actual.affected_resources["knowledge_collections"] == 1
    assert actual.affected_resources["knowledge_documents"] == 2
    assert actual.affected_resources["storage_files"] == 2


@pytest.mark.django_db
def test_a_failing_participant_cleanup_is_contained_after_commit(
    actor, acme, beta, extra_participant, _no_storage_calls, django_capture_on_commit_callbacks
):
    extra_participant(_FailingCleanupParticipant())
    _FailingCleanupParticipant.cleanup_calls = 0

    with django_capture_on_commit_callbacks(execute=True):
        OrganizationManagementService().delete_organization(actor=actor, org_id=acme.pk)

    assert not Organization.objects.filter(pk=acme.pk).exists()
    assert _FailingCleanupParticipant.cleanup_calls == 1
    _no_storage_calls.return_value.delete_prefix.assert_called_once_with("")


@pytest.mark.django_db
def test_a_failing_participant_sweep_rolls_back_the_whole_delete(
    actor, acme, beta, extra_participant
):
    from tables.models.crew_models import Crew, Task

    crew = Crew.objects.create(org=acme, name="c")
    task = Task.objects.create(crew=crew, name="t", instructions="i", expected_output="e")
    extra_participant(_FailingSweepParticipant())

    with pytest.raises(RuntimeError, match="sweep exploded"):
        OrganizationManagementService().delete_organization(actor=actor, org_id=acme.pk)

    assert Organization.objects.filter(pk=acme.pk).exists()
    assert Task.objects.filter(pk=task.pk).exists()
