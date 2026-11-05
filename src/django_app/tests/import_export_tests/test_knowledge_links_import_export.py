"""Knowledge links on knowledge nodes and on surfaces: they follow a collection the
file carried, relink to the same collection inside one org, and are dropped when
the target org has no such collection."""

import json
import os
import uuid
from decimal import Decimal

import pytest

from agents.models import (
    AgentDefinition,
    AgentInlineSurface,
    AgentInlineSurfaceKnowledge,
    InlineSurface,
    InlineSurfaceKnowledge,
    Surface,
    SurfaceGraphLocalSearchConfig,
    SurfaceKnowledge,
    SurfaceNaiveSearchConfig,
)
from rbac.models import Organization
from tables.import_export.archive import ExportArchiveWriter, ImportArchive
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.registry import entity_registry
from tables.import_export.services.export_service import ExportService
from tables.import_export.services.import_service import ImportService
from tables.import_export.services.partial_export_service import (
    GraphPartialExportService,
    NodeRef,
)
from tables.import_export.serializers.surface_knowledge import create_knowledge
from tables.import_export.services.partial_import_service import PartialImportService
from tables.import_export.strategies.source_collection import SourceCollectionStrategy
from tables.import_export.strategies.surface import SurfaceStrategy
from tables.models import AgentNode, Graph, KnowledgeNode, TaskNode
from tables.models.knowledge_models import (
    KnowledgeNodeNaiveRagSearchConfig,
    BaseRagType,
    GraphRag,
    NaiveRag,
    SourceCollection,
)
from tests.helpers import UNRESTRICTED_EXPORT_POLICY
from tests.import_export_tests.knowledge_builders import (
    make_document,
    make_graph_rag,
    make_naive_rag,
)


@pytest.fixture
def target_org(db):
    return Organization.objects.create(name="Target Organization")


@pytest.fixture
def collection(default_org):
    collection = SourceCollection.objects.create(
        collection_name="Handbook", description="HR docs", org=default_org
    )
    make_document(collection, "policy.txt", b"policy")
    return collection


@pytest.fixture
def graph(default_org):
    return Graph.objects.create(
        name="knowledge flow", metadata={"nodes": [], "edges": []}, org=default_org
    )


def _export(entity_type, entity_id, *, include_knowledge=False) -> dict:
    return (
        ExportService(entity_registry)
        .export_entities(
            entity_type,
            [entity_id],
            policy=UNRESTRICTED_EXPORT_POLICY,
            include_knowledge=include_knowledge,
        )
        .data
    )


def _import_json(entity_type, entity_id, org) -> IDMapper:
    """Export without knowledge and import the plain JSON into `org`."""
    export_data = json.loads(json.dumps(_export(entity_type, entity_id)))
    id_mapper, _ = ImportService(entity_registry).import_data(
        export_data, main_entity=entity_type, org_id=org.id
    )
    return id_mapper


def _import_archive(entity_type, entity_id, org, tmp_path) -> IDMapper:
    """Export with knowledge into an archive and import it into `org`."""
    export_data = _export(entity_type, entity_id, include_knowledge=True)
    with ExportArchiveWriter() as writer:
        writer.write_envelope(export_data)
        for entry in export_data.get(EntityType.SOURCE_COLLECTION, []):
            SourceCollectionStrategy().write_archive_members(entry, writer)
    path = tmp_path / f"export-{uuid.uuid4()}.zip"
    os.replace(writer.path, path)
    with ImportArchive.open(str(path)) as archive:
        id_mapper, _ = ImportService(entity_registry).import_data(
            archive.envelope(), main_entity=entity_type, org_id=org.id, archive=archive
        )
    return id_mapper


def _imported_collection(id_mapper, collection) -> SourceCollection:
    return SourceCollection.objects.get(
        pk=id_mapper.get(EntityType.SOURCE_COLLECTION, collection.collection_id)
    )


def _imported_graph(id_mapper, graph) -> Graph:
    return Graph.objects.get(pk=id_mapper.get(EntityType.GRAPH, graph.id))


def _attach_knowledge(knowledge_model, owner_kwargs, collection):
    """Attach `collection` with a naive and a graph-local search config."""
    row = knowledge_model.objects.create(collection=collection, **owner_kwargs)
    naive_model = knowledge_model._meta.get_field("naive_search_config").related_model
    local_model = knowledge_model._meta.get_field("graph_local_search_config").related_model
    naive_model.objects.create(
        surface_knowledge=row, search_limit=7, similarity_threshold=Decimal("0.55")
    )
    local_model.objects.create(surface_knowledge=row, top_k_entities=13)
    return row


