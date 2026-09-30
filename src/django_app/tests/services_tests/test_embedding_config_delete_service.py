"""Service-level tests for EmbeddingConfigDeleteService."""

import pytest

from tables.models import Crew, EmbeddingConfig
from tables.models.knowledge_models.collection_models import (
    BaseRagType,
    SourceCollection,
)
from tables.models.knowledge_models.graphrag_models import GraphRag
from tables.models.knowledge_models.naive_rag_models import NaiveRag
from tables.models.rbac_models import Organization
from tables.models.rbac_models.rbac_enums import Permission, ResourceType
from tables.services.delete_services import EmbeddingConfigDeleteService
from tables.services.delete_services.usage import RefKind
from tables.services.rbac.effective_permissions import EffectivePermissions


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
        by_resource={
            ResourceType.PROJECTS.value: int(Permission.READ),
            ResourceType.KNOWLEDGE_SOURCES.value: int(Permission.READ),
        },
    )


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

    result = EmbeddingConfigDeleteService().bulk_delete(
        [config.id], org_a.id, _can_read_everything(), dry_run=True
    )

    knowledge = _bucket(result, config.id, ResourceType.KNOWLEDGE_SOURCES)
    assert knowledge.visible_count == 1
    assert knowledge.visible_refs[0].kind == RefKind.COLLECTION


@pytest.mark.django_db
def test_deprecated_crew_still_counts_as_usage(org_a):
    """Legacy `tables.Crew` counts: old flows with a CrewNode still execute."""
    config = _config(org_a)
    Crew.objects.create(org=org_a, name="crew", embedding_config=config)

    result = EmbeddingConfigDeleteService().bulk_delete(
        [config.id], org_a.id, _can_read_everything(), dry_run=True
    )

    projects = _bucket(result, config.id, ResourceType.PROJECTS)
    assert [ref.kind for ref in projects.visible_refs] == [RefKind.CREW]


@pytest.mark.django_db
def test_unreferenced_config_is_deleted(org_a):
    config = _config(org_a)

    result = EmbeddingConfigDeleteService().bulk_delete(
        [config.id], org_a.id, _can_read_everything()
    )

    assert result.deleted_ids == [config.id]
    assert not EmbeddingConfig.objects.filter(id=config.id).exists()


@pytest.mark.django_db
def test_another_orgs_references_are_not_usage(org_a, org_b):
    """The crew and both RAG sources filter the referencing row by org.

    Each source lives in org B and points at org A's config; none of them may
    reach org A's preview or block its delete.
    """
    config = _config(org_a)
    Crew.objects.create(org=org_b, name="foreign", embedding_config=config)
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

    preview = EmbeddingConfigDeleteService().bulk_delete(
        [config.id], org_a.id, _can_read_everything(), dry_run=True
    )
    assert [bucket.total_count for bucket in preview.usage[config.id].buckets] == [
        0,
        0,
    ]

    nobody = EffectivePermissions(is_superadmin=False, role=None, by_resource={})
    result = EmbeddingConfigDeleteService().bulk_delete([config.id], org_a.id, nobody)
    assert result.deleted_ids == [config.id]
