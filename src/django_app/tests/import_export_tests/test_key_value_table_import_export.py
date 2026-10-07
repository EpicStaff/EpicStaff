"""A flow export carries the key-value tables its Key-Value nodes use; an import binds them.

Source flows live in `beta`; imports land in `acme`. Table rows never travel.
"""

import json

import pytest
from django.urls import reverse
from rest_framework import serializers

from rbac.access.resolver import PermissionResolver
from rbac.models import OrganizationUser, Role
from rbac.models.enums import Permission, ResourceType
from rbac.models.role import RolePermission
from tables.import_export.constants import DEPENDENCY_ORDER, IMPORT_VERSION
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.registry import entity_registry
from tables.import_export.schemas import ImportSettings
from tables.import_export.services.export_service import ExportService
from tables.import_export.services.import_service import ImportService
from tables.models import Graph, KeyValueNode, KeyValueTable, KeyValueTableEntry
from tests.helpers import data_to_json_file
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


@pytest.fixture
def source_table(beta):
    table = KeyValueTable.objects.create(
        org=beta, name="Conversations", description="One entry per chat."
    )
    KeyValueTableEntry.objects.create(table=table, key="c_1", value={"secret": "beta data"})
    KeyValueTableEntry.objects.create(table=table, key="c_2", value=2)
    yield table


@pytest.fixture
def source_flow(beta, source_table):
    graph = Graph.objects.create(name="Chat", org=beta)
    KeyValueNode.objects.create(
        graph=graph,
        node_name="Load",
        key_value_table=source_table,
        mode="read",
        entries=[{"key": "{variables.conversation_id}", "value": "variables.conversation"}],
    )
    yield graph


@pytest.fixture
def exported(source_flow, beta):
    yield ExportService(entity_registry).export_entities(
        EntityType.GRAPH, [source_flow.id], org_id=beta.id
    )


def _import(data: dict, org, user, settings: ImportSettings | None = None) -> IDMapper:
    id_mapper, _ = ImportService(entity_registry).import_data(
        json.loads(json.dumps(data)),
        EntityType.GRAPH,
        settings=settings,
        org_id=org.id,
        user=user,
        effective_permissions=PermissionResolver().resolve(user=user, org_id=org.id),
    )
    return id_mapper


def _imported_node(org) -> KeyValueNode:
    return KeyValueNode.objects.get(graph__org=org)


@pytest.mark.django_db
def test_flow_export_carries_the_table_definition_and_never_its_entries(
    exported, source_table
):
    assert exported[EntityType.KEY_VALUE_TABLE] == [
        {"id": source_table.id, "name": "Conversations", "description": "One entry per chat."}
    ]
    assert "beta data" not in json.dumps(exported)
    [node] = [
        node
        for node in exported[EntityType.GRAPH][0]["nodes"]
        if node["node_type"] == "KeyValueNode"
    ]
    assert (node["key_value_table"], node["key_value_table_name"]) == (
        source_table.id,
        "Conversations",
    )


@pytest.mark.django_db
def test_flow_export_leaves_out_another_orgs_table_and_unbound_nodes(source_flow, beta, acme):
    foreign = KeyValueTable.objects.create(org=acme, name="Acme customers")
    KeyValueNode.objects.create(graph=source_flow, node_name="Foreign", key_value_table=foreign)
    KeyValueNode.objects.create(graph=source_flow, node_name="Unbound")

    data = ExportService(entity_registry).export_entities(
        EntityType.GRAPH, [source_flow.id], org_id=beta.id
    )

    assert [table["name"] for table in data[EntityType.KEY_VALUE_TABLE]] == ["Conversations"]


