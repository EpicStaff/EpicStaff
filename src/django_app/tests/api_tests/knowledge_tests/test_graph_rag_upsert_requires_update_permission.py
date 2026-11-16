"""
Comprehensive RBAC tests for GraphRag.create_or_update endpoint.

The endpoint requires CREATE permission as the base action. When upserting (updating
an existing GraphRag), it additionally requires UPDATE permission. These tests verify:
- Permission checks happen in the correct order (org scope → permissions → validation)
- Both embedder_id and llm_id can be independently changed, and both require UPDATE
- Foreign org's collections return 404 (not 403)
- Invalid bodies trigger 403 before 400 when permission denied
"""

import pytest
from django.urls import reverse
from rest_framework import status

from rbac.models.enums import Permission, ResourceType
from tables.models import EmbeddingConfig, EmbeddingModel, LLMConfig, LLMModel, Provider
from tables.models.knowledge_models import (
    BaseRagType,
    DocumentContent,
    DocumentMetadata,
    GraphRag,
    SourceCollection,
)
from tests.api_tests.role_grant_clients import FULL_CRUD, client_with_grants
from tests.rbac_cross_org_fixtures import beta  # noqa: F401

pytestmark = pytest.mark.django_db


# --- Fixtures ---


@pytest.fixture
def openai_provider_fixture(db):
    """Get or create the OpenAI provider for test models."""
    provider, _ = Provider.objects.get_or_create(name="openai")
    return provider


@pytest.fixture
def embedding_model_1(openai_provider_fixture):
    """First embedding model for testing embedder swaps."""
    model, _ = EmbeddingModel.objects.get_or_create(
        name="text-embedding-3-small-1",
        defaults={"embedding_provider": openai_provider_fixture},
    )
    return model


@pytest.fixture
def embedding_model_2(openai_provider_fixture):
    """Second embedding model for testing embedder swaps."""
    model, _ = EmbeddingModel.objects.get_or_create(
        name="text-embedding-3-small-2",
        defaults={"embedding_provider": openai_provider_fixture},
    )
    return model


@pytest.fixture
def llm_model_1(openai_provider_fixture):
    """First LLM model for testing llm swaps."""
    model, _ = LLMModel.objects.get_or_create(
        name="gpt-4o-1",
        defaults={"llm_provider": openai_provider_fixture},
    )
    return model


@pytest.fixture
def llm_model_2(openai_provider_fixture):
    """Second LLM model for testing llm swaps."""
    model, _ = LLMModel.objects.get_or_create(
        name="gpt-4o-2",
        defaults={"llm_provider": openai_provider_fixture},
    )
    return model


@pytest.fixture
def embedder_config_1(embedding_model_1, default_org):
    """First embedder config in the default org."""
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
    """Second embedder config in the default org."""
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
def llm_config_1(llm_model_1, default_org):
    """First LLM config in the default org."""
    config, _ = LLMConfig.objects.get_or_create(
        custom_name="llm-config-1",
        defaults={
            "model": llm_model_1,
            "org": default_org,
        },
    )
    return config


@pytest.fixture
def llm_config_2(llm_model_2, default_org):
    """Second LLM config in the default org."""
    config, _ = LLMConfig.objects.get_or_create(
        custom_name="llm-config-2",
        defaults={
            "model": llm_model_2,
            "org": default_org,
        },
    )
    return config


@pytest.fixture
def test_collection(default_org):
    """Create a test source collection."""
    return SourceCollection.objects.create(
        collection_name="Test Collection", org=default_org
    )


@pytest.fixture
def empty_collection(default_org):
    """Create an empty source collection without GraphRag."""
    return SourceCollection.objects.create(
        collection_name="Empty Collection", org=default_org
    )


@pytest.fixture
def test_document(test_collection):
    """Create a test document in the test collection."""
    content = DocumentContent.objects.create(content=b"Test document content")
    return DocumentMetadata.objects.create(
        source_collection=test_collection,
        document_content=content,
        file_name="test_document.pdf",
        file_type="pdf",
        file_size=1024,
    )


