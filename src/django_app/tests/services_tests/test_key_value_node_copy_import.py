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
from tables.import_export.services.export_service import ExportService
from tables.import_export.services.partial_export_service import (
    LIST_KEY_TO_ENTITY_TYPE,
    GraphPartialExportService,
    NodeRef,
)
from tables.import_export.services.partial_import_service import PartialImportService
from tables.models import Graph, KeyValueNode, KeyValueTable
from tables.services.copy_services.graph_copy_service import GraphCopyService
from tables.services.key_value_table_service import KeyValueTableService
from tests.helpers import data_to_json_file

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
    table = KeyValueTable.objects.create(org=source_org, name="Customers")
    return KeyValueNode.objects.create(
        graph=graph,
        node_name="p",
        key_value_table=table,
        mode="read",
        entries=[{"key": "k", "value": "variables.a"}],
    )


def _copied_node(new_graph: Graph) -> KeyValueNode:
    return KeyValueNode.objects.get(graph=new_graph)


def _import_into(org: Organization, exported: dict, source_graph_id: int) -> KeyValueNode:
    strategy = entity_registry.get_strategy(EntityType.KEY_VALUE_NODE)
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
    assert copied.key_value_table_id == source_node.key_value_table_id
    assert copied.entries == source_node.entries
    assert copied.mode == "read"


@pytest.mark.django_db
def test_cross_org_copy_binds_same_named_table_in_target(source_node, target_org):
    target_table = KeyValueTable.objects.create(org=target_org, name="customers")
    new_graph = GraphCopyService().copy(source_node.graph, name="Flow", org_id=target_org.id)
    assert _copied_node(new_graph).key_value_table_id == target_table.id


@pytest.mark.django_db
def test_cross_org_copy_without_matching_table_nulls_reference(source_node, target_org):
    new_graph = GraphCopyService().copy(source_node.graph, name="Flow", org_id=target_org.id)
    assert _copied_node(new_graph).key_value_table_id is None


@pytest.mark.django_db
def test_export_then_import_round_trip_same_org(source_node, source_org):
    strategy = entity_registry.get_strategy(EntityType.KEY_VALUE_NODE)
    exported = strategy.export_entity(source_node)
    assert exported["key_value_table_name"] == "Customers"

    imported = _import_into(source_org, exported, source_node.graph_id)

    assert imported.graph.org_id == source_org.id
    assert imported.key_value_table_id == source_node.key_value_table_id
    assert imported.mode == "read"
    assert imported.entries == source_node.entries


@pytest.mark.django_db
def test_import_after_table_rename_does_not_bind_wrong_table(source_node, source_org):
    strategy = entity_registry.get_strategy(EntityType.KEY_VALUE_NODE)
    exported = strategy.export_entity(source_node)
    source_node.key_value_table.name = "Renamed"
    source_node.key_value_table.save()

    imported = _import_into(source_org, exported, source_node.graph_id)

    assert imported.key_value_table_id is None


@pytest.mark.django_db
def test_import_into_other_org_never_keeps_foreign_table_id(source_node, target_org):
    strategy = entity_registry.get_strategy(EntityType.KEY_VALUE_NODE)
    exported = strategy.export_entity(source_node)

    imported = _import_into(target_org, exported, source_node.graph_id)

    assert imported.key_value_table_id is None


@pytest.mark.django_db
def test_import_into_other_org_ignores_same_id_table_with_different_name(
    source_node, target_org
):
    strategy = entity_registry.get_strategy(EntityType.KEY_VALUE_NODE)
    exported = dict(strategy.export_entity(source_node))
    # The file came from another installation: its table id collides with an unrelated
    # table of the target org, and no target table is named like the exported one.
    unrelated_table = KeyValueTable.objects.create(org=target_org, name="Invoices")
    exported["key_value_table"] = unrelated_table.id

    imported = _import_into(target_org, exported, source_node.graph_id)

    assert imported.key_value_table_id is None