@pytest.mark.django_db
def test_import_into_a_clean_org_creates_the_table_and_binds_the_node(
    exported, source_table, acme, admin_acme
):
    id_mapper = _import(exported, acme, admin_acme)

    table = KeyValueTable.objects.get(org=acme)
    assert (table.name, table.description) == ("Conversations", "One entry per chat.")
    assert not table.entries.exists()
    assert id_mapper.get(EntityType.KEY_VALUE_TABLE, source_table.id) == table.id
    assert id_mapper.was_created(EntityType.KEY_VALUE_TABLE, source_table.id)
    assert _imported_node(acme).key_value_table_id == table.id


@pytest.mark.django_db
def test_import_reuses_the_importing_orgs_table_of_the_same_name_in_any_case(
    exported, source_table, acme, admin_acme
):
    own = KeyValueTable.objects.create(org=acme, name="CONVERSATIONS")

    id_mapper = _import(exported, acme, admin_acme)

    assert list(KeyValueTable.objects.filter(org=acme)) == [own]
    assert not id_mapper.was_created(EntityType.KEY_VALUE_TABLE, source_table.id)
    assert _imported_node(acme).key_value_table_id == own.id


@pytest.mark.django_db
def test_import_never_reuses_or_binds_another_orgs_table(
    exported, source_table, acme, admin_acme
):
    _import(exported, acme, admin_acme)

    node = _imported_node(acme)
    assert node.key_value_table_id != source_table.id
    assert node.key_value_table.org_id == acme.id
    assert KeyValueTable.objects.filter(org=source_table.org_id).count() == 1


@pytest.mark.django_db
def test_the_carried_table_wins_over_a_same_named_table_of_the_import(
    exported, source_table, acme, admin_acme
):
    """The node binds the table the file mapped, not whatever its stored name finds."""
    exported[EntityType.KEY_VALUE_TABLE][0]["name"] = "Chat log"
    own_conversations = KeyValueTable.objects.create(org=acme, name="Conversations")

    _import(exported, acme, admin_acme)

    carried = KeyValueTable.objects.get(org=acme, name="Chat log")
    assert _imported_node(acme).key_value_table_id == carried.id
    assert carried.pk != own_conversations.pk


@pytest.mark.django_db
@pytest.mark.parametrize("own_table", [True, False], ids=["org-has-table", "org-lacks-table"])
def test_a_file_without_the_entity_keeps_binding_by_name(
    exported, acme, admin_acme, own_table
):
    del exported[EntityType.KEY_VALUE_TABLE]
    own = KeyValueTable.objects.create(org=acme, name="conversations") if own_table else None

    _import(exported, acme, admin_acme)

    assert _imported_node(acme).key_value_table_id == (own.id if own else None)
    assert KeyValueTable.objects.filter(org=acme).count() == (1 if own_table else 0)


@pytest.mark.django_db
def test_a_mapped_table_is_still_bound_only_with_the_mode_permissions(
    exported, acme, django_user_model
):
    """Creating the table needs create; binding a read node to it also needs read."""
    role = Role.objects.create(name="Create-only tables", org=acme, is_built_in=False)
    RolePermission.objects.create(
        role=role, resource_type=ResourceType.FLOWS, permissions=int(Permission.CREATE)
    )
    RolePermission.objects.create(
        role=role,
        resource_type=ResourceType.KEY_VALUE_TABLES,
        permissions=int(Permission.CREATE),
    )
    user = django_user_model.objects.create_user(email="creator@acme.test", password="x")
    OrganizationUser.objects.create(user=user, org=acme, role=role)

    _import(exported, acme, user)

    assert KeyValueTable.objects.filter(org=acme).count() == 1
    assert _imported_node(acme).key_value_table_id is None


@pytest.fixture
def importer_without_table_create(django_user_model, acme):
    role = Role.objects.create(name="Flow importer", org=acme, is_built_in=False)
    RolePermission.objects.create(
        role=role,
        resource_type=ResourceType.FLOWS,
        permissions=int(Permission.CREATE | Permission.READ),
    )
    RolePermission.objects.create(
        role=role,
        resource_type=ResourceType.KEY_VALUE_TABLES,
        permissions=int(Permission.READ),
    )
    user = django_user_model.objects.create_user(email="importer@acme.test", password="x")
    OrganizationUser.objects.create(user=user, org=acme, role=role)
    yield user


