"""Node uuids through version snapshots: kept on restore, new for a flow created from a version."""

import uuid

import pytest
from django.urls import reverse
from django.utils import timezone
from loguru import logger as loguru_logger

from tables.import_export.id_mapper import IDMapper
from tables.import_export.strategies.graph import GraphStrategy
from tables.models import Graph
from tables.models.graph_models import (
    ClassificationConditionGroup,
    ClassificationConditionGroupSection,
    ClassificationDecisionTableNode,
    Condition,
    ConditionGroup,
    DecisionTableNode,
    GraphNote,
    PythonNode,
    TelegramTriggerNode,
    TelegramTriggerNodeField,
)
from tests.fixtures import *  # noqa: F401,F403
from tests.graph_node_builders import (
    NODE_MODELS,
    create_every_node,
    create_node,
    node_uuids_by_model,
)
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

by_model_name = {"ids": lambda model: model.__name__}


@pytest.fixture
def uuid_warnings():
    """Collect the loguru warnings about node uuids that were not kept."""
    messages = []
    sink_id = loguru_logger.add(
        lambda message: messages.append(message.record["message"]),
        level="WARNING",
        filter=lambda record: "it gets a new uuid" in record["message"],
    )
    yield messages
    loguru_logger.remove(sink_id)


def _restore(service, graph, version):
    graph.refresh_from_db()
    return service.restore_version(version, expected_save_version=graph.save_version)


def _set_snapshot_node_uuids(version, uuid_by_node_id: dict) -> None:
    """Overwrite (or, for the value `None`, remove) node uuids in a stored snapshot."""
    snapshot = version.snapshot
    for node_data in snapshot["nodes"]:
        if node_data["id"] not in uuid_by_node_id:
            continue
        value = uuid_by_node_id[node_data["id"]]
        if value is None:
            node_data.pop("uuid")
        else:
            node_data["uuid"] = value
    version.snapshot = snapshot
    version.save(update_fields=["snapshot"])


@pytest.mark.django_db
@pytest.mark.parametrize("model", NODE_MODELS, **by_model_name)
def test_snapshot_contains_node_uuid(service, graph, model):
    node = create_node(model, graph)

    version = service.save_version(graph, name="v")

    [node_data] = version.snapshot["nodes"]
    assert node_data["uuid"] == str(node.uuid)


@pytest.mark.django_db
@pytest.mark.parametrize("model", NODE_MODELS, **by_model_name)
def test_restore_keeps_node_uuid(service, graph, model):
    node = create_node(model, graph)
    version = service.save_version(graph, name="v")

    _restore(service, graph, version)

    restored = model.objects.get(graph=graph)
    assert restored.id != node.id
    assert restored.uuid == node.uuid


@pytest.mark.django_db
def test_restore_keeps_uuids_of_every_node_type_together(service, graph):
    create_every_node(graph)
    uuids_before = node_uuids_by_model(graph)
    version = service.save_version(graph, name="v")

    _restore(service, graph, version)

    assert node_uuids_by_model(graph) == uuids_before


@pytest.mark.django_db
def test_restore_twice_keeps_node_uuids(service, graph):
    create_every_node(graph)
    uuids_before = node_uuids_by_model(graph)
    version = service.save_version(graph, name="v")

    _restore(service, graph, version)
    _restore(service, graph, version)

    assert node_uuids_by_model(graph) == uuids_before


@pytest.mark.django_db
def test_restore_keeps_uuids_of_nodes_with_nested_rows(service, graph):
    decision_table = DecisionTableNode.objects.create(graph=graph, node_name="dt")
    group = ConditionGroup.objects.create(
        decision_table_node=decision_table, group_name="g", group_type="simple", order=0
    )
    Condition.objects.create(condition_group=group, condition_name="c", order=0, condition="True")
    classification_table = ClassificationDecisionTableNode.objects.create(
        graph=graph, node_name="cdt"
    )
    section = ClassificationConditionGroupSection.objects.create(
        id=uuid.uuid4(), classification_decision_table_node=classification_table, name="s"
    )
    ClassificationConditionGroup.objects.create(
        classification_decision_table_node=classification_table,
        group_name="cg",
        order=0,
        section=section,
    )
    telegram = TelegramTriggerNode.objects.create(graph=graph, node_name="tg")
    TelegramTriggerNodeField.objects.create(
        telegram_trigger_node=telegram, parent="message", field_name="text", variable_path="text"
    )
    version = service.save_version(graph, name="v")

    _restore(service, graph, version)

    restored_table = DecisionTableNode.objects.get(graph=graph)
    assert restored_table.uuid == decision_table.uuid
    assert restored_table.condition_groups.get().conditions.count() == 1
    restored_classification = ClassificationDecisionTableNode.objects.get(graph=graph)
    assert restored_classification.uuid == classification_table.uuid
    assert restored_classification.condition_groups.get().section.name == "s"
    restored_telegram = TelegramTriggerNode.objects.get(graph=graph)
    assert restored_telegram.uuid == telegram.uuid
    assert restored_telegram.fields.count() == 1