def _knowledge_of(rows) -> list[tuple]:
    """(collection, naive limit, naive threshold, local top_k, has basic config) per row."""
    result = []
    for row in rows:
        naive = getattr(row, "naive_search_config", None)
        local = getattr(row, "graph_local_search_config", None)
        result.append(
            (
                row.collection_id,
                naive.search_limit if naive else None,
                naive.similarity_threshold if naive else None,
                local.top_k_entities if local else None,
                hasattr(row, "graph_basic_search_config"),
            )
        )
    return result


# --- knowledge nodes ----------------------------------------------------------------------


def _naive_link(collection):
    return BaseRagType.RagType.NAIVE, make_naive_rag(collection).naive_rag_id


def _graph_link(collection):
    return BaseRagType.RagType.GRAPH, make_graph_rag(
        collection, status=GraphRag.GraphRagStatus.NEW
    ).graph_rag_id


@pytest.mark.django_db
@pytest.mark.parametrize("make_link", [_naive_link, _graph_link], ids=["naive", "graph"])
def test_knowledge_node_points_at_the_carried_collection_and_its_new_rag(
    collection, graph, target_org, tmp_path, make_link
):
    rag_type, rag_id = make_link(collection)
    KnowledgeNode.objects.create(
        graph=graph, source_collection=collection, rag_type=rag_type, rag_id=rag_id
    )

    id_mapper = _import_archive(EntityType.GRAPH, graph.id, target_org, tmp_path)

    imported = _imported_collection(id_mapper, collection)
    assert imported.org_id == target_org.id
    rag_model = NaiveRag if rag_type == BaseRagType.RagType.NAIVE else GraphRag
    new_rag = rag_model.objects.get(base_rag_type__source_collection=imported)
    node = KnowledgeNode.objects.get(graph=_imported_graph(id_mapper, graph))
    assert (node.source_collection_id, node.rag_type, node.rag_id) == (
        imported.collection_id,
        rag_type,
        new_rag.pk,
    )


@pytest.mark.django_db
def test_knowledge_node_relinks_to_the_same_collection_inside_one_org(
    collection, graph, default_org
):
    rag_type, rag_id = _naive_link(collection)
    KnowledgeNode.objects.create(
        graph=graph, source_collection=collection, rag_type=rag_type, rag_id=rag_id
    )

    id_mapper = _import_json(EntityType.GRAPH, graph.id, default_org)

    node = KnowledgeNode.objects.get(graph=_imported_graph(id_mapper, graph))
    assert (node.source_collection_id, node.rag_type, node.rag_id) == (
        collection.collection_id,
        rag_type,
        rag_id,
    )
    assert SourceCollection.objects.filter(org=default_org).count() == 1


@pytest.mark.django_db
def test_knowledge_node_link_is_cleared_in_an_org_without_the_collection(
    collection, graph, target_org
):
    rag_type, rag_id = _naive_link(collection)
    KnowledgeNode.objects.create(
        graph=graph, source_collection=collection, rag_type=rag_type, rag_id=rag_id
    )

    id_mapper = _import_json(EntityType.GRAPH, graph.id, target_org)

    node = KnowledgeNode.objects.get(graph=_imported_graph(id_mapper, graph))
    assert (node.source_collection_id, node.rag_type, node.rag_id) == (None, None, None)


# --- shared surfaces ----------------------------------------------------------------------


@pytest.fixture
def surface(default_org, collection):
    surface = Surface.objects.create(org=default_org, name="research", instructions="look up")
    _attach_knowledge(SurfaceKnowledge, {"surface": surface}, collection)
    return surface


@pytest.mark.django_db
def test_surface_knowledge_survives_a_same_instance_round_trip(surface, collection, default_org):
    id_mapper = _import_json(EntityType.SURFACE, surface.id, default_org)

    imported = Surface.objects.get(pk=id_mapper.get(EntityType.SURFACE, surface.id))
    assert imported.pk != surface.pk
    assert _knowledge_of(imported.knowledge.all()) == [
        (collection.collection_id, 7, Decimal("0.55"), 13, False)
    ]


@pytest.mark.django_db
def test_surface_knowledge_follows_a_carried_collection(surface, collection, target_org, tmp_path):
    id_mapper = _import_archive(EntityType.SURFACE, surface.id, target_org, tmp_path)

    imported = Surface.objects.get(pk=id_mapper.get(EntityType.SURFACE, surface.id))
    assert _knowledge_of(imported.knowledge.all()) == [
        (_imported_collection(id_mapper, collection).collection_id, 7, Decimal("0.55"), 13, False)
    ]


@pytest.mark.django_db
def test_surface_knowledge_is_dropped_when_the_collection_is_unknown(surface, target_org):
    id_mapper = _import_json(EntityType.SURFACE, surface.id, target_org)

    imported = Surface.objects.get(pk=id_mapper.get(EntityType.SURFACE, surface.id))
    assert list(imported.knowledge.all()) == []


