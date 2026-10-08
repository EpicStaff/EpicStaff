from unittest.mock import patch

import pytest
from django.urls import Resolver404, resolve, reverse
from rest_framework.test import APIClient

from rbac.models.enums import Permission, ResourceType
from rbac.models.role import RolePermission
from tables.models import SourceCollection, DocumentMetadata, StorageFile
from tables.services.storage_service.manager import StorageManager
from tests.storage_tests.in_memory_backend import InMemoryStorageBackend, seed_file
from tables.models.embedding_models import EmbeddingConfig
from tables.models.knowledge_models import BaseRagType, GraphRag, NaiveRag
from rbac.models import Organization, OrganizationUser, Role
from rbac.models.enums import BuiltInRole


# ---- fixtures ----


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="Org A")


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="Org B")


def _user(django_user_model, org, role_name, email):
    role = Role.objects.get(name=role_name, is_built_in=True, org__isnull=True)
    user = django_user_model.objects.create_user(email=email, password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=org, role=role)
    return user


def _client(user, org):
    c = APIClient()
    c.force_authenticate(user=user)
    c.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return c


@pytest.fixture
def client_member(db, django_user_model, org_a):
    return _client(
        _user(django_user_model, org_a, BuiltInRole.MEMBER, "km2@example.com"), org_a
    )


@pytest.fixture
def client_admin(db, django_user_model, org_a):
    return _client(
        _user(django_user_model, org_a, BuiltInRole.ORG_ADMIN, "ka2@example.com"), org_a
    )


def _results(resp):
    body = resp.data
    return body["results"] if isinstance(body, dict) and "results" in body else body


def _collection(org, name="c"):
    return SourceCollection.objects.create(collection_name=name, org=org)


def _graph_rag(org, name="c"):
    coll = _collection(org, name)
    brt = BaseRagType.objects.create(
        rag_type=BaseRagType.RagType.GRAPH, source_collection=coll
    )
    return GraphRag.objects.create(base_rag_type=brt), coll


def _naive_rag(org, name="c"):
    coll = _collection(org, name)
    brt = BaseRagType.objects.create(
        rag_type=BaseRagType.RagType.NAIVE, source_collection=coll
    )
    return NaiveRag.objects.create(base_rag_type=brt), coll


# ---- GraphRag (3c) ----


@pytest.mark.django_db
def test_graph_rag_retrieve_cross_org_404(client_member, org_b):
    gr, _ = _graph_rag(org_b)
    assert client_member.get(f"/api/graph-rag/{gr.graph_rag_id}/").status_code == 404


@pytest.mark.django_db
def test_graph_rag_destroy_cross_org_404(client_admin, org_b):
    gr, _ = _graph_rag(org_b)
    assert client_admin.delete(f"/api/graph-rag/{gr.graph_rag_id}/").status_code == 404


