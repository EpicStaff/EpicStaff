"""The stable per-node uuid: set automatically, unique per graph among active rows,
and never part of the content hash."""

from uuid import UUID, uuid4

import pytest
from django.db import IntegrityError, connection, transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.validators import UniqueTogetherValidator

from tables.models import Graph
from tables.models.base_models import BaseGlobalNode, NodeIdentityMixin
from tables.models.graph_models import EndNode, GraphNote, StartNode
from tests.graph_node_builders import (
    MULTIPLE_PER_GRAPH_NODE_MODELS,
    NODE_MODELS,
    create_every_node,
    create_node,
    node_fields,
)

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("mock_telegram_service")]


def _constraint_name(model) -> str:
    return f"tables_{model._meta.model_name}_graph_uuid_unique"


def _content_change(model) -> dict:
    if model is StartNode:
        return {"variables": {"changed": True}}
    if model is EndNode:
        return {"output_map": {"changed": "variables"}}
    if model is GraphNote:
        return {"content": "changed note"}
    return {"node_name": "changed name"}


@pytest.fixture
def other_graph(default_org):
    return Graph.objects.create(name="other", org=default_org)


def test_uuid_is_on_exactly_the_exported_node_models():
    models_with_uuid = {
        model
        for model in BaseGlobalNode.get_all_node_models()
        if any(field.name == "uuid" for field in model._meta.fields)
    }
    node_models = NodeIdentityMixin.get_node_models()

    assert models_with_uuid == set(NODE_MODELS)
    assert sorted(node_models, key=str) == sorted(NODE_MODELS, key=str)


def test_active_node_uuids_reads_every_node_table_of_the_graph_only(graph, other_graph):
    nodes = create_every_node(graph)
    create_every_node(other_graph)

    assert NodeIdentityMixin.active_node_uuids(graph) == {node.uuid for node in nodes.values()}


def test_active_node_uuids_leaves_out_soft_deleted_excluded_and_unasked_nodes(graph):
    kept, excluded, soft_deleted, unasked = (create_node(GraphNote, graph) for _ in range(4))
    GraphNote.all_objects.filter(pk=soft_deleted.pk).update(
        is_soft_deleted=True, soft_deleted_at=timezone.now()
    )

    active_uuids = NodeIdentityMixin.active_node_uuids(
        graph,
        among={kept.uuid, excluded.uuid, soft_deleted.uuid},
        excluded_ids_by_model={GraphNote: [excluded.id]},
    )

    assert active_uuids == {kept.uuid}
    assert unasked.uuid in NodeIdentityMixin.active_node_uuids(graph)


def test_raw_insert_without_uuid_gets_one_from_the_database(graph):
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {GraphNote._meta.db_table} "
            "(graph_id, content, metadata, created_at, updated_at, is_soft_deleted) "
            "VALUES (%s, 'raw note', '{}', now(), now(), false) RETURNING id, uuid",
            [graph.id],
        )
        note_id, inserted_uuid = cursor.fetchone()

    assert inserted_uuid is not None
    assert GraphNote.objects.get(pk=note_id).uuid == inserted_uuid


@pytest.mark.parametrize("model", NODE_MODELS, ids=lambda model: model.__name__)
class TestEveryNodeModel:
    def test_create_sets_a_stored_uuid(self, model, graph, other_graph):
        node = create_node(model, graph)
        other_node = create_node(model, other_graph)

        stored_uuid = model._base_manager.values_list("uuid", flat=True).get(pk=node.pk)
        assert isinstance(node.uuid, UUID)
        assert stored_uuid == node.uuid
        assert other_node.uuid != node.uuid

    def test_database_has_conditional_per_graph_unique_index(self, model):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT indexdef FROM pg_indexes WHERE tablename = %s AND indexname = %s",
                [model._meta.db_table, _constraint_name(model)],
            )
            (index_definition,) = cursor.fetchone()

        assert index_definition.startswith("CREATE UNIQUE INDEX")
        assert "(graph_id, uuid)" in index_definition
        assert index_definition.endswith("WHERE (NOT is_soft_deleted)")

    def test_model_serializer_gets_no_uuid_uniqueness_validator(self, model):
        serializer_class = type(
            f"{model.__name__}AllFieldsSerializer",
            (serializers.ModelSerializer,),
            {"Meta": type("Meta", (), {"model": model, "fields": "__all__"})},
        )

        validated_field_sets = [
            set(validator.fields)
            for validator in serializer_class().get_validators()
            if isinstance(validator, UniqueTogetherValidator)
        ]

        assert not any("uuid" in fields for fields in validated_field_sets)

    def test_same_uuid_in_another_graph_is_allowed(self, model, graph, other_graph):
        node = create_node(model, graph)

        other_node = create_node(model, other_graph, uuid=node.uuid)

        assert other_node.uuid == node.uuid

    def test_changing_uuid_keeps_content_hash(self, model, graph):
        node = create_node(model, graph)
        hash_before = node.content_hash

        model._base_manager.filter(pk=node.pk).update(uuid=uuid4())
        reloaded = model._base_manager.get(pk=node.pk)

        assert reloaded.uuid != node.uuid
        assert reloaded.content_hash == hash_before

    def test_changing_content_still_changes_content_hash(self, model, graph):
        node = create_node(model, graph)
        hash_before = node.content_hash

        model._base_manager.filter(pk=node.pk).update(**_content_change(model))
        reloaded = model._base_manager.get(pk=node.pk)

        assert reloaded.content_hash != hash_before


@pytest.mark.parametrize("model", MULTIPLE_PER_GRAPH_NODE_MODELS, ids=lambda model: model.__name__)
class TestUniquenessInOneGraph:
    def test_active_duplicate_raises(self, model, graph):
        node = create_node(model, graph)

        with pytest.raises(IntegrityError, match=_constraint_name(model)):
            with transaction.atomic():
                create_node(model, graph, uuid=node.uuid)

    def test_soft_deleted_duplicate_is_allowed(self, model, graph):
        node = create_node(model, graph)
        model._base_manager.filter(pk=node.pk).update(
            is_soft_deleted=True, soft_deleted_at=timezone.now()
        )

        replacement = create_node(model, graph, uuid=node.uuid)

        assert set(model._base_manager.filter(graph=graph).values_list("uuid", flat=True)) == {
            node.uuid
        }
        assert replacement.pk != node.pk

    def test_bulk_create_sets_distinct_uuids(self, model, graph):
        created = model.objects.bulk_create(
            [model(graph=graph, **node_fields(model)) for _ in range(3)]
        )

        stored_uuids = set(model._base_manager.filter(graph=graph).values_list("uuid", flat=True))
        assert len(stored_uuids) == 3
        assert stored_uuids == {node.uuid for node in created}