@pytest.mark.django_db
def test_import_into_other_org_binds_same_named_target_table(source_node, target_org):
    target_table = KeyValueTable.objects.create(org=target_org, name="CUSTOMERS")
    strategy = entity_registry.get_strategy(EntityType.KEY_VALUE_NODE)
    exported = strategy.export_entity(source_node)

    imported = _import_into(target_org, exported, source_node.graph_id)

    assert imported.key_value_table_id == target_table.id


def test_partial_export_knows_key_value_nodes():
    assert LIST_KEY_TO_ENTITY_TYPE["key_value_node_list"] == EntityType.KEY_VALUE_NODE


@pytest.mark.django_db
def test_partial_export_carries_no_key_value_table(source_node):
    """Pasting a node re-binds by name; only a full flow export ships the table itself."""
    full = ExportService(entity_registry).export_entities(
        EntityType.GRAPH, [source_node.graph_id], org_id=source_node.graph.org_id
    )
    partial = GraphPartialExportService(entity_registry).export(
        [NodeRef(entity_type=EntityType.KEY_VALUE_NODE, node_id=source_node.id)],
        org_id=source_node.graph.org_id,
    )

    assert not partial.has_errors, partial.errors
    assert EntityType.KEY_VALUE_TABLE in full
    assert EntityType.KEY_VALUE_TABLE not in partial.data
    [node] = partial.data[EntityType.KEY_VALUE_NODE]
    assert (node["key_value_table"], node["key_value_table_name"]) == (
        source_node.key_value_table_id,
        "Customers",
    )


@pytest.mark.django_db
def test_import_rejects_malformed_entries(source_node, source_org):
    strategy = entity_registry.get_strategy(EntityType.KEY_VALUE_NODE)
    exported = {**strategy.export_entity(source_node), "entries": "x"}

    with pytest.raises(serializers.ValidationError):
        _import_into(source_org, exported, source_node.graph_id)


@pytest.mark.django_db
def test_import_rejects_entries_that_do_not_fit_the_mode(source_node, source_org):
    strategy = entity_registry.get_strategy(EntityType.KEY_VALUE_NODE)
    # Read and write share the {key, value} shape; delete takes only a key.
    exported = {**strategy.export_entity(source_node), "mode": "delete"}

    with pytest.raises(serializers.ValidationError):
        _import_into(source_org, exported, source_node.graph_id)


@pytest.mark.django_db
def test_import_rejects_write_value_that_is_not_a_state_path(source_node, source_org):
    strategy = entity_registry.get_strategy(EntityType.KEY_VALUE_NODE)
    exported = {
        **strategy.export_entity(source_node),
        "mode": "write",
        "entries": [{"key": "k", "value": "user.name"}],
    }

    with pytest.raises(serializers.ValidationError, match="must be a state path"):
        _import_into(source_org, exported, source_node.graph_id)


@pytest.mark.django_db
def test_full_import_rejects_invalid_key(source_node, source_org):
    KeyValueNode.objects.filter(pk=source_node.pk).update(
        entries=[{"key": "user-1", "value": "variables.a"}]
    )
    source_node.refresh_from_db()
    graph_strategy = entity_registry.get_strategy(EntityType.GRAPH)
    exported_graph = graph_strategy.export_entity(source_node.graph)

    with pytest.raises(serializers.ValidationError, match="'key' must use only letters"):
        graph_strategy.create_entity(dict(exported_graph), IDMapper(), org_id=source_org.id)


# A node's mode decides which key_value_tables permissions binding its table needs, on every
# path that has an acting user. Without them the node is created with no table.

R = int(Permission.READ)
C = int(Permission.CREATE)
U = int(Permission.UPDATE)
D = int(Permission.DELETE)

# (key_value_tables bits, source node mode, table stays bound)
BINDING_CASES = [
    pytest.param(0, "read", False, id="none-read"),
    pytest.param(R, "read", True, id="R-read"),
    pytest.param(R, "write", False, id="R-write"),
    pytest.param(R | C, "write", False, id="RC-write"),
    pytest.param(R | C | U, "write", True, id="RCU-write"),
    pytest.param(D, "delete", False, id="D-delete"),
    pytest.param(R | D, "delete", True, id="RD-delete"),
]