@pytest.fixture
def existing_graph_rag(test_collection, embedder_config_1, llm_config_1):
    """Create an existing GraphRag for the test collection."""
    base_rag_type = BaseRagType.objects.create(
        source_collection=test_collection,
        rag_type=BaseRagType.RagType.GRAPH,
    )
    return GraphRag.objects.create(
        base_rag_type=base_rag_type,
        embedder=embedder_config_1,
        llm=llm_config_1,
        rag_status=GraphRag.GraphRagStatus.NEW,
    )


@pytest.fixture
def beta_collection(beta, openai_provider_fixture, llm_model_1, embedding_model_1):
    """Create a collection in the beta org (cross-org test)."""
    # Create LLM and embedder configs in the beta org
    beta_embedder = EmbeddingConfig.objects.create(
        custom_name="beta-embedder",
        model=embedding_model_1,
        task_type="retrieval_document",
        org=beta,
    )
    beta_llm = LLMConfig.objects.create(
        custom_name="beta-llm",
        model=llm_model_1,
        org=beta,
    )
    collection = SourceCollection.objects.create(
        collection_name="Beta Collection", org=beta
    )
    # Create GraphRag in beta org
    base_rag_type = BaseRagType.objects.create(
        source_collection=collection,
        rag_type=BaseRagType.RagType.GRAPH,
    )
    GraphRag.objects.create(
        base_rag_type=base_rag_type,
        embedder=beta_embedder,
        llm=beta_llm,
        rag_status=GraphRag.GraphRagStatus.NEW,
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
            ResourceType.KNOWLEDGE_SOURCES.value: int(
                Permission.CREATE | Permission.READ
            ),
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
            ResourceType.KNOWLEDGE_SOURCES.value: int(
                Permission.UPDATE | Permission.READ
            ),
        },
    )


# --- Test Cases ---


