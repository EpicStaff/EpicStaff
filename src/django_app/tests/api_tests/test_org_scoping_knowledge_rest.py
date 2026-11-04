from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from django.urls import Resolver404, resolve, reverse
from rest_framework.test import APIClient

from rbac.authorship import record_last_edit
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


def _index_body(naive_rag):
    # The body is validated before the org check, so it must be complete.
    # The view reads document_config_ids only after the org and permission checks.
    return {
        "rag_id": naive_rag.naive_rag_id,
        "rag_type": "naive",
        "document_config_ids": [],
    }


@pytest.mark.django_db
def test_process_rag_indexing_cross_org_404(client_admin, org_b):
    nr, _ = _naive_rag(org_b)
    resp = client_admin.post(
        "/api/process-rag-indexing/",
        _index_body(nr),
        format="json",
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_process_rag_indexing_denied_for_member(client_member, org_a):
    nr, _ = _naive_rag(org_a)
    resp = client_member.post(
        "/api/process-rag-indexing/",
        _index_body(nr),
        format="json",
    )
    assert resp.status_code == 403  # indexing requires UPDATE; Member is READ only


# ---- Import from storage ----

# A foreign id answers exactly like a missing one: no id, path or org in the body.
NOT_FOUND_BODY = {"status_code": 404, "code": "not_found", "message": "Not found."}
PREVIOUS_EDIT_AT = datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)


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


def _api_key_client(raw_key, org):
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=raw_key, HTTP_X_ORGANIZATION_ID=str(org.id))
    return client


@pytest.fixture
def api_key_client_as(issue_api_key):
    """Factory: a client with a new USER API key of `user` that sends `org` as `X-Organization-Id`.

    The key belongs to `user`'s first org (see `issue_api_key`) and acts only there: the
    header is ignored, so `org` is the active org only when it is that first org.
    """

    def _make(user, org):
        raw_key, _ = issue_api_key(user=user)
        return _api_key_client(raw_key, org)

    return _make


@pytest.fixture(
    params=["org_admin_session", "superadmin_session", "org_admin_user_api_key", "system_api_key"]
)
def org_a_caller(request, django_user_model, issue_api_key, api_key_client_as, org_a):
    """A client with org A active that passes every permission gate there.

    The Org Admin holds the grants; the superadmin and the SYSTEM key bypass the
    gates; the USER key acts as its Org Admin owner. None of them may bypass
    org A's row scope.
    """
    if request.param == "org_admin_session":
        return _client(
            _user(django_user_model, org_a, BuiltInRole.ORG_ADMIN, "ks-org-admin@example.com"),
            org_a,
        )
    if request.param == "superadmin_session":
        superadmin = django_user_model.objects.create_user(
            email="ks-superadmin@example.com", password="StrongPass123!", is_superadmin=True
        )
        return _client(superadmin, org_a)
    if request.param == "org_admin_user_api_key":
        owner = _user(django_user_model, org_a, BuiltInRole.ORG_ADMIN, "ks-key-owner@example.com")
        return api_key_client_as(owner, org_a)
    raw_key, _ = issue_api_key(user=None)
    return _api_key_client(raw_key, org_a)


@pytest.fixture(params=["collection", "storage_file"])
def other_org_target(request, storage_manager, org_a, org_b):
    """(collection, storage_file_ids) where exactly one side belongs to org B, the rest to org A.

    Both orgs hold a file at the same path. Otherwise a lookup that ignored the
    org would still answer 404, only because the foreign path has no object to
    download in org A, and the test could not tell the two apart.
    """
    own_file = _stored_file(storage_manager, org_a, "report.txt", b"own")
    their_file = _stored_file(storage_manager, org_b, "report.txt", b"their bytes")
    if request.param == "collection":
        return _collection(org_b, "theirs"), [own_file.id]
    return _collection(org_a, "mine"), [their_file.id]