@pytest.mark.django_db
def test_surface_is_reused_only_when_its_knowledge_matches(surface, default_org):
    entry = json.loads(json.dumps(_export(EntityType.SURFACE, surface.id)))[EntityType.SURFACE][0]
    strategy = SurfaceStrategy()

    assert strategy.find_existing(entry, IDMapper(), org_id=default_org.id) == surface

    SurfaceNaiveSearchConfig.objects.filter(surface_knowledge__surface=surface).update(
        search_limit=8
    )
    assert strategy.find_existing(entry, IDMapper(), org_id=default_org.id) is None

    SurfaceNaiveSearchConfig.objects.filter(surface_knowledge__surface=surface).update(
        search_limit=7
    )
    SurfaceGraphLocalSearchConfig.objects.filter(surface_knowledge__surface=surface).delete()
    assert strategy.find_existing(entry, IDMapper(), org_id=default_org.id) is None


@pytest.mark.django_db
def test_owned_surface_knowledge_travels_with_its_agent(
    collection, default_org, target_org, tmp_path
):
    agent = AgentDefinition.objects.create(org=default_org, name="researcher")
    owned = Surface.objects.create(
        org=default_org, name="owned", instructions="mine", owner_agent=agent
    )
    _attach_knowledge(SurfaceKnowledge, {"surface": owned}, collection)

    id_mapper = _import_archive(EntityType.AGENT_DEFINITION, agent.id, target_org, tmp_path)

    imported_agent = AgentDefinition.objects.get(
        pk=id_mapper.get(EntityType.AGENT_DEFINITION, agent.id)
    )
    [imported_owned] = imported_agent.owned_surfaces.all()
    assert _knowledge_of(imported_owned.knowledge.all()) == [
        (_imported_collection(id_mapper, collection).collection_id, 7, Decimal("0.55"), 13, False)
    ]


def _import_edited_json(entity_type, entity_id, org, edit, before_import=None) -> IDMapper:
    """Export without knowledge, let `edit` change the file, run `before_import`,
    and import the file into `org`."""
    export_data = json.loads(json.dumps(_export(entity_type, entity_id)))
    edit(export_data)
    if before_import is not None:
        before_import()
    id_mapper, _ = ImportService(entity_registry).import_data(
        export_data, main_entity=entity_type, org_id=org.id
    )
    return id_mapper


def _drop_collection_names(export_data):
    for surface in export_data[EntityType.SURFACE]:
        for entry in surface["knowledge"]:
            del entry["collection_name"]


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("rename_to", "edit", "relinked"),
    [
        pytest.param(None, lambda data: None, True, id="same id and name"),
        pytest.param("Something else", lambda data: None, False, id="same id, other name"),
        pytest.param(
            "Something else", _drop_collection_names, True, id="file without names: id only"
        ),
    ],
)
def test_a_link_relinks_by_id_only_when_the_name_matches_too(
    surface, collection, default_org, rename_to, edit, relinked
):
    def rename():
        # After the export: the file keeps the name the collection had then.
        if rename_to is not None:
            collection.collection_name = rename_to
            collection.save()

    id_mapper = _import_edited_json(
        EntityType.SURFACE, surface.id, default_org, edit, before_import=rename
    )

    imported = Surface.objects.get(pk=id_mapper.get(EntityType.SURFACE, surface.id))
    expected = [collection.collection_id] if relinked else []
    assert list(imported.knowledge.values_list("collection_id", flat=True)) == expected


@pytest.mark.django_db
def test_a_knowledge_node_is_not_relinked_to_another_collection_with_its_id(
    collection, graph, default_org
):
    rag_type, rag_id = _naive_link(collection)
    KnowledgeNode.objects.create(
        graph=graph, source_collection=collection, rag_type=rag_type, rag_id=rag_id
    )
    export_data = json.loads(json.dumps(_export(EntityType.GRAPH, graph.id)))
    collection.collection_name = "Something else"
    collection.save()

    id_mapper, _ = ImportService(entity_registry).import_data(
        export_data, main_entity=EntityType.GRAPH, org_id=default_org.id
    )

    node = KnowledgeNode.objects.get(graph=_imported_graph(id_mapper, graph))
    assert (node.source_collection_id, node.rag_id) == (None, None)


@pytest.mark.django_db
def test_a_search_config_takes_only_its_own_fields_and_a_collection_is_linked_once(
    collection, default_org
):
    target = Surface.objects.create(org=default_org, name="target", instructions="x")
    taken_id = (
        SurfaceNaiveSearchConfig.all_objects.order_by("-pk").values_list("pk", flat=True).first()
        or 0
    )
    entry = {
        "collection": collection.collection_id,
        "collection_name": collection.collection_name,
        "naive_search_config": {"id": taken_id + 1000, "search_limit": 9, "not_a_field": 1},
    }

    create_knowledge(
        SurfaceKnowledge, {"surface": target}, [entry, dict(entry)], IDMapper(), default_org.id
    )

    [row] = target.knowledge.all()
    assert row.naive_search_config.search_limit == 9
    assert row.naive_search_config.pk != taken_id + 1000


