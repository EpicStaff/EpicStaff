import pytest
from rest_framework.test import APIClient

from tables.models import SourceCollection, DocumentMetadata
from tables.models.embedding_models import EmbeddingConfig
from tables.models.knowledge_models import BaseRagType, GraphRag, NaiveRag
from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole


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