@pytest.mark.django_db
def test_import_from_storage_cross_org_storage_file_404(
    client_admin, django_user_model, storage_manager, org_a, org_b
):
    coll = _collection(org_a, "mine")
    previous_editor = _user(
        django_user_model, org_a, BuiltInRole.MEMBER, "previous-editor@example.com"
    )
    record_last_edit(coll, previous_editor, edited_at=PREVIOUS_EDIT_AT)
    # One path in both orgs, so ignoring the org would find bytes to download
    # in org A instead of failing on a missing object.
    mine = _stored_file(storage_manager, org_a, "report.txt", b"own")
    theirs = _stored_file(storage_manager, org_b, "report.txt", b"their bytes")

    resp = _import(client_admin, coll, [mine.id, theirs.id])

    assert resp.status_code == 404
    # The generic envelope, identical to a missing collection: no id is named.
    assert resp.data == NOT_FOUND_BODY
    assert not DocumentMetadata.objects.exists()
    # The own file in the selection is not imported either, so no edit is recorded.
    last_edit = coll.last_edits.get()
    assert (last_edit.edited_by_id, last_edit.edited_at) == (previous_editor.id, PREVIOUS_EDIT_AT)


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
@pytest.mark.parametrize("role_name", [BuiltInRole.MEMBER, BuiltInRole.VIEWER])
def test_import_from_storage_denied_without_knowledge_create(
    django_user_model, storage_manager, org_a, role_name
):
    # Both built-in roles read knowledge sources and files but cannot create sources.
    client = _client(_user(django_user_model, org_a, role_name, "no-ks-create@example.com"), org_a)
    coll = _collection(org_a, "mine")
    stored = _stored_file(storage_manager, org_a, "mine.txt")

    resp = _import(client, coll, [stored.id])

    assert resp.status_code == 403
    assert resp.data["code"] == "permission_denied"
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


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("stored_path", "binned_path", "binned_row_path"),
    [("report.pdf", "report.pdf", "report.pdf"), ("docs/report.pdf", "docs", "docs/")],
    ids=["file", "folder"],
)
def test_import_from_storage_binned_item_404(
    client_admin, storage_manager, org_a, stored_path, binned_path, binned_row_path
):
    coll = _collection(org_a, "mine")
    _stored_file(storage_manager, org_a, stored_path, b"binned")
    storage_manager.delete(org_a.id, binned_path, user=None)
    binned = StorageFile.deleted_objects.get(org=org_a, path=binned_row_path)
    # Binning moves the object to the trash. A new upload to the same path puts
    # a live object back there, so the 404 can only come from leaving the
    # binned row out, not from a missing object.
    _stored_file(storage_manager, org_a, stored_path, b"uploaded again")

    resp = _import(client_admin, coll, [binned.id])

    assert resp.status_code == 404
    assert resp.data == NOT_FOUND_BODY
    assert not DocumentMetadata.objects.exists()


@pytest.mark.django_db
def test_import_from_storage_folder_leaves_out_binned_files(client_admin, storage_manager, org_a):
    coll = _collection(org_a, "mine")
    _stored_file(storage_manager, org_a, "docs/kept.pdf")
    _stored_file(storage_manager, org_a, "docs/binned.pdf")
    storage_manager.delete(org_a.id, "docs/binned.pdf", user=None)
    folder = StorageFile.objects.get(org=org_a, path="docs/")

    resp = _import(client_admin, coll, [folder.id])

    assert resp.status_code == 201, resp.data
    assert [document["file_name"] for document in resp.data["documents"]] == ["kept.pdf"]
    assert resp.data["skipped"] == []


@pytest.mark.django_db
def test_import_from_storage_other_org_ids_404_for_every_kind_of_caller(
    org_a_caller, other_org_target
):
    collection, storage_file_ids = other_org_target

    resp = _import(org_a_caller, collection, storage_file_ids)

    assert resp.status_code == 404
    assert resp.data == NOT_FOUND_BODY
    assert not DocumentMetadata.objects.exists()


