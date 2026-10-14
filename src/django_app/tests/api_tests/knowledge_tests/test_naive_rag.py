"""The naive-RAG endpoints: one per collection, plus its per-document chunking configs.

Configs are created by POST .../document-configs/initialize/ (and once when the RAG is
created); a GET never creates them. A config id is only ever honoured under the RAG it
belongs to. Cross-org access is covered in test_org_scoping_naive_rag.py.
"""

import pytest
from django.urls import reverse
from rest_framework import status

from tables.models import EmbeddingConfig, EmbeddingModel
from tables.models.knowledge_models import (
    BaseRagType,
    DocumentContent,
    DocumentMetadata,
    NaiveRag,
    NaiveRagDocumentConfig,
    SourceCollection,
)

pytestmark = pytest.mark.django_db

MISSING = 99999


@pytest.fixture
def initialized_configs(auth_client, naive_rag, multiple_documents):
    response = auth_client.post(reverse("naive-rag-initialize-configs", args=[naive_rag.naive_rag_id]))
    assert response.status_code == status.HTTP_201_CREATED
    return list(NaiveRagDocumentConfig.objects.filter(naive_rag=naive_rag).order_by("pk"))


@pytest.fixture
def foreign_config(default_org, test_embedding_config):
    """A config of another RAG in the same org: never reachable through ours."""
    collection = SourceCollection.objects.create(collection_name="Another Collection", org=default_org)
    rag = NaiveRag.objects.create(
        base_rag_type=BaseRagType.objects.create(source_collection=collection, rag_type=BaseRagType.RagType.NAIVE),
        embedder=test_embedding_config,
        rag_status=NaiveRag.NaiveRagStatus.NEW,
    )
    document = DocumentMetadata.objects.create(
        source_collection=collection,
        document_content=DocumentContent.objects.create(content=b"Another doc content"),
        file_name="another_doc.pdf",
        file_type="pdf",
        file_size=1024,
    )
    return NaiveRagDocumentConfig.objects.get_or_create(
        naive_rag=rag, document=document,
        defaults={"chunk_strategy": "token", "chunk_size": 1000, "chunk_overlap": 150},
    )[0]


def _config_url(naive_rag, config_id):
    return reverse("document-config-detail", args=[naive_rag.naive_rag_id, config_id])


# --- the RAG itself ---------------------------------------------------------


def test_posting_an_embedder_creates_then_switches_the_collections_rag(
    auth_client, source_collection, test_embedding_config, default_org
):
    url = reverse("naive-rag-collection", args=[source_collection.collection_id])

    created = auth_client.post(url, {"embedder_id": test_embedding_config.pk}, format="json")

    assert created.status_code == status.HTTP_200_OK
    assert created.json()["naive_rag"]["embedder"] == test_embedding_config.pk
    rag = NaiveRag.objects.get(base_rag_type__source_collection=source_collection)
    other_embedder = EmbeddingConfig.objects.create(
        custom_name="New Embedder",
        model=EmbeddingModel.objects.create(
            name="text-embedding-ada-002", embedding_provider=test_embedding_config.model.embedding_provider
        ),
        task_type="retrieval_document",
        org=default_org,
    )

    switched = auth_client.post(url, {"embedder_id": other_embedder.pk}, format="json")

    assert switched.status_code == status.HTTP_200_OK
    rag.refresh_from_db()
    assert rag.embedder == other_embedder
    assert NaiveRag.objects.filter(base_rag_type__source_collection=source_collection).count() == 1


