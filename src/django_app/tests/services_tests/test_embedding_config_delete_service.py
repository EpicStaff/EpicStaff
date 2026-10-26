"""Service-level tests for EmbeddingConfigDeleteService."""

import pytest

from tables.models import EmbeddingConfig
from tables.models.knowledge_models.collection_models import (
    BaseRagType,
    SourceCollection,
)
from tables.models.knowledge_models.graphrag_models import GraphRag
from tables.models.knowledge_models.naive_rag_models import NaiveRag
from rbac.models import Organization
from rbac.models.enums import Permission, ResourceType
from tables.services.delete_services import EmbeddingConfigDeleteService
from rbac.access.effective import EffectivePermissions


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="Org A")


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="Org B")


def _config(org, name="cfg"):
    return EmbeddingConfig.objects.create(org=org, custom_name=name)


def _can_read_everything():
    return EffectivePermissions(
        is_superadmin=False,
        role=None,
        by_resource={ResourceType.KNOWLEDGE_SOURCES.value: int(Permission.READ)},
    )


def _can_read_nothing():
    return EffectivePermissions(is_superadmin=False, role=None, by_resource={})


def _bucket(result, config_id, resource_type):
    return next(
        bucket
        for bucket in result.usage[config_id].buckets
        if bucket.resource_type == resource_type.value
    )


@pytest.mark.django_db
def test_collection_with_both_rag_kinds_on_one_embedder_is_one_collection(org_a):
    """GraphRag and NaiveRag rows for one collection are one reference, not two."""
    config = _config(org_a)
    collection = SourceCollection.objects.create(org=org_a, collection_name="Docs")
    graph_rag_type = BaseRagType.objects.create(
        source_collection=collection, rag_type=BaseRagType.RagType.GRAPH
    )
    naive_rag_type = BaseRagType.objects.create(
        source_collection=collection, rag_type=BaseRagType.RagType.NAIVE
    )
    GraphRag.objects.create(base_rag_type=graph_rag_type, embedder=config)
    NaiveRag.objects.create(base_rag_type=naive_rag_type, embedder=config)

    result = EmbeddingConfigDeleteService(
        org_id=org_a.id, permissions=_can_read_everything(), user=None
    ).preview([config.id])

    knowledge = _bucket(result, config.id, ResourceType.KNOWLEDGE_SOURCES)
    assert knowledge.visible_count == 1
    assert knowledge.visible_refs[0].id == collection.collection_id


@pytest.mark.django_db
def test_unreferenced_config_is_deleted(org_a):
    config = _config(org_a)

    result = EmbeddingConfigDeleteService(
        org_id=org_a.id, permissions=_can_read_everything(), user=None
    ).delete([config.id])

    assert result.deleted_ids == [config.id]
    assert not EmbeddingConfig.objects.filter(id=config.id).exists()


@pytest.mark.django_db
def test_another_orgs_references_are_not_usage(org_a, org_b):
    """Both RAG sources filter the referencing row by org.

    Each source lives in org B and points at org A's config; neither may reach
    org A's preview or block its delete.
    """
    config = _config(org_a)
    for rag_model, rag_kind in (
        (GraphRag, BaseRagType.RagType.GRAPH),
        (NaiveRag, BaseRagType.RagType.NAIVE),
    ):
        collection = SourceCollection.objects.create(
            org=org_b, collection_name=f"foreign-{rag_kind}"
        )
        rag_type = BaseRagType.objects.create(
            source_collection=collection, rag_type=rag_kind
        )
        rag_model.objects.create(base_rag_type=rag_type, embedder=config)

    preview = EmbeddingConfigDeleteService(
        org_id=org_a.id, permissions=_can_read_everything(), user=None
    ).preview([config.id])
    assert [
        (bucket.resource_type, bucket.total_count)
        for bucket in preview.usage[config.id].buckets
    ] == [(ResourceType.KNOWLEDGE_SOURCES.value, 0)]

    result = EmbeddingConfigDeleteService(
        org_id=org_a.id, permissions=_can_read_nothing(), user=None
    ).delete([config.id])
    assert result.deleted_ids == [config.id]