def _member_of(django_user_model, orgs: list[Organization], email: str, key_value_tables: int):
    user = django_user_model.objects.create_user(email=email, password="StrongPass123!")
    for org in orgs:
        role = Role.objects.create(name=f"flows-{email}", org=org, is_built_in=False)
        RolePermission.objects.create(
            role=role, resource_type=ResourceType.FLOWS, permissions=FLOWS_ALL
        )
        if key_value_tables:
            RolePermission.objects.create(
                role=role, resource_type=ResourceType.KEY_VALUE_TABLES, permissions=key_value_tables
            )
        OrganizationUser.objects.create(user=user, org=org, role=role)
    return user


@pytest.fixture
def acting_user(django_user_model, source_org, target_org):
    def _make(bits: int):
        return _member_of(
            django_user_model, [source_org, target_org], f"bits-{bits}@example.com", bits
        )

    return _make


def _set_mode(node: KeyValueNode, mode: str) -> KeyValueNode:
    node.mode = mode
    # Delete entries name only a key; a read/write entry's value is invalid there.
    if mode == "delete":
        node.entries = [{"key": entry["key"]} for entry in node.entries]
    node.save(update_fields=["mode", "entries"])
    return node


def _paste(source_node: KeyValueNode, target_graph: Graph, user) -> KeyValueNode:
    result = GraphPartialExportService(entity_registry).export(
        [NodeRef(entity_type=EntityType.KEY_VALUE_NODE, node_id=source_node.id)],
        org_id=source_node.graph.org_id,
    )
    assert not result.has_errors, result.errors
    PartialImportService(entity_registry).import_data(
        export_data=result.data, graph=target_graph, org_id=target_graph.org_id, user=user
    )
    return KeyValueNode.objects.get(graph=target_graph)


@pytest.mark.django_db
def test_paste_rejects_invalid_key(source_node, source_org, acting_user):
    KeyValueNode.objects.filter(pk=source_node.pk).update(
        entries=[{"key": "user-1", "value": "variables.a"}]
    )
    target_graph = Graph.objects.create(name="Paste target", org=source_org)

    with pytest.raises(serializers.ValidationError, match="'key' must use only letters"):
        _paste(source_node, target_graph, acting_user(R))

    assert not KeyValueNode.objects.filter(graph=target_graph).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("bits, mode, bound", BINDING_CASES)
def test_paste_binds_table_only_with_mode_permissions(
    source_node, source_org, acting_user, bits, mode, bound
):
    _set_mode(source_node, mode)
    target_graph = Graph.objects.create(name="Paste target", org=source_org)

    pasted = _paste(source_node, target_graph, acting_user(bits))

    assert pasted.mode == mode
    expected = source_node.key_value_table_id if bound else None
    assert pasted.key_value_table_id == expected


@pytest.mark.django_db
@pytest.mark.parametrize("bits, mode, bound", BINDING_CASES)
def test_cross_org_paste_binds_target_org_table_only_with_mode_permissions(
    source_node, target_org, acting_user, bits, mode, bound
):
    _set_mode(source_node, mode)
    target_table = KeyValueTable.objects.create(org=target_org, name="customers")
    target_graph = Graph.objects.create(name="Paste target", org=target_org)

    pasted = _paste(source_node, target_graph, acting_user(bits))

    assert pasted.key_value_table_id == (target_table.id if bound else None)


@pytest.mark.django_db
@pytest.mark.parametrize("bits, mode, bound", BINDING_CASES)
def test_full_import_binds_table_only_with_mode_permissions(
    source_node, source_org, acting_user, bits, mode, bound
):
    _set_mode(source_node, mode)
    graph_strategy = entity_registry.get_strategy(EntityType.GRAPH)
    exported_graph = graph_strategy.export_entity(source_node.graph)

    new_graph = graph_strategy.create_entity(
        dict(exported_graph), IDMapper(), org_id=source_org.id, user=acting_user(bits)
    )

    expected = source_node.key_value_table_id if bound else None
    assert new_graph.key_value_node_list.get().key_value_table_id == expected