@pytest.mark.django_db
def test_a_knowledge_node_search_config_takes_only_its_own_fields(graph, default_org):
    node = KnowledgeNode.objects.create(graph=graph)
    KnowledgeNodeNaiveRagSearchConfig.objects.create(knowledge_node=node, search_limit=4)
    export_data = json.loads(json.dumps(_export(EntityType.GRAPH, graph.id)))
    [node_entry] = [
        entry
        for entry in export_data[EntityType.GRAPH][0]["nodes"]
        if entry.get("naive_search_config")
    ]
    taken_id = KnowledgeNodeNaiveRagSearchConfig.all_objects.order_by("-pk").first().pk
    node_entry["naive_search_config"].update(id=taken_id + 1000, not_a_field=1)

    id_mapper, _ = ImportService(entity_registry).import_data(
        export_data, main_entity=EntityType.GRAPH, org_id=default_org.id
    )

    imported = KnowledgeNode.objects.get(graph=_imported_graph(id_mapper, graph))
    assert imported.naive_search_config.search_limit == 4
    assert imported.naive_search_config.pk != taken_id + 1000


# --- inline surfaces of agent and task nodes ---------------------------------------------


@pytest.mark.django_db
def test_inline_surface_knowledge_follows_a_carried_collection(
    collection, graph, default_org, target_org, tmp_path
):
    agent = AgentDefinition.objects.create(org=default_org, name="node agent")
    agent_node = AgentNode.objects.create(graph=graph, agent_definition=agent)
    agent_inline = AgentInlineSurface.objects.create(agent_node=agent_node, instructions="a")
    _attach_knowledge(
        AgentInlineSurfaceKnowledge, {"agent_inline_surface": agent_inline}, collection
    )
    task_node = TaskNode.objects.create(graph=graph, agent_definition=agent, instructions="t")
    task_inline = InlineSurface.objects.create(task_node=task_node, instructions="b")
    _attach_knowledge(InlineSurfaceKnowledge, {"inline_surface": task_inline}, collection)

    id_mapper = _import_archive(EntityType.GRAPH, graph.id, target_org, tmp_path)

    imported_graph = _imported_graph(id_mapper, graph)
    expected = [
        (_imported_collection(id_mapper, collection).collection_id, 7, Decimal("0.55"), 13, False)
    ]
    imported_agent_node = AgentNode.objects.get(graph=imported_graph)
    imported_task_node = TaskNode.objects.get(graph=imported_graph)
    assert _knowledge_of(imported_agent_node.inline_surface.knowledge.all()) == expected
    assert _knowledge_of(imported_task_node.inline_surface.knowledge.all()) == expected


# --- what an export carries ---------------------------------------------------------------


@pytest.mark.django_db
def test_collections_travel_as_dependencies_only_when_knowledge_is_included(collection, graph):
    KnowledgeNode.objects.create(graph=graph, source_collection=collection)

    assert EntityType.SOURCE_COLLECTION not in _export(EntityType.GRAPH, graph.id)
    assert [
        entry["id"]
        for entry in _export(EntityType.GRAPH, graph.id, include_knowledge=True)[
            EntityType.SOURCE_COLLECTION
        ]
    ] == [collection.collection_id]
    # A collection asked for by itself is exported whatever the flag says.
    assert EntityType.SOURCE_COLLECTION in _export(
        EntityType.SOURCE_COLLECTION, collection.collection_id
    )


@pytest.mark.django_db
def test_a_pasted_knowledge_node_relinks_without_carrying_the_collection(
    collection, graph, default_org
):
    rag_type, rag_id = _naive_link(collection)
    node = KnowledgeNode.objects.create(
        graph=graph, source_collection=collection, rag_type=rag_type, rag_id=rag_id
    )

    export_result = GraphPartialExportService(entity_registry).export(
        [NodeRef(entity_type=EntityType.KNOWLEDGE_NODE, node_id=node.id)],
        org_id=default_org.id,
        policy=UNRESTRICTED_EXPORT_POLICY,
    )
    target_graph = Graph.objects.create(
        name="paste target", metadata={"nodes": [], "edges": []}, org=default_org
    )
    result = PartialImportService(entity_registry).import_data(
        json.loads(json.dumps(export_result.data)), target_graph, org_id=default_org.id
    )

    assert EntityType.SOURCE_COLLECTION not in export_result.data
    # A paste returns the nodes unsaved; the client saves them with the flow.
    [pasted] = result.content["knowledge_node_list"]
    assert (pasted["source_collection"], pasted["rag_id"]) == (collection.collection_id, rag_id)