@pytest.mark.django_db
def test_importer_without_key_value_tables_create_is_refused_and_nothing_is_created(
    exported, acme, importer_without_table_create, client_as
):
    client = client_as(importer_without_table_create)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

    response = client.post(
        reverse("graphs-import-entity"),
        {"file": data_to_json_file(data=exported, filename="flow.json")},
        format="multipart",
    )

    assert response.status_code == 403, response.content
    assert "key_value_tables" in json.dumps(response.json())
    assert not Graph.objects.filter(org=acme).exists()
    assert not KeyValueTable.objects.filter(org=acme).exists()


@pytest.mark.django_db
def test_importer_without_create_may_still_reuse_the_orgs_table(
    exported, acme, importer_without_table_create, client_as
):
    own = KeyValueTable.objects.create(org=acme, name="Conversations")
    client = client_as(importer_without_table_create)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

    response = client.post(
        reverse("graphs-import-entity"),
        {"file": data_to_json_file(data=exported, filename="flow.json")},
        format="multipart",
    )

    assert response.status_code == 200, response.content
    assert _imported_node(acme).key_value_table_id == own.id


@pytest.mark.django_db
def test_a_forced_create_refuses_a_name_the_org_already_has(exported, acme, admin_acme):
    KeyValueTable.objects.create(org=acme, name="conversations")

    with pytest.raises(serializers.ValidationError, match="already exists"):
        _import(
            exported,
            acme,
            admin_acme,
            ImportSettings(force_create_types=frozenset({EntityType.KEY_VALUE_TABLE})),
        )

    assert KeyValueTable.objects.filter(org=acme).count() == 1


def _create(org_id, **settings):
    strategy = entity_registry.get_strategy(EntityType.KEY_VALUE_TABLE)
    return strategy.create_entity(
        {"id": 7, "name": "Conversations", "description": "carried"},
        IDMapper(),
        org_id=org_id,
        **settings,
    )


@pytest.mark.django_db
def test_a_plain_import_that_loses_the_name_race_reuses_the_winner(acme):
    """Another request created the name after find_existing missed it."""
    winner = KeyValueTable.objects.create(org=acme, name="CONVERSATIONS")

    assert _create(acme.id) == winner
    assert KeyValueTable.objects.filter(org=acme).count() == 1


@pytest.mark.django_db
def test_a_forced_create_that_loses_the_name_race_is_refused(acme):
    KeyValueTable.objects.create(org=acme, name="conversations")

    with pytest.raises(serializers.ValidationError, match="already exists"):
        _create(acme.id, force_create_types=frozenset({EntityType.KEY_VALUE_TABLE}))

    assert KeyValueTable.objects.filter(org=acme).count() == 1


@pytest.mark.django_db
def test_create_needs_an_importing_org():
    with pytest.raises(serializers.ValidationError, match="only be imported into an organization"):
        _create(None)

    assert not KeyValueTable.objects.exists()


@pytest.mark.django_db
def test_find_existing_needs_an_org(source_table):
    strategy = entity_registry.get_strategy(EntityType.KEY_VALUE_TABLE)

    assert strategy.find_existing({"name": "Conversations"}, IDMapper(), org_id=None) is None
    assert (
        strategy.find_existing({"name": "conversations"}, IDMapper(), org_id=source_table.org_id)
        == source_table
    )


def test_tables_import_before_flows_and_the_format_version_is_unchanged():
    order = list(DEPENDENCY_ORDER)

    assert order.index(EntityType.WEBHOOK_TRIGGER) < order.index(EntityType.KEY_VALUE_TABLE)
    assert order.index(EntityType.KEY_VALUE_TABLE) < order.index(EntityType.GRAPH)
    assert IMPORT_VERSION == 3
