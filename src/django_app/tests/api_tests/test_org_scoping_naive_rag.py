import pytest
from rest_framework.test import APIClient

from tables.models import SourceCollection
from tables.models.embedding_models import EmbeddingConfig
from tables.models.knowledge_models import (
    BaseRagType,
    NaiveRag,
    NaiveRagChunk,
    NaiveRagDocumentConfig,
)
from tables.models.knowledge_models.collection_models import DocumentMetadata
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
def client_member(db, django_user_model, org_a):  # knowledge READ only
    return _client(
        _user(django_user_model, org_a, BuiltInRole.MEMBER, "nm@example.com"), org_a
    )


@pytest.fixture
def client_admin(db, django_user_model, org_a):  # knowledge CRUD
    return _client(
        _user(django_user_model, org_a, BuiltInRole.ORG_ADMIN, "na@example.com"), org_a
    )


def _results(resp):
    body = resp.data
    return body["results"] if isinstance(body, dict) and "results" in body else body


def _naive_rag(org, name="c"):
    coll = SourceCollection.objects.create(collection_name=name, org=org)
    brt = BaseRagType.objects.create(
        rag_type=BaseRagType.RagType.NAIVE, source_collection=coll
    )
    return NaiveRag.objects.create(base_rag_type=brt), coll


def _chunk(org, name="c"):
    nr, coll = _naive_rag(org, name)
    doc = DocumentMetadata.objects.create(source_collection=coll, file_name="f")
    cfg = NaiveRagDocumentConfig.objects.create(naive_rag=nr, document=doc)
    chunk = NaiveRagChunk.objects.create(
        naive_rag_document_config=cfg, text="t", chunk_index=0
    )
    return chunk, cfg, nr, coll


# ---- NaiveRag (service-delegating, raw-id gating) ----


@pytest.mark.django_db
def test_naive_rag_retrieve_own_org(client_member, org_a):
    nr, _ = _naive_rag(org_a)
    assert client_member.get(f"/api/naive-rag/{nr.naive_rag_id}/").status_code == 200


@pytest.mark.django_db
def test_naive_rag_retrieve_cross_org_404(client_member, org_b):
    nr, _ = _naive_rag(org_b)
    assert client_member.get(f"/api/naive-rag/{nr.naive_rag_id}/").status_code == 404


@pytest.mark.django_db
def test_naive_rag_destroy_cross_org_404(client_admin, org_b):
    nr, _ = _naive_rag(org_b)
    assert client_admin.delete(f"/api/naive-rag/{nr.naive_rag_id}/").status_code == 404


@pytest.mark.django_db
def test_get_by_collection_cross_org_404(client_member, org_b):
    _, coll = _naive_rag(org_b)
    resp = client_member.get(
        f"/api/naive-rag/collections/{coll.collection_id}/naive-rag/"
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_create_or_update_cross_org_collection_404(client_admin, org_b):
    coll = SourceCollection.objects.create(collection_name="theirs", org=org_b)
    resp = client_admin.post(
        f"/api/naive-rag/collections/{coll.collection_id}/naive-rag/",
        {"embedder_id": 1},
        format="json",
    )
    assert resp.status_code == 404  # collection not in active org


@pytest.mark.django_db
def test_create_or_update_denied_for_member(client_member, org_a):
    coll = SourceCollection.objects.create(collection_name="mine", org=org_a)
    resp = client_member.post(
        f"/api/naive-rag/collections/{coll.collection_id}/naive-rag/",
        {"embedder_id": 1},
        format="json",
    )
    assert resp.status_code == 403  # Member has knowledge_sources READ only


@pytest.mark.django_db
def test_create_or_update_rejects_cross_org_embedder(client_admin, org_a, org_b):
    coll = SourceCollection.objects.create(collection_name="mine", org=org_a)
    other_embedder = EmbeddingConfig.objects.create(custom_name="e", org=org_b)
    resp = client_admin.post(
        f"/api/naive-rag/collections/{coll.collection_id}/naive-rag/",
        {"embedder_id": other_embedder.id},
        format="json",
    )
    assert resp.status_code == 404  # embedder belongs to another org


# ---- NaiveRagDocumentConfig (get_object via scoped queryset) ----


@pytest.mark.django_db
def test_document_config_retrieve_cross_org_404(client_member, org_b):
    _, cfg, nr, _ = _chunk(org_b)
    resp = client_member.get(
        f"/api/naive-rag/{nr.naive_rag_id}/document-configs/{cfg.naive_rag_document_id}/"
    )
    assert resp.status_code == 404


# ---- NaiveRagChunk (child mixin, deep org_filter_path) ----


@pytest.mark.django_db
def test_chunk_list_only_active_org(client_member, org_a, org_b):
    _chunk(org_a, name="mine")
    _chunk(org_b, name="theirs")
    # fresh test DB: only these two chunks exist; the member sees only org A's.
    results = _results(client_member.get("/api/naive-rag-document-chunks/"))
    assert len(results) == 1
