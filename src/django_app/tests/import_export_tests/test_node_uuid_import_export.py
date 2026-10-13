"""Node uuids through export and import: kept when a file replaces its flow, new otherwise."""

from copy import deepcopy

import pytest
from django.utils import timezone

from tables.import_export.enums import EntityType
from tables.import_export.registry import entity_registry
from tables.import_export.schemas import ImportSettings
from tables.import_export.services.partial_export_service import (
    LIST_KEY_TO_ENTITY_TYPE,
    GraphPartialExportService,
    NodeRef,
)
from tables.import_export.services.partial_import_service import PartialImportService
from tables.import_export.strategies.nodes.node_maps import NODE_RELATIONS
from tables.models import Graph
from tables.models.graph_models import PythonNode
from tests.graph_node_builders import (
    MULTIPLE_PER_GRAPH_NODE_MODELS,
    NODE_MODELS,
    create_every_node,
    create_node,
    node_uuids_by_model,
)
from tests.rbac_cross_org_fixtures import acme, beta  # noqa: F401

by_model_name = {"ids": lambda model: model.__name__}

REPLACE_IN_PLACE = ImportSettings(preserve_uuids=True, replace_existing=True)


def _flow(org, name="flow"):
    return Graph.objects.create(name=name, org=org, metadata={"nodes": [], "edges": []})


def _export(export_service, graph):
    return export_service.export_entities(EntityType.GRAPH, [graph.id])


def _import(import_service, export_data, settings, org=None) -> Graph:
    """Import one flow; `import_service` puts it in `default_org` unless `org` is given."""
    id_mapper, _ = import_service.import_data(
        export_data, EntityType.GRAPH, settings=settings, org_id=org.id if org else None
    )
    [graph_data] = export_data[EntityType.GRAPH]
    return Graph.objects.get(pk=id_mapper.get(EntityType.GRAPH, graph_data["id"]))


def _exported_node_uuids(export_data) -> dict:
    [graph_data] = export_data[EntityType.GRAPH]
    return {node_data["id"]: node_data["uuid"] for node_data in graph_data["nodes"]}


def _all_uuids(graph) -> set:
    return {
        node_uuid for model_uuids in node_uuids_by_model(graph).values() for node_uuid in model_uuids
    }


@pytest.mark.django_db
@pytest.mark.parametrize("model", NODE_MODELS, **by_model_name)
def test_export_contains_node_uuid(export_service, default_org, model):
    graph = _flow(default_org)
    node = create_node(model, graph)

    assert _exported_node_uuids(_export(export_service, graph)) == {node.id: str(node.uuid)}


@pytest.mark.django_db
@pytest.mark.parametrize("model", NODE_MODELS, **by_model_name)
def test_replace_import_keeps_node_uuid(export_service, import_service, default_org, model):
    graph = _flow(default_org)
    node = create_node(model, graph)
    export_data = _export(export_service, graph)

    imported = _import(import_service, export_data, REPLACE_IN_PLACE)

    assert imported.pk == graph.pk
    replaced = model.objects.get(graph=graph)
    assert replaced.id != node.id
    assert replaced.uuid == node.uuid


@pytest.mark.django_db
@pytest.mark.parametrize("model", NODE_MODELS, **by_model_name)
def test_import_as_new_flow_gives_new_node_uuid(
    export_service, import_service, default_org, model
):
    graph = _flow(default_org)
    node = create_node(model, graph)

    imported = _import(import_service, _export(export_service, graph), ImportSettings())

    assert imported.pk != graph.pk
    assert model.objects.get(graph=imported).uuid != node.uuid
    assert model.objects.get(graph=graph).uuid == node.uuid


@pytest.mark.django_db
def test_import_keeping_the_flow_uuid_without_replace_gives_new_node_uuids(
    export_service, import_service, default_org
):
    graph = _flow(default_org)
    create_every_node(graph)

    imported = _import(
        import_service,
        _export(export_service, graph),
        ImportSettings(preserve_uuids=True, replace_existing=False),
    )

    assert imported.pk != graph.pk
    assert _all_uuids(imported).isdisjoint(_all_uuids(graph))