@pytest.mark.django_db
def test_restore_regenerates_a_duplicate_uuid_and_the_first_node_keeps_it(
    service, graph, uuid_warnings
):
    first_python = create_node(PythonNode, graph)
    second_python = create_node(PythonNode, graph)
    note = create_node(GraphNote, graph)
    version = service.save_version(graph, name="v")
    snapshot_order = [node_data["id"] for node_data in version.snapshot["nodes"]]
    # Python nodes come before notes in the snapshot, so the first python node wins.
    assert snapshot_order.index(first_python.id) < snapshot_order.index(note.id)
    duplicate = str(first_python.uuid)
    _set_snapshot_node_uuids(version, {second_python.id: duplicate, note.id: duplicate})

    result = _restore(service, graph, version)

    assert result["restored"] is True
    python_uuids = set(PythonNode.objects.filter(graph=graph).values_list("uuid", flat=True))
    assert first_python.uuid in python_uuids
    assert len(python_uuids) == 2
    assert GraphNote.objects.get(graph=graph).uuid != first_python.uuid
    assert len(uuid_warnings) == 2
    assert all("already used" in message for message in uuid_warnings)


@pytest.mark.django_db
@pytest.mark.parametrize("bad_uuid", ["not-a-uuid", "", 123, {"uuid": "x"}])
def test_restore_regenerates_a_malformed_uuid(service, graph, uuid_warnings, bad_uuid):
    node = create_node(PythonNode, graph)
    version = service.save_version(graph, name="v")
    _set_snapshot_node_uuids(version, {node.id: bad_uuid})

    result = _restore(service, graph, version)

    assert result["restored"] is True
    restored = PythonNode.objects.get(graph=graph)
    assert isinstance(restored.uuid, uuid.UUID)
    assert restored.uuid != node.uuid
    assert len(uuid_warnings) == 1
    assert "not a valid uuid" in uuid_warnings[0]


@pytest.mark.django_db
def test_restore_of_a_snapshot_without_uuids_gives_new_uuids_without_warning(
    service, graph, uuid_warnings
):
    nodes = create_every_node(graph)
    version = service.save_version(graph, name="v")
    _set_snapshot_node_uuids(version, {node.id: None for node in nodes.values()})

    _restore(service, graph, version)

    for model, node in nodes.items():
        assert model.objects.get(graph=graph).uuid != node.uuid
    assert uuid_warnings == []


@pytest.mark.django_db
def test_restore_of_a_mixed_snapshot_keeps_the_uuids_it_has(service, graph):
    with_uuid = create_node(PythonNode, graph)
    without_uuid = create_node(GraphNote, graph)
    version = service.save_version(graph, name="v")
    _set_snapshot_node_uuids(version, {without_uuid.id: None})

    _restore(service, graph, version)

    assert PythonNode.objects.get(graph=graph).uuid == with_uuid.uuid
    assert GraphNote.objects.get(graph=graph).uuid != without_uuid.uuid


@pytest.mark.django_db
def test_restore_keeps_a_uuid_held_by_a_soft_deleted_node_of_the_graph(service, graph):
    node = create_node(PythonNode, graph)
    version = service.save_version(graph, name="v")
    PythonNode.all_objects.filter(pk=node.pk).update(
        is_soft_deleted=True, soft_deleted_at=timezone.now()
    )

    _restore(service, graph, version)

    # The wipe removes active rows only, so the soft-deleted row is still there.
    soft_deleted = PythonNode.all_objects.get(pk=node.pk)
    assert soft_deleted.is_soft_deleted
    assert PythonNode.objects.get(graph=graph).uuid == soft_deleted.uuid


@pytest.mark.django_db
def test_keeping_uuids_without_a_wipe_regenerates_one_an_active_node_holds(
    graph, uuid_warnings
):
    strategy = GraphStrategy()
    existing = create_node(PythonNode, graph)
    nodes_data = strategy._export_nodes(graph)

    strategy.recreate_graph_children(
        graph, {"nodes": nodes_data}, IDMapper(), keep_node_uuids=True
    )

    uuids = list(PythonNode.objects.filter(graph=graph).values_list("uuid", flat=True))
    assert len(uuids) == 2
    assert len(set(uuids)) == 2
    assert existing.uuid in uuids
    assert len(uuid_warnings) == 1


@pytest.mark.django_db
def test_create_graph_from_version_gives_every_node_a_new_uuid(service, graph):
    nodes = create_every_node(graph)
    version = service.save_version(graph, name="v")

    result = service.create_graph_from_version(version)

    source_uuids = {node.uuid for node in nodes.values()}
    new_graph = Graph.objects.get(pk=result["graph_id"])
    new_graph_uuids = {
        node_uuid
        for model_uuids in node_uuids_by_model(new_graph).values()
        for node_uuid in model_uuids
    }
    assert len(new_graph_uuids) == len(NODE_MODELS)
    assert new_graph_uuids.isdisjoint(source_uuids)
    assert node_uuids_by_model(graph) == {model: [node.uuid] for model, node in nodes.items()}


@pytest.mark.django_db
def test_restore_of_another_orgs_version_returns_404_and_keeps_its_nodes(
    service, client_as, admin_acme, acme, beta
):
    acme_graph = Graph.objects.create(name="acme flow", org=acme)
    create_node(PythonNode, acme_graph)
    acme_version = service.save_version(acme_graph, name="acme")
    beta_graph = Graph.objects.create(name="beta flow", org=beta)
    beta_node = create_node(PythonNode, beta_graph)
    beta_version = service.save_version(beta_graph, name="beta")
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

    def restore(version):
        version.graph.refresh_from_db()
        return client.post(
            reverse("graph-versions-restore", args=[version.id]),
            {"save_version": version.graph.save_version},
            format="json",
        )

    own_response = restore(acme_version)
    foreign_response = restore(beta_version)

    # Positive control: the 404 below is the org filter, not a broken request.
    assert own_response.status_code == 200, own_response.content
    assert foreign_response.status_code == 404
    assert list(PythonNode.objects.filter(graph=beta_graph).values_list("id", "uuid")) == [
        (beta_node.id, beta_node.uuid)
    ]