def test_create_read_without_update_existing_graph_rag_returns_403(
    client_create_read_only,
    existing_graph_rag,
    test_collection,
    embedder_config_2,
    llm_config_1,
):
    """
    Test Case 1: CREATE+READ without UPDATE, existing GraphRag → 403.

    Verify that trying to update an existing GraphRag without UPDATE permission
    returns 403 and the embedder_id in DB did NOT change.
    """
    url = reverse(
        "graph-rag-collection", args=[test_collection.collection_id]
    )
    original_embedder_id = existing_graph_rag.embedder_id

    response = client_create_read_only.post(
        url,
        {"embedder_id": embedder_config_2.pk, "llm_id": llm_config_1.pk},
        format="json",
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN
    existing_graph_rag.refresh_from_db()
    assert existing_graph_rag.embedder_id == original_embedder_id


def test_create_read_without_update_empty_collection_returns_200(
    client_create_read_only,
    empty_collection,
    embedder_config_1,
    llm_config_1,
):
    """
    Test Case 2: CREATE+READ without UPDATE, collection without GraphRag → 200.

    Verify that creating a new GraphRag (no existing one) succeeds with only
    CREATE+READ permissions, and the row exists in DB.
    """
    url = reverse(
        "graph-rag-collection", args=[empty_collection.collection_id]
    )

    response = client_create_read_only.post(
        url,
        {"embedder_id": embedder_config_1.pk, "llm_id": llm_config_1.pk},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    # Verify the GraphRag was actually created in DB
    graph_rag = GraphRag.objects.get(base_rag_type__source_collection=empty_collection)
    assert graph_rag.embedder_id == embedder_config_1.pk
    assert graph_rag.llm_id == llm_config_1.pk


def test_full_crud_existing_graph_rag_updates_both_fields(
    client_full_crud,
    existing_graph_rag,
    test_collection,
    embedder_config_2,
    llm_config_2,
):
    """
    Test Case 3: FULL_CRUD, existing GraphRag → 200 (success).

    Verify that a client with FULL_CRUD can update both embedder_id and llm_id,
    and both fields actually change in the DB.
    """
    url = reverse(
        "graph-rag-collection", args=[test_collection.collection_id]
    )

    response = client_full_crud.post(
        url,
        {"embedder_id": embedder_config_2.pk, "llm_id": llm_config_2.pk},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    existing_graph_rag.refresh_from_db()
    assert existing_graph_rag.embedder_id == embedder_config_2.pk
    assert existing_graph_rag.llm_id == llm_config_2.pk


def test_foreign_org_collection_returns_404(
    client_create_read_only,
    beta_collection,
    embedder_config_1,
    llm_config_1,
):
    """
    Test Case 4: Foreign org's collection → 404 (not 403).

    Verify that accessing a collection from another org returns 404, not 403,
    and the other org's GraphRag was NOT modified.
    """
    # Get the foreign GraphRag to check it later
    foreign_graph_rag = GraphRag.objects.get(
        base_rag_type__source_collection=beta_collection
    )
    original_embedder_id = foreign_graph_rag.embedder_id

    url = reverse(
        "graph-rag-collection", args=[beta_collection.collection_id]
    )

    response = client_create_read_only.post(
        url,
        {"embedder_id": embedder_config_1.pk, "llm_id": llm_config_1.pk},
        format="json",
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    foreign_graph_rag.refresh_from_db()
    assert foreign_graph_rag.embedder_id == original_embedder_id


def test_update_read_without_create_existing_graph_rag_returns_403(
    client_update_read_only,
    existing_graph_rag,
    test_collection,
    embedder_config_2,
    llm_config_1,
):
    """
    Test Case 5: UPDATE+READ without CREATE, existing GraphRag → 403 (control test).

    Verify that UPDATE without CREATE is insufficient, proving the action map
    still requires CREATE as the base permission.
    """
    url = reverse(
        "graph-rag-collection", args=[test_collection.collection_id]
    )
    original_embedder_id = existing_graph_rag.embedder_id

    response = client_update_read_only.post(
        url,
        {"embedder_id": embedder_config_2.pk, "llm_id": llm_config_1.pk},
        format="json",
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN
    existing_graph_rag.refresh_from_db()
    assert existing_graph_rag.embedder_id == original_embedder_id


def test_create_read_without_update_invalid_body_existing_graph_rag_returns_403(
    client_create_read_only,
    existing_graph_rag,
    test_collection,
):
    """
    Test Case 6: CREATE-without-UPDATE + invalid body on existing GraphRag → 403 (not 400).

    Verify that permission check happens before validation: a 403 is returned
    instead of 400 Bad Request, even though the body is invalid.
    """
    url = reverse(
        "graph-rag-collection", args=[test_collection.collection_id]
    )

    # Send invalid body (missing llm_id)
    response = client_create_read_only.post(
        url,
        {"embedder_id": 9999},  # Missing llm_id
        format="json",
    )

    # Permission check happens before validation, so 403 instead of 400
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_same_embedder_different_llm_without_update_returns_403(
    client_create_read_only,
    existing_graph_rag,
    test_collection,
    embedder_config_1,
    llm_config_2,
):
    """
    Test Case 7: GraphRag-specific - same embedder_id, different llm_id, client without UPDATE → 403.

    Verify that changing only llm_id (keeping embedder_id same) still requires
    UPDATE, and the change does NOT happen.
    """
    url = reverse(
        "graph-rag-collection", args=[test_collection.collection_id]
    )
    original_llm_id = existing_graph_rag.llm_id

    response = client_create_read_only.post(
        url,
        {"embedder_id": embedder_config_1.pk, "llm_id": llm_config_2.pk},
        format="json",
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN
    existing_graph_rag.refresh_from_db()
    assert existing_graph_rag.llm_id == original_llm_id


def test_different_embedder_same_llm_without_update_returns_403(
    client_create_read_only,
    existing_graph_rag,
    test_collection,
    embedder_config_2,
    llm_config_1,
):
    """
    Test Case 8: GraphRag-specific - different embedder_id, same llm_id, client without UPDATE → 403.

    Verify that changing only embedder_id (keeping llm_id same) still requires
    UPDATE, and the change does NOT happen.
    """
    url = reverse(
        "graph-rag-collection", args=[test_collection.collection_id]
    )
    original_embedder_id = existing_graph_rag.embedder_id

    response = client_create_read_only.post(
        url,
        {"embedder_id": embedder_config_2.pk, "llm_id": llm_config_1.pk},
        format="json",
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN
    existing_graph_rag.refresh_from_db()
    assert existing_graph_rag.embedder_id == original_embedder_id