@pytest.mark.parametrize("missing", ["collection", "embedder"])
def test_creating_a_rag_for_something_missing_is_404(auth_client, source_collection, test_embedding_config, missing):
    collection_id = MISSING if missing == "collection" else source_collection.collection_id
    embedder_id = MISSING if missing == "embedder" else test_embedding_config.pk

    response = auth_client.post(
        reverse("naive-rag-collection", args=[collection_id]), {"embedder_id": embedder_id}, format="json"
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert not NaiveRag.objects.exists()


def test_the_rag_is_read_by_collection_and_by_id(auth_client, source_collection, empty_collection, naive_rag):
    by_collection = auth_client.get(reverse("naive-rag-collection", args=[source_collection.collection_id]))
    detail = auth_client.get(reverse("naive-rag-detail", args=[naive_rag.naive_rag_id]))
    none_yet = auth_client.get(reverse("naive-rag-collection", args=[empty_collection.collection_id]))

    assert by_collection.status_code == detail.status_code == status.HTTP_200_OK
    assert by_collection.json()["naive_rag_id"] == detail.json()["naive_rag_id"] == naive_rag.naive_rag_id
    assert none_yet.status_code == status.HTTP_404_NOT_FOUND


def test_deleting_the_rag_removes_its_base_type(auth_client, naive_rag):
    base_rag_id = naive_rag.base_rag_type.rag_type_id

    response = auth_client.delete(reverse("naive-rag-detail", args=[naive_rag.naive_rag_id]))

    assert response.status_code == status.HTTP_200_OK
    assert not NaiveRag.objects.filter(pk=naive_rag.pk).exists()
    assert not BaseRagType.objects.filter(rag_type_id=base_rag_id).exists()


# --- document configs -------------------------------------------------------


def test_initialize_creates_default_configs_only_for_documents_without_one(
    auth_client, naive_rag, multiple_documents
):
    url = reverse("naive-rag-initialize-configs", args=[naive_rag.naive_rag_id])
    NaiveRagDocumentConfig.objects.create(
        naive_rag=naive_rag, document=multiple_documents[0], chunk_strategy="character", chunk_size=500, chunk_overlap=50
    )

    first = auth_client.post(url)
    again = auth_client.post(url)

    assert first.status_code == status.HTTP_201_CREATED
    assert again.status_code == status.HTTP_200_OK
    configs = {config.document_id: config for config in NaiveRagDocumentConfig.objects.filter(naive_rag=naive_rag)}
    assert set(configs) == {document.document_id for document in multiple_documents}
    assert (configs[multiple_documents[0].document_id].chunk_strategy, configs[multiple_documents[0].document_id].chunk_size) == ("character", 500)
    assert {(c.chunk_strategy, c.chunk_size, c.chunk_overlap) for c in list(configs.values())[1:]} == {("token", 1000, 150)}
    listed = auth_client.get(reverse("document-config-list", args=[naive_rag.naive_rag_id])).json()
    assert listed["total_configs"] == len(listed["configs"]) == 3


def test_a_get_never_creates_configs(auth_client, naive_rag, multiple_documents):
    auth_client.get(reverse("naive-rag-detail", args=[naive_rag.naive_rag_id]))
    listed = auth_client.get(reverse("document-config-list", args=[naive_rag.naive_rag_id]))

    assert listed.status_code == status.HTTP_200_OK
    assert listed.json()["total_configs"] == 0


@pytest.mark.parametrize(
    ("body", "expected_status", "expected"),
    [
        ({"chunk_size": 2000, "chunk_overlap": 300, "chunk_strategy": "character", "additional_params": {"custom": "value"}},
         status.HTTP_200_OK, (2000, 300, "character")),
        ({"chunk_size": 1500}, status.HTTP_200_OK, (1500, 150, "token")),
        ({"chunk_size": 10}, status.HTTP_400_BAD_REQUEST, (1000, 150, "token")),
        ({"chunk_size": 100, "chunk_overlap": 150}, status.HTTP_400_BAD_REQUEST, (1000, 150, "token")),
        ({}, status.HTTP_400_BAD_REQUEST, (1000, 150, "token")),
    ],
    ids=["all-fields", "partial", "size-below-minimum", "overlap-over-size", "nothing-to-update"],
)
def test_updating_a_config(auth_client, naive_rag, naive_rag_document_config, body, expected_status, expected):
    response = auth_client.put(_config_url(naive_rag, naive_rag_document_config.pk), body, format="json")

    assert response.status_code == expected_status
    naive_rag_document_config.refresh_from_db()
    assert (
        naive_rag_document_config.chunk_size,
        naive_rag_document_config.chunk_overlap,
        naive_rag_document_config.chunk_strategy,
    ) == expected


def test_a_config_is_read_and_deleted_by_id(auth_client, naive_rag, naive_rag_document_config):
    url = _config_url(naive_rag, naive_rag_document_config.pk)

    read = auth_client.get(url)
    deleted = auth_client.delete(url)

    assert read.status_code == status.HTTP_200_OK
    assert (read.json()["naive_rag_document_id"], read.json()["chunk_size"]) == (naive_rag_document_config.pk, 1000)
    assert deleted.status_code == status.HTTP_200_OK
    assert deleted.json()["config_id"] == naive_rag_document_config.pk
    assert not NaiveRagDocumentConfig.objects.filter(pk=naive_rag_document_config.pk).exists()


@pytest.mark.parametrize("method", ["get", "put", "delete"])
@pytest.mark.parametrize("target", ["another-rags-config", "missing-config"])
def test_a_config_outside_this_rag_is_404_and_untouched(auth_client, naive_rag, foreign_config, method, target):
    config_id = foreign_config.pk if target == "another-rags-config" else MISSING

    response = getattr(auth_client, method)(_config_url(naive_rag, config_id), {"chunk_size": 3000}, format="json")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    foreign_config.refresh_from_db()
    assert foreign_config.chunk_size == 1000


def _bulk_update(auth_client, naive_rag, items):
    return auth_client.put(reverse("document-config-bulk-update", args=[naive_rag.naive_rag_id]), items, format="json")


def test_bulk_update_changes_only_the_listed_configs(auth_client, naive_rag, initialized_configs):
    listed, untouched = initialized_configs[:2], initialized_configs[2]

    response = _bulk_update(
        auth_client, naive_rag, [{"id": config.pk, "chunk_size": 2500, "chunk_overlap": 400} for config in listed]
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["updated_count"] == 2
    assert {(c.chunk_size, c.chunk_overlap) for c in NaiveRagDocumentConfig.objects.filter(pk__in=[c.pk for c in listed])} == {(2500, 400)}
    untouched.refresh_from_db()
    assert untouched.chunk_size == 1000


def test_bulk_update_applies_valid_items_and_reports_the_invalid_ones_with_207(
    auth_client, naive_rag, initialized_configs
):
    valid, invalid = initialized_configs[:2]

    response = _bulk_update(
        auth_client, naive_rag, [{"id": valid.pk, "chunk_size": 2500}, {"id": invalid.pk, "chunk_size": 100, "chunk_overlap": 150}]
    )

    assert response.status_code == status.HTTP_207_MULTI_STATUS
    assert (response.json()["updated_count"], response.json()["failed_count"]) == (1, 1)
    valid.refresh_from_db()
    invalid.refresh_from_db()
    assert (valid.chunk_size, invalid.chunk_size) == (2500, 1000)


@pytest.mark.parametrize(
    ("items", "expected_status"),
    [
        ([{"id": "own", "chunk_size": 5}], status.HTTP_400_BAD_REQUEST),
        ([{"id": "own"}], status.HTTP_400_BAD_REQUEST),
        ([{"id": "own", "chunk_size": 3000}, {"id": MISSING, "chunk_size": 3000}], status.HTTP_404_NOT_FOUND),
        ([{"id": "foreign", "chunk_size": 3000}], status.HTTP_404_NOT_FOUND),
    ],
    ids=["invalid-size", "nothing-to-update", "unknown-id", "another-rags-config"],
)
def test_a_rejected_bulk_update_changes_nothing(
    auth_client, naive_rag, naive_rag_document_config, foreign_config, items, expected_status
):
    ids = {"own": naive_rag_document_config.pk, "foreign": foreign_config.pk}
    items = [{**item, "id": ids.get(item["id"], item["id"])} for item in items]

    response = _bulk_update(auth_client, naive_rag, items)

    assert response.status_code == expected_status
    for config in (naive_rag_document_config, foreign_config):
        config.refresh_from_db()
        assert config.chunk_size == 1000


def test_bulk_delete_removes_only_this_rags_listed_configs(auth_client, naive_rag, initialized_configs, foreign_config):
    listed = [config.pk for config in initialized_configs[:2]]

    response = auth_client.post(
        reverse("document-config-bulk-delete", args=[naive_rag.naive_rag_id]),
        {"config_ids": [*listed, foreign_config.pk, MISSING]},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["deleted_count"] == 2
    assert set(response.json()["deleted_config_ids"]) == set(listed)
    remaining = set(NaiveRagDocumentConfig.objects.values_list("pk", flat=True))
    assert remaining == {initialized_configs[2].pk, foreign_config.pk}


def test_bulk_delete_without_ids_is_400(auth_client, naive_rag):
    response = auth_client.post(
        reverse("document-config-bulk-delete", args=[naive_rag.naive_rag_id]), {"config_ids": []}, format="json"
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
