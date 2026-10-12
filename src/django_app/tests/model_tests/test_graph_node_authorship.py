import pytest
from django.apps import apps

from rbac.exceptions import AuthorChangeForbiddenError
from rbac.governance.authorship import AuthorshipReleaseService
from rbac.models import AuthorModel
from tables.models import Graph
from tables.models.base_models import GraphAuthorModel
from tables.models.graph_models import (
    AgentNode,
    AudioTranscriptionNode,
    ClassificationDecisionTableNode,
    CrewNode,
    DecisionTableNode,
    Edge,
    EndNode,
    FileExtractorNode,
    GraphNote,
    KeyValueNode,
    KnowledgeNode,
    PythonNode,
    ScheduleTriggerNode,
    StartNode,
    SubGraphNode,
    TaskNode,
    TelegramTriggerNode,
    WebhookTriggerNode,
)
from tables.models.python_models import PythonCode

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


def _python_code():
    return PythonCode.objects.create(code="def main(): return 1", entrypoint="main")


NODE_FACTORIES = {
    GraphNote: lambda graph: GraphNote.objects.create(graph=graph, content="note"),
    KeyValueNode: lambda graph: KeyValueNode.objects.create(graph=graph),
    StartNode: lambda graph: StartNode.objects.create(graph=graph, variables={}),
    EndNode: lambda graph: EndNode.objects.create(graph=graph, output_map={}),
    WebhookTriggerNode: lambda graph: WebhookTriggerNode.objects.create(
        graph=graph, node_name="webhook", python_code=_python_code()
    ),
    ScheduleTriggerNode: lambda graph: ScheduleTriggerNode.objects.create(
        graph=graph, node_name="schedule"
    ),
    TelegramTriggerNode: lambda graph: TelegramTriggerNode.objects.create(
        graph=graph, node_name="telegram"
    ),
    AgentNode: lambda graph: AgentNode.objects.create(graph=graph),
    TaskNode: lambda graph: TaskNode.objects.create(graph=graph),
    PythonNode: lambda graph: PythonNode.objects.create(
        graph=graph, python_code=_python_code()
    ),
    KnowledgeNode: lambda graph: KnowledgeNode.objects.create(graph=graph),
    FileExtractorNode: lambda graph: FileExtractorNode.objects.create(graph=graph),
    AudioTranscriptionNode: lambda graph: AudioTranscriptionNode.objects.create(
        graph=graph
    ),
    SubGraphNode: lambda graph: SubGraphNode.objects.create(graph=graph),
    DecisionTableNode: lambda graph: DecisionTableNode.objects.create(
        graph=graph, node_name="decision"
    ),
    ClassificationDecisionTableNode: lambda graph: ClassificationDecisionTableNode.objects.create(
        graph=graph, node_name="classification"
    ),
}


@pytest.fixture
def author(db, django_user_model):
    return django_user_model.objects.create_user(
        email="node-author@example.com", password="StrongPass123!"
    )


@pytest.fixture
def other_user(db, django_user_model):
    return django_user_model.objects.create_user(
        email="node-other@example.com", password="StrongPass123!"
    )


@pytest.fixture
def acme_graph(acme):
    return Graph.objects.create(name="acme-authored-flow", org=acme)


@pytest.fixture
def beta_graph(beta):
    return Graph.objects.create(name="beta-authored-flow", org=beta)


# ---- which models are authored ----


def test_exactly_the_graph_node_models_are_graph_authored():
    graph_authored = {
        model for model in apps.get_models() if issubclass(model, GraphAuthorModel)
    }

    assert graph_authored == set(NODE_FACTORIES)


def test_graph_authored_models_reach_org_through_graph():
    assert GraphAuthorModel.author_org_lookup == "graph__org_id"
    for model in NODE_FACTORIES:
        assert model.author_org_lookup == "graph__org_id", model.__name__


@pytest.mark.parametrize("model", [Edge, CrewNode])
def test_edges_and_crew_node_are_not_authored(model):
    assert not issubclass(model, AuthorModel)


# ---- immutability guard and content hash ----


@pytest.mark.django_db
@pytest.mark.parametrize("model", list(NODE_FACTORIES), ids=lambda model: model.__name__)
def test_node_author_cannot_be_replaced(model, acme_graph, author, other_user, mock_telegram_service):
    node = NODE_FACTORIES[model](acme_graph)
    model._base_manager.filter(pk=node.pk).update(created_by=author)
    node = model._base_manager.get(pk=node.pk)

    node.created_by = other_user
    with pytest.raises(AuthorChangeForbiddenError):
        node.save()


@pytest.mark.django_db
@pytest.mark.parametrize("model", list(NODE_FACTORIES), ids=lambda model: model.__name__)
def test_node_content_hash_ignores_author(model, acme_graph, author, mock_telegram_service):
    node = NODE_FACTORIES[model](acme_graph)
    unauthored_hash = node.generate_hash()

    node.created_by = author

    assert node.generate_hash() == unauthored_hash


# ---- release ----


@pytest.mark.django_db
def test_release_clears_node_authors_in_that_org_only(
    acme, acme_graph, beta_graph, author, mock_telegram_service
):
    acme_nodes = [factory(acme_graph) for factory in NODE_FACTORIES.values()]
    beta_note = GraphNote.objects.create(graph=beta_graph, content="beta", created_by=author)
    for node in acme_nodes:
        type(node)._base_manager.filter(pk=node.pk).update(created_by=author)

    AuthorshipReleaseService().release(author.id, acme.id)

    for node in acme_nodes:
        assert type(node)._base_manager.get(pk=node.pk).created_by_id is None, type(node)
    assert GraphNote.objects.get(pk=beta_note.pk).created_by_id == author.id