@pytest.mark.django_db
def test_import_taking_over_a_soft_deleted_flow_uuid_gives_new_node_uuids(
    export_service, import_service, default_org
):
    graph = _flow(default_org)
    create_every_node(graph)
    source_uuids = _all_uuids(graph)
    export_data = _export(export_service, graph)
    Graph.all_objects.filter(pk=graph.pk).update(
        is_soft_deleted=True, soft_deleted_at=timezone.now()
    )

    imported = _import(import_service, export_data, REPLACE_IN_PLACE)

    assert imported.pk != graph.pk
    assert imported.uuid == graph.uuid
    assert _all_uuids(imported).isdisjoint(source_uuids)


@pytest.mark.django_db
def test_export_replace_import_export_round_trip_keeps_node_uuids(
    export_service, import_service, default_org
):
    graph = _flow(default_org)
    create_every_node(graph)
    first_export = _export(export_service, graph)

    def uuids_per_node_type(export_data):
        [graph_data] = export_data[EntityType.GRAPH]
        return sorted((node["node_type"], node["uuid"]) for node in graph_data["nodes"])

    first_uuids = uuids_per_node_type(first_export)
    first_node_ids = set(_exported_node_uuids(first_export))
    # The import consumes the dict it is given (it pops keys), so pass a copy.
    _import(import_service, deepcopy(first_export), REPLACE_IN_PLACE)
    second_export = _export(export_service, graph)

    assert uuids_per_node_type(second_export) == first_uuids
    assert len(first_uuids) == len(NODE_RELATIONS)
    # The node ids changed: these are new rows that kept the uuids.
    assert first_node_ids.isdisjoint(_exported_node_uuids(second_export))


@pytest.mark.django_db
def test_replace_import_regenerates_a_duplicate_uuid_in_the_file(
    export_service, import_service, default_org
):
    graph = _flow(default_org)
    first = create_node(PythonNode, graph)
    second = create_node(PythonNode, graph)
    export_data = _export(export_service, graph)
    [graph_data] = export_data[EntityType.GRAPH]
    for node_data in graph_data["nodes"]:
        node_data["uuid"] = str(first.uuid)

    _import(import_service, export_data, REPLACE_IN_PLACE)

    uuids = set(PythonNode.objects.filter(graph=graph).values_list("uuid", flat=True))
    assert len(uuids) == 2
    assert first.uuid in uuids
    assert second.uuid not in uuids


@pytest.mark.django_db
def test_partial_import_twice_into_one_graph_gives_new_distinct_uuids(default_org):
    source = _flow(default_org, "source")
    nodes = create_every_node(source, MULTIPLE_PER_GRAPH_NODE_MODELS)
    entity_type_by_model = {
        Graph._meta.get_field(list_key).related_model: entity_type
        for list_key, entity_type in LIST_KEY_TO_ENTITY_TYPE.items()
    }
    export = GraphPartialExportService(entity_registry).export(
        [
            NodeRef(entity_type=entity_type_by_model[model], node_id=node.id)
            for model, node in nodes.items()
        ],
        org_id=default_org.id,
    )
    assert not export.has_errors, export.errors
    target = _flow(default_org, "target")

    for _ in range(2):
        PartialImportService(entity_registry).import_data(
            export.data, target, org_id=default_org.id
        )

    target_uuids = node_uuids_by_model(target, MULTIPLE_PER_GRAPH_NODE_MODELS)
    pasted = [node_uuid for model_uuids in target_uuids.values() for node_uuid in model_uuids]
    assert len(pasted) == 2 * len(MULTIPLE_PER_GRAPH_NODE_MODELS)
    assert len(set(pasted)) == len(pasted)
    assert set(pasted).isdisjoint(node.uuid for node in nodes.values())


@pytest.mark.django_db
def test_node_uuid_of_another_orgs_graph_in_a_file_is_only_data(
    export_service, import_service, acme, beta  # noqa: F811
):
    beta_graph = _flow(beta, "beta flow")
    beta_node = create_node(PythonNode, beta_graph)
    acme_graph = _flow(acme, "acme flow")
    create_node(PythonNode, acme_graph)
    export_data = _export(export_service, acme_graph)
    [graph_data] = export_data[EntityType.GRAPH]
    [node_data] = graph_data["nodes"]
    node_data["uuid"] = str(beta_node.uuid)

    _import(import_service, export_data, REPLACE_IN_PLACE, org=acme)

    assert PythonNode.objects.get(graph=acme_graph).uuid == beta_node.uuid
    beta_node.refresh_from_db()
    assert beta_node.graph_id == beta_graph.id
    assert PythonNode.objects.filter(graph=beta_graph).count() == 1
