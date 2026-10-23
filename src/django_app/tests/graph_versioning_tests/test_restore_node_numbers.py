"""Version restore keeps the stored node numbers; create-from-version renumbers 1..K."""

from datetime import datetime, timezone

import pytest
from django.apps import apps
from django.urls import reverse
from rest_framework import status

from tables.graph_versioning.services import GraphVersioningService
from tables.models import AgentNode, Crew, CrewNode, Graph, PythonCode, PythonNode, StartNode
from tables.models.base_models import NumberedNode
from tables.models.graph_models import (
    AudioTranscriptionNode,
    ClassificationDecisionTableNode,
    DecisionTableNode,
    FileExtractorNode,
    KeyValueNode,
    KnowledgeNode,
    ScheduleTriggerNode,
    SubGraphNode,
    TaskNode,
    TelegramTriggerNode,
    WebhookTriggerNode,
)
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


@pytest.fixture(autouse=True)
def _telegram_registration_mocked(mock_telegram_service):
    return mock_telegram_service


def _python_code():
    return PythonCode.objects.create(code="def main(): ...", entrypoint="main")


def _python_node(graph, node_name, node_number):
    return PythonNode.objects.create(
        graph=graph, node_name=node_name, python_code=_python_code(), node_number=node_number
    )


def _numbers_by_name(graph):
    return {
        **dict(graph.agent_node_list.values_list("node_name", "node_number")),
        **dict(graph.python_node_list.values_list("node_name", "node_number")),
    }


def _set_stored_numbers(version, numbers_by_name):
    for node in version.snapshot["nodes"]:
        if node.get("node_name") in numbers_by_name:
            node["node_number"] = numbers_by_name[node["node_name"]]
    version.save(update_fields=["snapshot"])


@pytest.fixture
def numbered_flow(acme):
    """A flow whose nodes hold #1, #4 and #5, spread over two node tables."""
    graph = Graph.objects.create(name="Numbered Flow", org=acme)
    StartNode.objects.create(graph=graph, variables={})
    _python_node(graph, "first", 1)
    AgentNode.objects.create(graph=graph, node_name="fourth", node_number=4)
    _python_node(graph, "fifth", 5)
    graph.refresh_from_db()
    return graph


@pytest.fixture
def version(numbered_flow):
    return GraphVersioningService().save_version(numbered_flow, name="three nodes")


def _restore(graph, version):
    graph.refresh_from_db()
    GraphVersioningService().restore_version(
        version, expected_save_version=graph.save_version
    )
    graph.refresh_from_db()


@pytest.fixture
def grown_flow(numbered_flow, version):
    """`numbered_flow` after its version was saved: it grew to #7, then lost #4."""
    AgentNode.objects.create(graph=numbered_flow, node_name="sixth")
    AgentNode.objects.create(graph=numbered_flow, node_name="seventh")
    AgentNode.objects.filter(graph=numbered_flow, node_name="fourth").delete()
    numbered_flow.refresh_from_db()
    assert numbered_flow.node_number_seq == 7
    return numbered_flow


@pytest.mark.django_db
def test_restore_keeps_the_numbers_stored_in_the_version(grown_flow, version):
    _restore(grown_flow, version)

    assert _numbers_by_name(grown_flow) == {"first": 1, "fourth": 4, "fifth": 5}


@pytest.mark.django_db
def test_restore_never_lowers_the_counter(grown_flow, version):
    _restore(grown_flow, version)

    assert grown_flow.node_number_seq == 7
    added = AgentNode.objects.create(graph=grown_flow, node_name="after restore")
    assert added.node_number == 8


@pytest.mark.django_db
def test_restore_raises_the_counter_to_a_stored_number_above_it(numbered_flow, version):
    _set_stored_numbers(version, {"fifth": 12})

    _restore(numbered_flow, version)

    assert _numbers_by_name(numbered_flow) == {"first": 1, "fourth": 4, "fifth": 12}
    assert numbered_flow.node_number_seq == 12


@pytest.mark.django_db
def test_restore_ignores_the_counter_stored_in_the_snapshot(numbered_flow, version):
    version.snapshot["node_number_seq"] = 99
    version.save(update_fields=["snapshot"])

    _restore(numbered_flow, version)

    assert numbered_flow.node_number_seq == 5


@pytest.mark.django_db
def test_restore_keeps_a_duplicated_number_on_the_first_node_and_mints_the_second(
    numbered_flow, version
):
    # "first" (#1) comes before "fourth" in source order, so it keeps #1.
    _set_stored_numbers(version, {"fourth": 1})

    _restore(numbered_flow, version)

    assert _numbers_by_name(numbered_flow) == {"first": 1, "fifth": 5, "fourth": 6}
    assert numbered_flow.node_number_seq == 6


@pytest.mark.parametrize(
    "unusable_number",
    [None, "4", 4.0, True, 0, -1, 1_000_001],
    ids=["null", "string", "float", "bool", "zero", "negative", "above-cap"],
)
@pytest.mark.django_db
def test_restore_mints_a_fresh_number_for_an_unusable_stored_one(
    numbered_flow, version, unusable_number
):
    _set_stored_numbers(version, {"fourth": unusable_number})

    _restore(numbered_flow, version)

    assert _numbers_by_name(numbered_flow) == {"first": 1, "fifth": 5, "fourth": 6}


