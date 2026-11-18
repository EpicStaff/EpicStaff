"""RBAC: NaiveRag.create_or_update requires UPDATE when it upserts an existing RAG."""

import pytest
from django.urls import reverse
from rest_framework import status

from rbac.models.enums import Permission, ResourceType
from tables.models import EmbeddingConfig, EmbeddingModel, Provider, SourceCollection
from tables.models.knowledge_models import BaseRagType, NaiveRag
from tests.api_tests.role_grant_clients import FULL_CRUD, client_with_grants
from tests.rbac_cross_org_fixtures import beta  # noqa: F401

pytestmark = pytest.mark.django_db


# ---- Fixtures ----


@pytest.fixture
def openai_provider_fixture(db):
    """Get or create the OpenAI provider for test models."""
    provider, _ = Provider.objects.get_or_create(name="openai")
    return provider


@pytest.fixture
def embedding_model_1(openai_provider_fixture):
    model, _ = EmbeddingModel.objects.get_or_create(
        name="text-embedding-3-small-1",
        defaults={"embedding_provider": openai_provider_fixture},
    )
    return model


@pytest.fixture
def embedding_model_2(openai_provider_fixture):
    model, _ = EmbeddingModel.objects.get_or_create(
        name="text-embedding-3-small-2",
        defaults={"embedding_provider": openai_provider_fixture},
    )
    return model


@pytest.fixture
def embedder_config_1(embedding_model_1, default_org):
    config, _ = EmbeddingConfig.objects.get_or_create(
        custom_name="embedder-1",
        defaults={
            "model": embedding_model_1,
            "task_type": "retrieval_document",
            "org": default_org,
        },
    )
    return config


@pytest.fixture
def embedder_config_2(embedding_model_2, default_org):
    config, _ = EmbeddingConfig.objects.get_or_create(
        custom_name="embedder-2",
        defaults={
            "model": embedding_model_2,
            "task_type": "retrieval_document",
            "org": default_org,
        },
    )
    return config


@pytest.fixture
def test_collection(default_org):
    """Create a test source collection."""
    return SourceCollection.objects.create(collection_name="Test Collection", org=default_org)


@pytest.fixture
def empty_collection(default_org):
    """Create a collection with no existing RAG."""
    return SourceCollection.objects.create(collection_name="Empty Collection", org=default_org)


@pytest.fixture
def naive_rag_for_collection(test_collection, embedder_config_1):
    """Create a NaiveRag instance for the test collection."""
    base_rag = BaseRagType.objects.create(
        source_collection=test_collection,
        rag_type=BaseRagType.RagType.NAIVE,
    )
    return NaiveRag.objects.create(
        base_rag_type=base_rag,
        embedder=embedder_config_1,
        rag_status=NaiveRag.NaiveRagStatus.NEW,
    )


@pytest.fixture
def beta_collection(beta, openai_provider_fixture, embedding_model_1):
    """Create a collection with an existing NaiveRag in the beta org (cross-org test)."""
    beta_embedder = EmbeddingConfig.objects.create(
        custom_name="beta-embedder",
        model=embedding_model_1,
        task_type="retrieval_document",
        org=beta,
    )
    collection = SourceCollection.objects.create(collection_name="Beta Collection", org=beta)
    base_rag_type = BaseRagType.objects.create(
        source_collection=collection,
        rag_type=BaseRagType.RagType.NAIVE,
    )
    NaiveRag.objects.create(
        base_rag_type=base_rag_type,
        embedder=beta_embedder,
        rag_status=NaiveRag.NaiveRagStatus.NEW,
    )
    return collection


@pytest.fixture
def client_create_read_only(db, django_user_model, default_org):
    """Client with CREATE+READ but no UPDATE on Knowledge Sources."""
    return client_with_grants(
        org=default_org,
        django_user_model=django_user_model,
        email="create-read-only@example.com",
        resource_permissions={
            ResourceType.KNOWLEDGE_SOURCES.value: int(Permission.CREATE | Permission.READ),
        },
    )