@pytest.mark.django_db
@pytest.mark.parametrize("bits, mode, bound", BINDING_CASES)
def test_graph_copy_binds_table_only_with_mode_permissions(
    source_node, acting_user, bits, mode, bound
):
    _set_mode(source_node, mode)

    new_graph = GraphCopyService().copy(source_node.graph, name="Flow copy", user=acting_user(bits))

    copied = _copied_node(new_graph)
    assert copied.mode == mode
    assert copied.key_value_table_id == (source_node.key_value_table_id if bound else None)


@pytest.mark.django_db
@pytest.mark.parametrize("bits, mode, bound", BINDING_CASES)
def test_copy_endpoint_passes_the_acting_user(
    source_node, source_org, acting_user, bits, mode, bound
):
    _set_mode(source_node, mode)
    client = APIClient()
    client.force_authenticate(user=acting_user(bits))
    client.credentials(HTTP_X_ORGANIZATION_ID=str(source_org.id))

    response = client.post(reverse("graphs-copy", args=[source_node.graph_id]), {}, format="json")

    assert response.status_code == status.HTTP_201_CREATED, response.content
    copied = KeyValueNode.objects.get(graph_id=response.data["id"])
    assert copied.key_value_table_id == (source_node.key_value_table_id if bound else None)


@pytest.mark.django_db
@pytest.mark.parametrize("bits, mode, bound", BINDING_CASES)
def test_version_restore_binds_table_only_with_mode_permissions(
    source_node, acting_user, bits, mode, bound
):
    _set_mode(source_node, mode)
    graph = source_node.graph
    versioning = GraphVersioningService()
    version = versioning.save_version(graph=graph, name="v1")
    graph.refresh_from_db()

    versioning.restore_version(
        version, expected_save_version=graph.save_version, user=acting_user(bits)
    )

    expected = source_node.key_value_table_id if bound else None
    assert graph.key_value_node_list.get().key_value_table_id == expected


@pytest.mark.django_db
@pytest.mark.parametrize("bits, mode, bound", BINDING_CASES)
def test_create_graph_from_version_binds_table_only_with_mode_permissions(
    source_node, acting_user, bits, mode, bound
):
    _set_mode(source_node, mode)
    versioning = GraphVersioningService()
    version = versioning.save_version(graph=source_node.graph, name="v1")

    result = versioning.create_graph_from_version(version, user=acting_user(bits))

    new_graph = Graph.objects.get(pk=result["graph_id"])
    expected = source_node.key_value_table_id if bound else None
    assert new_graph.key_value_node_list.get().key_value_table_id == expected