@pytest.mark.django_db
def test_graph_rag_create_cross_org_collection_404(client_admin, org_b):
    coll = _collection(org_b, "theirs")
    resp = client_admin.post(
        f"/api/graph-rag/collections/{coll.collection_id}/graph-rag/",
        {"embedder_id": 1, "llm_id": 1},
        format="json",
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_graph_rag_create_rejects_cross_org_embedder(client_admin, org_a, org_b):
    coll = _collection(org_a, "mine")
    other_embedder = EmbeddingConfig.objects.create(custom_name="e", org=org_b)
    resp = client_admin.post(
        f"/api/graph-rag/collections/{coll.collection_id}/graph-rag/",
        {"embedder_id": other_embedder.id, "llm_id": 1},
        format="json",
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_graph_rag_create_denied_for_member(client_member, org_a):
    coll = _collection(org_a, "mine")
    resp = client_member.post(
        f"/api/graph-rag/collections/{coll.collection_id}/graph-rag/",
        {"embedder_id": 1, "llm_id": 1},
        format="json",
    )
    assert resp.status_code == 403


# ---- Documents (3d) ----


@pytest.mark.django_db
def test_document_list_only_active_org(client_member, org_a, org_b):
    DocumentMetadata.objects.create(
        source_collection=_collection(org_a, "a"), file_name="mine"
    )
    DocumentMetadata.objects.create(
        source_collection=_collection(org_b, "b"), file_name="theirs"
    )
    results = _results(client_member.get("/api/documents/"))
    assert len(results) == 1


@pytest.mark.django_db
def test_document_retrieve_cross_org_404(client_member, org_b):
    doc = DocumentMetadata.objects.create(
        source_collection=_collection(org_b, "b"), file_name="theirs"
    )
    assert client_member.get(f"/api/documents/{doc.document_id}/").status_code == 404


@pytest.mark.django_db
def test_document_bulk_delete_ignores_other_org(client_admin, org_a, org_b):
    mine = DocumentMetadata.objects.create(
        source_collection=_collection(org_a, "a"), file_name="mine"
    )
    theirs = DocumentMetadata.objects.create(
        source_collection=_collection(org_b, "b"), file_name="theirs"
    )
    resp = client_admin.post(
        "/api/documents/bulk-delete/",
        {"document_ids": [mine.document_id, theirs.document_id]},
        format="json",
    )
    assert resp.status_code == 200, resp.data
    assert not DocumentMetadata.objects.filter(document_id=mine.document_id).exists()
    assert DocumentMetadata.objects.filter(document_id=theirs.document_id).exists()


@pytest.mark.django_db
def test_collection_documents_cross_org_404(client_member, org_b):
    coll = _collection(org_b, "theirs")
    resp = client_member.get(f"/api/source-collections/{coll.collection_id}/documents/")
    assert resp.status_code == 404


# ---- ProcessRagIndexing (3e) ----


@pytest.mark.django_db
def test_process_rag_indexing_cross_org_404(client_admin, org_b):
    nr, _ = _naive_rag(org_b)
    resp = client_admin.post(
        "/api/process-rag-indexing/",
        {"rag_id": nr.naive_rag_id, "rag_type": "naive"},
        format="json",
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_process_rag_indexing_denied_for_member(client_member, org_a):
    nr, _ = _naive_rag(org_a)
    resp = client_member.post(
        "/api/process-rag-indexing/",
        {"rag_id": nr.naive_rag_id, "rag_type": "naive"},
        format="json",
    )
    assert resp.status_code == 403  # indexing requires UPDATE; Member is READ only


# ---- Import from storage ----


@pytest.fixture
def storage_manager():
    manager = StorageManager(InMemoryStorageBackend(organization_prefix=""))
    with patch(
        "tables.views.knowledge_views.document_management_views.get_storage_manager",
        return_value=manager,
    ):
        yield manager


def _stored_file(storage_manager, org, path, content=b"content"):
    seed_file(storage_manager._backend, org.id, path, content)
    return StorageFile.objects.get(org=org, path=path)


def _import(client, collection, storage_file_ids):
    return client.post(
        f"/api/documents/source-collection/{collection.collection_id}/from-storage/",
        {"storage_file_ids": storage_file_ids},
        format="json",
    )


def test_import_from_storage_has_only_the_contract_url():
    match = resolve("/api/documents/source-collection/7/from-storage/")
    assert match.url_name == "document-import-from-storage"
    assert match.kwargs == {"collection_id": "7"}
    assert reverse("document-import-from-storage", args=[7]) == (
        "/api/documents/source-collection/7/from-storage/"
    )

    for unintended in (
        "/api/documents/source-collections/7/from-storage/",
        "/api/source-collections/7/from-storage/",
    ):
        with pytest.raises(Resolver404):
            resolve(unintended)


def _client_with_grants(django_user_model, org, email, grants):
    role = Role.objects.create(name=f"role-{email}", org=org, is_built_in=False)
    for resource_type, permissions in grants.items():
        RolePermission.objects.create(
            role=role, resource_type=resource_type, permissions=int(permissions)
        )
    user = django_user_model.objects.create_user(email=email, password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=org, role=role)
    return _client(user, org)


@pytest.mark.django_db
def test_import_from_storage_cross_org_collection_404(client_admin, storage_manager, org_a, org_b):
    theirs = _collection(org_b, "theirs")
    mine = _stored_file(storage_manager, org_a, "mine.txt")

    resp = _import(client_admin, theirs, [mine.id])

    assert resp.status_code == 404
    assert not DocumentMetadata.objects.exists()


@pytest.mark.django_db
def test_import_from_storage_cross_org_storage_file_404(
    client_admin, storage_manager, org_a, org_b
):
    coll = _collection(org_a, "mine")
    mine = _stored_file(storage_manager, org_a, "mine.txt")
    theirs = _stored_file(storage_manager, org_b, "theirs.txt")

    resp = _import(client_admin, coll, [mine.id, theirs.id])

    assert resp.status_code == 404
    # The generic envelope, identical to a missing collection: no id is named.
    assert resp.data == {"status_code": 404, "code": "not_found", "message": "Not found."}
    assert not DocumentMetadata.objects.exists()


@pytest.mark.django_db
def test_import_from_storage_cross_org_folder_404(client_admin, storage_manager, org_a, org_b):
    coll = _collection(org_a, "mine")
    _stored_file(storage_manager, org_b, "shared/theirs.txt")
    their_folder = StorageFile.objects.get(org=org_b, path="shared/")

    resp = _import(client_admin, coll, [their_folder.id])

    assert resp.status_code == 404
    assert not DocumentMetadata.objects.exists()


@pytest.mark.django_db
def test_import_from_storage_explicit_system_file_404(client_admin, storage_manager, org_a):
    coll = _collection(org_a, "mine")
    system_file = _stored_file(storage_manager, org_a, "session-output.txt")
    StorageFile.objects.filter(id=system_file.id).update(is_system=True)

    resp = _import(client_admin, coll, [system_file.id])

    assert resp.status_code == 404
    assert not DocumentMetadata.objects.exists()


@pytest.mark.django_db
def test_import_from_storage_denied_without_knowledge_create(client_member, storage_manager, org_a):
    coll = _collection(org_a, "mine")
    stored = _stored_file(storage_manager, org_a, "mine.txt")

    resp = _import(client_member, coll, [stored.id])

    assert resp.status_code == 403
    assert not DocumentMetadata.objects.exists()


@pytest.mark.django_db
def test_import_from_storage_denied_without_files_read(
    django_user_model, storage_manager, org_a
):
    client = _client_with_grants(
        django_user_model,
        org_a,
        "ks-create-only@example.com",
        {ResourceType.KNOWLEDGE_SOURCES: Permission.CREATE | Permission.READ},
    )
    coll = _collection(org_a, "mine")
    stored = _stored_file(storage_manager, org_a, "mine.txt")

    resp = _import(client, coll, [stored.id])

    assert resp.status_code == 403
    assert not DocumentMetadata.objects.exists()


@pytest.mark.django_db
def test_import_from_storage_denied_with_files_read_only(
    django_user_model, storage_manager, org_a
):
    client = _client_with_grants(
        django_user_model,
        org_a,
        "files-read-only@example.com",
        {ResourceType.FILES: Permission.READ, ResourceType.KNOWLEDGE_SOURCES: Permission.READ},
    )
    coll = _collection(org_a, "mine")
    stored = _stored_file(storage_manager, org_a, "mine.txt")

    resp = _import(client, coll, [stored.id])

    assert resp.status_code == 403
    assert not DocumentMetadata.objects.exists()


@pytest.mark.django_db
def test_import_from_storage_allowed_with_both_grants(django_user_model, storage_manager, org_a):
    client = _client_with_grants(
        django_user_model,
        org_a,
        "ks-create-files-read@example.com",
        {
            ResourceType.FILES: Permission.READ,
            ResourceType.KNOWLEDGE_SOURCES: Permission.CREATE | Permission.READ,
        },
    )
    coll = _collection(org_a, "mine")
    stored = _stored_file(storage_manager, org_a, "mine.txt")

    resp = _import(client, coll, [stored.id])

    assert resp.status_code == 201, resp.data
    assert DocumentMetadata.objects.filter(source_collection=coll).count() == 1