@pytest.fixture
def client_full_crud(db, django_user_model, default_org):
    """Client with FULL_CRUD on Knowledge Sources."""
    return client_with_grants(
        org=default_org,
        django_user_model=django_user_model,
        email="full-crud@example.com",
        resource_permissions={
            ResourceType.KNOWLEDGE_SOURCES.value: FULL_CRUD,
        },
    )


@pytest.fixture
def client_update_read_only(db, django_user_model, default_org):
    """Client with UPDATE+READ but no CREATE on Knowledge Sources."""
    return client_with_grants(
        org=default_org,
        django_user_model=django_user_model,
        email="update-read-only@example.com",
        resource_permissions={
            ResourceType.KNOWLEDGE_SOURCES.value: int(Permission.UPDATE | Permission.READ),
        },
    )


# ---- Test Cases ----


def test_create_or_update_existing_rag_with_create_read_denied(
    client_create_read_only, naive_rag_for_collection, test_collection, embedder_config_2
):
    """CREATE+READ without UPDATE, existing RAG → 403; embedder_id unchanged."""
    url = reverse("naive-rag-collection", args=[test_collection.collection_id])
    original_embedder_id = naive_rag_for_collection.embedder_id

    response = client_create_read_only.post(
        url, {"embedder_id": embedder_config_2.pk}, format="json"
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN
    naive_rag_for_collection.refresh_from_db()
    assert naive_rag_for_collection.embedder_id == original_embedder_id


def test_create_or_update_no_existing_rag_with_create_read_succeeds(
    client_create_read_only, empty_collection, embedder_config_1
):
    """CREATE+READ, no existing RAG → 200, row created (create path unaffected)."""
    url = reverse("naive-rag-collection", args=[empty_collection.collection_id])

    response = client_create_read_only.post(
        url, {"embedder_id": embedder_config_1.pk}, format="json"
    )

    assert response.status_code == status.HTTP_200_OK  # create also returns 200, not 201
    naive_rag = NaiveRag.objects.get(base_rag_type__source_collection=empty_collection)
    assert naive_rag.embedder_id == embedder_config_1.pk


def test_create_or_update_existing_rag_with_full_crud_succeeds(
    client_full_crud, naive_rag_for_collection, test_collection, embedder_config_2
):
    """FULL_CRUD, existing RAG → 200, embedder_id actually changed."""
    url = reverse("naive-rag-collection", args=[test_collection.collection_id])

    response = client_full_crud.post(url, {"embedder_id": embedder_config_2.pk}, format="json")

    assert response.status_code == status.HTTP_200_OK
    naive_rag_for_collection.refresh_from_db()
    assert naive_rag_for_collection.embedder_id == embedder_config_2.pk


def test_create_or_update_foreign_org_collection_returns_404(
    client_create_read_only, beta_collection, embedder_config_1
):
    """Foreign org's collection → 404, not 403; foreign RAG unchanged."""
    foreign_rag = NaiveRag.objects.get(base_rag_type__source_collection=beta_collection)
    original_embedder_id = foreign_rag.embedder_id

    url = reverse("naive-rag-collection", args=[beta_collection.collection_id])

    response = client_create_read_only.post(
        url, {"embedder_id": embedder_config_1.pk}, format="json"
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    foreign_rag.refresh_from_db()
    assert foreign_rag.embedder_id == original_embedder_id


def test_create_or_update_existing_rag_with_update_read_no_create_denied(
    client_update_read_only, naive_rag_for_collection, test_collection, embedder_config_2
):
    """UPDATE+READ without CREATE → 403 (control: CREATE is still the base gate)."""
    url = reverse("naive-rag-collection", args=[test_collection.collection_id])

    response = client_update_read_only.post(
        url, {"embedder_id": embedder_config_2.pk}, format="json"
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_create_or_update_existing_rag_invalid_body_denies_before_validation(
    client_create_read_only, naive_rag_for_collection, test_collection
):
    """CREATE-without-UPDATE + invalid body on existing RAG → 403, not 400 (order: perms before validation)."""
    url = reverse("naive-rag-collection", args=[test_collection.collection_id])

    response = client_create_read_only.post(url, {}, format="json")

    assert response.status_code == status.HTTP_403_FORBIDDEN