@pytest.mark.django_db
def test_import_from_storage_system_api_key_imports_and_records_no_editor(
    django_user_model, issue_api_key, storage_manager, org_a
):
    coll = _collection(org_a, "mine")
    previous_editor = _user(
        django_user_model, org_a, BuiltInRole.MEMBER, "previous-editor@example.com"
    )
    record_last_edit(coll, previous_editor, edited_at=PREVIOUS_EDIT_AT)
    stored = _stored_file(storage_manager, org_a, "mine.txt")
    raw_key, _ = issue_api_key(user=None)

    resp = _import(_api_key_client(raw_key, org_a), coll, [stored.id])

    assert resp.status_code == 201, resp.data
    assert [document["file_name"] for document in resp.data["documents"]] == ["mine.txt"]
    # The system principal is not a user: the edit is recorded with no editor.
    last_edit = coll.last_edits.get()
    assert last_edit.edited_by_id is None
    assert last_edit.edited_at > PREVIOUS_EDIT_AT


@pytest.mark.django_db
def test_import_from_storage_header_naming_an_org_the_caller_is_not_in_is_403(
    django_user_model, storage_manager, org_a, org_b
):
    admin_of_a = _user(django_user_model, org_a, BuiltInRole.ORG_ADMIN, "ks-admin-a@example.com")
    their_collection = _collection(org_b, "theirs")
    their_file = _stored_file(storage_manager, org_b, "theirs.txt")

    resp = _import(_client(admin_of_a, org_b), their_collection, [their_file.id])

    assert resp.status_code == 403
    assert resp.data == {
        "status_code": 403,
        "code": "org_membership_required",
        "message": "You are not a member of this organization.",
    }
    assert not DocumentMetadata.objects.exists()


@pytest.mark.django_db
def test_import_from_storage_user_api_key_ignores_header_and_finds_no_foreign_collection(
    django_user_model, api_key_client_as, storage_manager, org_a, org_b
):
    # The key acts in its own org A, so org B's collection is simply not found there.
    admin_of_a = _user(django_user_model, org_a, BuiltInRole.ORG_ADMIN, "ks-admin-a@example.com")
    their_collection = _collection(org_b, "theirs")
    their_file = _stored_file(storage_manager, org_b, "theirs.txt")

    resp = _import(api_key_client_as(admin_of_a, org_b), their_collection, [their_file.id])

    assert resp.status_code == 404
    assert not DocumentMetadata.objects.exists()


@pytest.mark.django_db
def test_import_from_storage_without_org_header_400(django_user_model, storage_manager, org_a):
    # The caller belongs to a single org; it is still not picked implicitly.
    admin = _user(django_user_model, org_a, BuiltInRole.ORG_ADMIN, "ks-no-header@example.com")
    client = APIClient()
    client.force_authenticate(user=admin)
    coll = _collection(org_a, "mine")
    stored = _stored_file(storage_manager, org_a, "mine.txt")

    resp = _import(client, coll, [stored.id])

    assert resp.status_code == 400
    assert resp.data["code"] == "org_context_required"
    assert not DocumentMetadata.objects.exists()


@pytest.mark.django_db
def test_import_from_storage_201_returns_only_documents_created_in_the_target_collection(
    client_admin, storage_manager, org_a, org_b
):
    target = _collection(org_a, "target")
    stored_ids = [
        _stored_file(storage_manager, org_a, "report.txt").id,
        _stored_file(storage_manager, org_a, "notes.md").id,
    ]
    # Same name and size as an imported file, in another collection of each org:
    # a duplicate check or result query reaching past the target would show here.
    decoys = [
        DocumentMetadata.objects.create(
            source_collection=other_collection,
            file_name="report.txt",
            file_type="txt",
            file_size=len(b"content"),
        )
        for other_collection in (_collection(org_a, "other"), _collection(org_b, "theirs"))
    ]

    resp = _import(client_admin, target, stored_ids)

    assert resp.status_code == 201, resp.data
    assert resp.data["skipped"] == []
    assert sorted(document["file_name"] for document in resp.data["documents"]) == [
        "notes.md",
        "report.txt",
    ]
    assert {document["source_collection"] for document in resp.data["documents"]} == {
        target.collection_id
    }
    # Each decoy is still the only document of its collection, unchanged.
    for decoy in decoys:
        assert list(
            DocumentMetadata.objects.filter(
                source_collection_id=decoy.source_collection_id
            ).values_list("document_id", "file_name", "file_size")
        ) == [(decoy.document_id, "report.txt", len(b"content"))]
