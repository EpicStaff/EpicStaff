import pytest
from django.apps import apps
from django.contrib.auth import get_user_model

from rbac.governance.delete_collector import build_collector, summarize
from rbac.governance.delete_resource_names import (
    known_excluded_resource_labels,
    known_resource_names,
    resource_name,
)
from rbac.models import Organization


def _cascade_closure(root_model):
    """Return every model reachable from root_model by following only CASCADE-delete relations."""
    seen = {root_model}
    frontier = [root_model]
    while frontier:
        current = frontier.pop()
        for rel in current._meta.related_objects:
            on_delete = getattr(rel.field.remote_field, "on_delete", None)
            if getattr(on_delete, "__name__", "") != "CASCADE":
                continue
            if rel.related_model not in seen:
                seen.add(rel.related_model)
                frontier.append(rel.related_model)
    return seen


def test_resource_name_returns_the_mapped_friendly_name():
    assert resource_name("tables.Graph") == "flow"
    assert resource_name("rbac.Role") == "roles"
    assert resource_name("rbac.OrganizationUser") == "memberships"
    assert resource_name("rbac.ApiKey") == "api_keys"


def _stale_labels(labels):
    """Return every label in `labels` that names no installed model."""
    stale = []
    for label in labels:
        try:
            apps.get_model(label)
        except LookupError:
            stale.append(label)
    return sorted(stale)


def test_every_resource_names_key_is_an_installed_model_label():
    stale = _stale_labels(known_resource_names())
    assert stale == [], f"resource name keys naming no installed model: {stale}"


def test_every_known_excluded_label_is_an_installed_model_label():
    stale = _stale_labels(known_excluded_resource_labels())
    assert stale == [], f"excluded labels naming no installed model: {stale}"


def test_resource_name_returns_none_for_a_known_excluded_label():
    assert resource_name("tables.StartNode") is None


def test_resource_name_logs_and_returns_none_for_a_truly_unmapped_label(mocker):
    warning = mocker.patch("rbac.governance.delete_resource_names.logger.warning")

    result = resource_name("tables.NotARealModel")

    assert result is None
    warning.assert_called_once()


@pytest.fixture
def rich_org(default_org):
    """Populate `default_org` with at least one row of most model families the delete cascade touches."""
    from tables.models.crew_models import Agent, Crew, Task, TemplateAgent
    from tables.models.graph_models import EndNode, Graph, StartNode
    from tables.models.knowledge_models.collection_models import (
        DocumentContent,
        DocumentMetadata,
        SourceCollection,
    )
    from tables.models.llm_models import LLMConfig
    from rbac.models import Role
    from tables.models.realtime_models import OpenAIRealtimeConfig, RealtimeAgentChat
    from tables.models.session_models import Session
    from tables.models.webhook_models import WebhookTrigger

    graph = Graph.objects.create(name="rich-org-graph", org=default_org)
    StartNode.objects.create(graph=graph, variables={})
    EndNode.objects.create(graph=graph)
    Session.objects.create(graph=graph, status=Session.SessionStatus.END)

    crew = Crew.objects.create(org=default_org, name="rich-org-crew")
    agent = Agent.objects.create(org=default_org, role="r", goal="g", backstory="b")
    Role.objects.create(name="Rich Org Custom Role", is_built_in=False, org=default_org)
    WebhookTrigger.objects.create(org=default_org, path="rich-org-webhook")
    llm_config = LLMConfig.objects.create(custom_name="rich-org-llm", org=default_org)

    collection = SourceCollection.objects.create(
        org=default_org, collection_name="rich-org-docs"
    )
    content = DocumentContent.objects.create(content=b"hello world")
    DocumentMetadata.objects.create(
        source_collection=collection, document_content=content, file_name="hello.txt"
    )

    # Deprecated, SET_NULL-only reachable rows -- included for a realistic
    # cascade, but the Collector only reports rows reached via CASCADE, so
    # these are counted separately by TablesOrganizationDeletion's sweep,
    # not by build_collector/summarize.
    Task.objects.create(
        crew=crew, agent=agent, name="t", instructions="i", expected_output="e"
    )
    TemplateAgent.objects.create(role="r", goal="g", backstory="b", llm_config=llm_config)
    openai_config = OpenAIRealtimeConfig.objects.create(
        org=default_org, custom_name="rich-org-openai"
    )
    RealtimeAgentChat.objects.create(connection_key="k", openai_config=openai_config)

    return default_org


@pytest.mark.django_db
def test_every_model_a_richly_populated_org_delete_touches_is_mapped_or_excluded(rich_org):
    """Every model label a real org-delete cascade reports must be a known resource name or a known excluded label."""
    by_model = summarize(build_collector(rich_org))

    unmapped = [
        row.model for row in by_model
        if row.model not in known_resource_names() and row.model not in known_excluded_resource_labels()
    ]
    assert unmapped == [], f"unmapped model labels in a real org-delete cascade: {unmapped}"


def test_every_cascade_reachable_org_model_is_mapped_or_excluded():
    """Every model CASCADE-reachable from Organization must be a known resource name or a known excluded label."""
    unmapped = [
        label for label in (model._meta.label for model in _cascade_closure(Organization))
        if label not in known_resource_names() and label not in known_excluded_resource_labels()
    ]
    assert unmapped == [], f"CASCADE-reachable from Organization but unmapped: {sorted(unmapped)}"


def test_every_cascade_reachable_user_model_is_mapped_or_excluded():
    """Every model CASCADE-reachable from User must be a known resource name or a known excluded label."""
    User = get_user_model()
    unmapped = [
        label for label in (model._meta.label for model in _cascade_closure(User))
        if label not in known_resource_names() and label not in known_excluded_resource_labels()
    ]
    assert unmapped == [], f"CASCADE-reachable from User but unmapped: {sorted(unmapped)}"