@pytest.mark.django_db
@pytest.mark.parametrize("bits, mode, bound", BINDING_CASES)
def test_import_replace_recreates_node_and_binds_table_only_with_mode_permissions(
    source_node, source_org, acting_user, bits, mode, bound
):
    _set_mode(source_node, mode)
    graph = source_node.graph
    export_data = ExportService(entity_registry).export_entities(EntityType.GRAPH, [graph.id])
    # Unbound after the export, so only the replace can bring the table back.
    KeyValueNode.objects.filter(pk=source_node.pk).update(key_value_table=None)
    client = APIClient()
    client.force_authenticate(user=acting_user(bits))
    client.credentials(HTTP_X_ORGANIZATION_ID=str(source_org.id))

    response = client.post(
        reverse("graphs-import-entity"),
        {
            "file": data_to_json_file(data=export_data, filename="flow.json"),
            "preserve_uuids": True,
            "replace_existing": True,
        },
        format="multipart",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert Graph.objects.filter(org=source_org).count() == 1
    recreated = graph.key_value_node_list.get()
    assert recreated.pk != source_node.pk
    assert not KeyValueNode.all_objects.filter(pk=source_node.pk).exists()
    assert recreated.mode == mode
    table = KeyValueTable.objects.get(org=source_org, name="Customers")
    assert recreated.key_value_table_id == (table.id if bound else None)
    assert list(table.nodes.values_list("pk", flat=True)) == ([recreated.pk] if bound else [])


def _preview_node(version) -> dict:
    (node,) = GraphVersioningService().preview_version(version)["snapshot"]["nodes"]
    return node


def _point_snapshot_at(version, table: KeyValueTable) -> None:
    (node,) = version.snapshot["nodes"]
    node["key_value_table"], node["key_value_table_name"] = table.id, table.name
    version.save(update_fields=["snapshot"])


@pytest.mark.django_db
def test_version_preview_shows_the_existing_table(source_node):
    version = GraphVersioningService().save_version(graph=source_node.graph, name="v1")

    node = _preview_node(version)

    assert node["node_type"] == "KeyValueNode"
    assert node["key_value_table"] == source_node.key_value_table_id
    assert node["key_value_table_name"] == "Customers"
    assert node["mode"] == "read"
    assert node["entries"] == [{"key": "k", "value": "variables.a"}]


@pytest.mark.django_db
def test_version_preview_nulls_a_renamed_table_and_keeps_the_stored_name(source_node):
    version = GraphVersioningService().save_version(graph=source_node.graph, name="v1")
    KeyValueTable.objects.filter(pk=source_node.key_value_table_id).update(name="Clients")

    node = _preview_node(version)

    assert node["key_value_table"] is None
    assert node["key_value_table_name"] == "Customers"


@pytest.mark.django_db
def test_version_preview_nulls_a_deleted_table_and_keeps_the_stored_name(source_node):
    version = GraphVersioningService().save_version(graph=source_node.graph, name="v1")
    KeyValueTableService().delete_table(source_node.key_value_table)

    node = _preview_node(version)

    assert node["key_value_table"] is None
    assert node["key_value_table_name"] == "Customers"


@pytest.mark.django_db
def test_version_preview_binds_a_recreated_same_named_table(source_node, source_org):
    version = GraphVersioningService().save_version(graph=source_node.graph, name="v1")
    KeyValueTableService().delete_table(source_node.key_value_table)
    recreated = KeyValueTable.objects.create(org=source_org, name="customers")

    assert _preview_node(version)["key_value_table"] == recreated.id


@pytest.mark.django_db
def test_version_preview_never_returns_another_orgs_table(source_node, target_org):
    version = GraphVersioningService().save_version(graph=source_node.graph, name="v1")
    _point_snapshot_at(version, KeyValueTable.objects.create(org=target_org, name="Foreign"))

    assert _preview_node(version)["key_value_table"] is None


@pytest.mark.django_db
def test_version_preview_binds_own_orgs_table_for_a_foreign_id_with_a_known_name(
    source_node, target_org
):
    version = GraphVersioningService().save_version(graph=source_node.graph, name="v1")
    _point_snapshot_at(version, KeyValueTable.objects.create(org=target_org, name="Customers"))

    assert _preview_node(version)["key_value_table"] == source_node.key_value_table_id


@pytest.mark.django_db
@pytest.mark.parametrize("bits, bound", [(0, False), (R, True)], ids=["none", "R"])
def test_version_preview_binds_the_table_only_with_the_viewers_mode_permissions(
    source_node, source_org, acting_user, bits, bound
):
    version = GraphVersioningService().save_version(graph=source_node.graph, name="v1")
    client = APIClient()
    client.force_authenticate(user=acting_user(bits))
    client.credentials(HTTP_X_ORGANIZATION_ID=str(source_org.id))

    response = client.get(reverse("graph-versions-preview", args=[version.id]))

    assert response.status_code == status.HTTP_200_OK, response.content
    (node,) = response.data["snapshot"]["nodes"]
    assert node["key_value_table"] == (source_node.key_value_table_id if bound else None)


@pytest.mark.django_db
@pytest.mark.parametrize("mode", ["read", "write", "delete"])
def test_system_principal_binds_table(source_node, source_org, mode):
    table = source_node.key_value_table

    resolved = KeyValueTableService().resolve_reference(
        source_org.id, table.id, table.name, mode=mode, user=SystemServicePrincipal()
    )

    assert resolved == table