@pytest.mark.django_db
def test_restore_keeps_a_stored_number_at_the_cap(numbered_flow, version):
    _set_stored_numbers(version, {"fourth": 1_000_000})

    _restore(numbered_flow, version)

    assert _numbers_by_name(numbered_flow) == {"first": 1, "fifth": 5, "fourth": 1_000_000}


@pytest.mark.django_db
def test_restore_mints_numbers_above_every_kept_one_whatever_the_source_order(
    numbered_flow, version
):
    # "fourth" duplicates #1 and sorts before "fifth", yet it is minted only after
    # "fifth" raised the counter to 9.
    _set_stored_numbers(version, {"fourth": 1, "fifth": 9})

    _restore(numbered_flow, version)

    assert _numbers_by_name(numbered_flow) == {"first": 1, "fifth": 9, "fourth": 10}


@pytest.mark.django_db
def test_restore_mints_a_number_held_by_a_legacy_crew_node_the_wipe_keeps(
    client_as, admin_acme, acme
):
    graph = Graph.objects.create(name="Crew Flow", org=acme)
    _python_node(graph, "python", 1)
    crew_node = CrewNode.objects.create(
        graph=graph,
        node_name="legacy crew",
        crew=Crew.objects.create(org=acme, name="legacy"),
        node_number=4,
    )
    version = GraphVersioningService().save_version(graph, name="with crew node")
    _set_stored_numbers(version, {"python": 4})
    graph.refresh_from_db()
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

    response = client.post(
        reverse("graph-versions-restore", args=[version.id]),
        {"save_version": graph.save_version},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert dict(graph.python_node_list.values_list("node_name", "node_number")) == {"python": 5}
    assert CrewNode.objects.get(pk=crew_node.pk).node_number == 4


@pytest.mark.django_db
def test_restore_mints_a_number_held_by_a_binned_node_the_wipe_keeps(numbered_flow, version):
    binned = AgentNode.objects.get(graph=numbered_flow, node_name="fourth")
    AgentNode.all_objects.filter(pk=binned.pk).update(
        active=False, soft_deleted_at=datetime.now(timezone.utc)
    )

    _restore(numbered_flow, version)

    assert _numbers_by_name(numbered_flow) == {"first": 1, "fifth": 5, "fourth": 6}
    assert numbered_flow.node_number_seq == 6
    assert AgentNode.all_objects.get(pk=binned.pk).node_number == 4


def _create_every_numbered_node_type(graph):
    """One node of every numbered type that a version can hold, numbered #10, #20, ..."""
    nodes = [
        KeyValueNode(graph=graph, node_name="key value"),
        WebhookTriggerNode(graph=graph, node_name="webhook", python_code=_python_code()),
        ScheduleTriggerNode(graph=graph, node_name="schedule"),
        TelegramTriggerNode(graph=graph, node_name="telegram"),
        AgentNode(graph=graph, node_name="agent"),
        TaskNode(graph=graph, node_name="task"),
        PythonNode(graph=graph, node_name="python", python_code=_python_code()),
        KnowledgeNode(graph=graph, node_name="knowledge"),
        FileExtractorNode(graph=graph, node_name="extractor"),
        AudioTranscriptionNode(graph=graph, node_name="transcription"),
        SubGraphNode(graph=graph, node_name="subgraph"),
        DecisionTableNode(graph=graph, node_name="decision"),
        ClassificationDecisionTableNode(graph=graph, node_name="classification"),
    ]
    for position, node in enumerate(nodes, start=1):
        node.node_number = position * 10
        node.save()
    return nodes


def _numbers_by_type(graph):
    return {
        model.__name__: number
        for model in apps.get_models()
        if issubclass(model, NumberedNode)
        for number in model.objects.filter(graph=graph).values_list("node_number", flat=True)
    }


@pytest.mark.django_db
def test_restore_keeps_the_stored_number_of_every_numbered_node_type(acme):
    graph = Graph.objects.create(name="Every Node Flow", org=acme)
    nodes = _create_every_numbered_node_type(graph)
    # Legacy CrewNodes are never recreated by a restore: the wipe keeps them.
    numbered_models = {model for model in apps.get_models() if issubclass(model, NumberedNode)}
    assert {type(node) for node in nodes} == numbered_models - {CrewNode}
    stored_numbers = _numbers_by_type(graph)
    version = GraphVersioningService().save_version(graph, name="every node type")

    _restore(graph, version)

    assert _numbers_by_type(graph) == stored_numbers
    assert graph.node_number_seq == 130


@pytest.mark.django_db
def test_create_from_version_numbers_the_new_flow_one_to_k(numbered_flow, version):
    result = GraphVersioningService().create_graph_from_version(version)

    new_graph = Graph.objects.get(pk=result["graph_id"])
    assert _numbers_by_name(new_graph) == {"first": 1, "fourth": 2, "fifth": 3}
    assert new_graph.node_number_seq == 3
    numbered_flow.refresh_from_db()
    assert _numbers_by_name(numbered_flow) == {"first": 1, "fourth": 4, "fifth": 5}
    assert numbered_flow.node_number_seq == 5


@pytest.mark.django_db
def test_create_from_version_ignores_the_counter_stored_in_the_snapshot(version):
    version.snapshot["node_number_seq"] = 99
    version.save(update_fields=["snapshot"])

    result = GraphVersioningService().create_graph_from_version(version)

    assert Graph.objects.get(pk=result["graph_id"]).node_number_seq == 3
