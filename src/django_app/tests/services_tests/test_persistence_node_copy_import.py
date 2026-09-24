import pytest

from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.registry import entity_registry
from tables.import_export.services.partial_export_service import LIST_KEY_TO_ENTITY_TYPE
from tables.models import Graph, PersistenceNode, PersistenceTable
from rbac.models import Organization
from tables.services.copy_services.graph_copy_service import GraphCopyService


@pytest.fixture
def source_org(db):
    return Organization.objects.create(name="Source")


@pytest.fixture
def target_org(db):
    return Organization.objects.create(name="Target")


@pytest.fixture
def source_node(source_org):
    graph = Graph.objects.create(name="Flow", org=source_org)
    table = PersistenceTable.objects.create(org=source_org, name="Customers")
    return PersistenceNode.objects.create(
        graph=graph,
        node_name="p",
        persistence_table=table,
        mode="read",
        entries=[{"alias": "a", "key": "k"}],
    )


def _copied_node(new_graph: Graph) -> PersistenceNode:
    return PersistenceNode.objects.get(graph=new_graph)


def _import_into(org: Organization, exported: dict, source_graph_id: int) -> PersistenceNode:
    strategy = entity_registry.get_strategy(EntityType.PERSISTENCE_NODE)
    new_graph = Graph.objects.create(name="Imported", org=org)
    id_mapper = IDMapper()
    id_mapper.map(EntityType.GRAPH, source_graph_id, new_graph.id)
    # `graph` is write-only, so exports omit it; GraphStrategy._create_nodes re-adds the
    # exported graph id before calling create_entity.
    return strategy.create_entity({**exported, "graph": source_graph_id}, id_mapper)


@pytest.mark.django_db
def test_same_org_copy_keeps_table(source_node):
    new_graph = GraphCopyService().copy(source_node.graph, name="Flow copy")
    copied = _copied_node(new_graph)
    assert copied.persistence_table_id == source_node.persistence_table_id
    assert copied.entries == source_node.entries
    assert copied.mode == "read"


@pytest.mark.django_db
def test_cross_org_copy_binds_same_named_table_in_target(source_node, target_org):
    target_table = PersistenceTable.objects.create(org=target_org, name="customers")
    new_graph = GraphCopyService().copy(source_node.graph, name="Flow", org_id=target_org.id)
    assert _copied_node(new_graph).persistence_table_id == target_table.id


@pytest.mark.django_db
def test_cross_org_copy_without_matching_table_nulls_reference(source_node, target_org):
    new_graph = GraphCopyService().copy(source_node.graph, name="Flow", org_id=target_org.id)
    assert _copied_node(new_graph).persistence_table_id is None


@pytest.mark.django_db
def test_export_then_import_round_trip_same_org(source_node, source_org):
    strategy = entity_registry.get_strategy(EntityType.PERSISTENCE_NODE)
    exported = strategy.export_entity(source_node)
    assert exported["persistence_table_name"] == "Customers"

    imported = _import_into(source_org, exported, source_node.graph_id)

    assert imported.graph.org_id == source_org.id
    assert imported.persistence_table_id == source_node.persistence_table_id
    assert imported.mode == "read"
    assert imported.entries == source_node.entries


@pytest.mark.django_db
def test_import_after_table_rename_does_not_bind_wrong_table(source_node, source_org):
    strategy = entity_registry.get_strategy(EntityType.PERSISTENCE_NODE)
    exported = strategy.export_entity(source_node)
    source_node.persistence_table.name = "Renamed"
    source_node.persistence_table.save()

    imported = _import_into(source_org, exported, source_node.graph_id)

    assert imported.persistence_table_id is None


@pytest.mark.django_db
def test_import_into_other_org_never_keeps_foreign_table_id(source_node, target_org):
    strategy = entity_registry.get_strategy(EntityType.PERSISTENCE_NODE)
    exported = strategy.export_entity(source_node)

    imported = _import_into(target_org, exported, source_node.graph_id)

    assert imported.persistence_table_id is None


@pytest.mark.django_db
def test_import_into_other_org_ignores_same_id_table_with_different_name(
    source_node, target_org
):
    strategy = entity_registry.get_strategy(EntityType.PERSISTENCE_NODE)
    exported = dict(strategy.export_entity(source_node))
    # The file came from another installation: its table id collides with an unrelated
    # table of the target org, and no target table is named like the exported one.
    unrelated_table = PersistenceTable.objects.create(org=target_org, name="Invoices")
    exported["persistence_table"] = unrelated_table.id

    imported = _import_into(target_org, exported, source_node.graph_id)

    assert imported.persistence_table_id is None


@pytest.mark.django_db
def test_import_into_other_org_binds_same_named_target_table(source_node, target_org):
    target_table = PersistenceTable.objects.create(org=target_org, name="CUSTOMERS")
    strategy = entity_registry.get_strategy(EntityType.PERSISTENCE_NODE)
    exported = strategy.export_entity(source_node)

    imported = _import_into(target_org, exported, source_node.graph_id)

    assert imported.persistence_table_id == target_table.id


def test_partial_export_knows_persistence_nodes():
    assert LIST_KEY_TO_ENTITY_TYPE["persistence_node_list"] == EntityType.PERSISTENCE_NODE
