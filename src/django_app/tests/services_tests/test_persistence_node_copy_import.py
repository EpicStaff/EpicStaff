import pytest
from django.urls import reverse
from rest_framework import serializers, status
from rest_framework.test import APIClient

from rbac.identity.api_keys.principals import SystemServicePrincipal
from rbac.models import Organization, OrganizationUser, Role, RolePermission
from rbac.models.enums import Permission, ResourceType
from tables.graph_versioning.services import GraphVersioningService
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.registry import entity_registry
from tables.import_export.services.partial_export_service import (
    LIST_KEY_TO_ENTITY_TYPE,
    GraphPartialExportService,
    NodeRef,
)
from tables.import_export.services.partial_import_service import PartialImportService
from tables.models import Graph, PersistenceNode, PersistenceTable
from tables.services.copy_services.graph_copy_service import GraphCopyService
from tables.services.persistence_table_service import PersistenceTableService

FLOWS_ALL = 255


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
        entries=[{"key": "k", "value": "variables.a"}],
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


@pytest.mark.django_db
def test_import_rejects_malformed_entries(source_node, source_org):
    strategy = entity_registry.get_strategy(EntityType.PERSISTENCE_NODE)
    exported = {**strategy.export_entity(source_node), "entries": "x"}

    with pytest.raises(serializers.ValidationError):
        _import_into(source_org, exported, source_node.graph_id)


@pytest.mark.django_db
def test_import_rejects_entries_that_do_not_fit_the_mode(source_node, source_org):
    strategy = entity_registry.get_strategy(EntityType.PERSISTENCE_NODE)
    # Read and write share the {key, value} shape; delete takes only a key.
    exported = {**strategy.export_entity(source_node), "mode": "delete"}

    with pytest.raises(serializers.ValidationError):
        _import_into(source_org, exported, source_node.graph_id)


@pytest.mark.django_db
def test_import_rejects_write_value_that_is_not_a_state_path(source_node, source_org):
    strategy = entity_registry.get_strategy(EntityType.PERSISTENCE_NODE)
    exported = {
        **strategy.export_entity(source_node),
        "mode": "write",
        "entries": [{"key": "k", "value": "user.name"}],
    }

    with pytest.raises(serializers.ValidationError, match="must be a state path"):
        _import_into(source_org, exported, source_node.graph_id)


# persistent_data:USE gates table binding on every path that has an acting user.


def _member_of(django_user_model, orgs: list[Organization], email: str, persistent_data: int):
    user = django_user_model.objects.create_user(email=email, password="StrongPass123!")
    for org in orgs:
        role = Role.objects.create(name=f"flows-{email}", org=org, is_built_in=False)
        RolePermission.objects.create(
            role=role, resource_type=ResourceType.FLOWS, permissions=FLOWS_ALL
        )
        if persistent_data:
            RolePermission.objects.create(
                role=role, resource_type=ResourceType.PERSISTENT_DATA, permissions=persistent_data
            )
        OrganizationUser.objects.create(user=user, org=org, role=role)
    return user


@pytest.fixture
def no_use_user(django_user_model, source_org, target_org):
    return _member_of(django_user_model, [source_org, target_org], "no-use@example.com", 0)


@pytest.fixture
def use_user(django_user_model, source_org, target_org):
    return _member_of(
        django_user_model,
        [source_org, target_org],
        "use@example.com",
        int(Permission.READ | Permission.USE),
    )


def _paste(source_node: PersistenceNode, target_graph: Graph, user) -> PersistenceNode:
    result = GraphPartialExportService(entity_registry).export(
        [NodeRef(entity_type=EntityType.PERSISTENCE_NODE, node_id=source_node.id)]
    )
    assert not result.has_errors, result.errors
    PartialImportService(entity_registry).import_data(
        export_data=result.data, graph=target_graph, org_id=target_graph.org_id, user=user
    )
    return PersistenceNode.objects.get(graph=target_graph)


@pytest.mark.django_db
def test_paste_without_use_permission_leaves_node_without_table(
    source_node, source_org, no_use_user
):
    target_graph = Graph.objects.create(name="Paste target", org=source_org)

    pasted = _paste(source_node, target_graph, no_use_user)

    assert pasted.persistence_table_id is None


@pytest.mark.django_db
def test_paste_with_use_permission_binds_table(source_node, source_org, use_user):
    target_graph = Graph.objects.create(name="Paste target", org=source_org)

    pasted = _paste(source_node, target_graph, use_user)

    assert pasted.persistence_table_id == source_node.persistence_table_id


@pytest.mark.django_db
def test_cross_org_paste_binds_target_org_table(source_node, target_org, use_user):
    target_table = PersistenceTable.objects.create(org=target_org, name="customers")
    target_graph = Graph.objects.create(name="Paste target", org=target_org)

    pasted = _paste(source_node, target_graph, use_user)

    assert pasted.persistence_table_id == target_table.id


@pytest.mark.django_db
def test_full_import_without_use_permission_leaves_node_without_table(
    source_node, source_org, no_use_user
):
    graph_strategy = entity_registry.get_strategy(EntityType.GRAPH)
    exported_graph = graph_strategy.export_entity(source_node.graph)

    new_graph = graph_strategy.create_entity(
        dict(exported_graph), IDMapper(), org_id=source_org.id, user=no_use_user
    )

    assert new_graph.persistence_node_list.get().persistence_table_id is None


@pytest.mark.django_db
def test_graph_copy_without_use_permission_leaves_node_without_table(source_node, no_use_user):
    new_graph = GraphCopyService().copy(source_node.graph, name="Flow copy", user=no_use_user)

    assert _copied_node(new_graph).persistence_table_id is None


@pytest.mark.django_db
def test_copy_endpoint_passes_the_acting_user(source_node, source_org, no_use_user):
    client = APIClient()
    client.force_authenticate(user=no_use_user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(source_org.id))

    response = client.post(reverse("graphs-copy", args=[source_node.graph_id]), {}, format="json")

    assert response.status_code == status.HTTP_201_CREATED, response.content
    copied = PersistenceNode.objects.get(graph_id=response.data["id"])
    assert copied.persistence_table_id is None


@pytest.mark.django_db
def test_version_restore_without_use_permission_leaves_node_without_table(
    source_node, no_use_user
):
    graph = source_node.graph
    versioning = GraphVersioningService()
    version = versioning.save_version(graph=graph, name="v1")
    graph.refresh_from_db()

    versioning.restore_version(
        version, expected_save_version=graph.save_version, user=no_use_user
    )

    assert graph.persistence_node_list.get().persistence_table_id is None


@pytest.mark.django_db
def test_create_graph_from_version_without_use_permission_leaves_node_without_table(
    source_node, no_use_user
):
    versioning = GraphVersioningService()
    version = versioning.save_version(graph=source_node.graph, name="v1")

    result = versioning.create_graph_from_version(version, user=no_use_user)

    new_graph = Graph.objects.get(pk=result["graph_id"])
    assert new_graph.persistence_node_list.get().persistence_table_id is None


@pytest.mark.django_db
def test_system_principal_binds_table(source_node, source_org):
    table = source_node.persistence_table

    resolved = PersistenceTableService().resolve_reference(
        source_org.id, table.id, table.name, user=SystemServicePrincipal()
    )

    assert resolved == table
