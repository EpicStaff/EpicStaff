"""Write routes whose URL does not name what they change (`HOOK_RECORDED_ROUTES`) record
each changed object by an explicit hook, and a request that changed nothing records nothing.
The last section covers rows the fallback names through their URL.

Presentation tests through the real endpoints. Only the object store (in-memory backend),
the knowledge service client and Twilio's HTTP API are replaced.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpResponse
from django.test import RequestFactory
from django.urls import ResolverMatch
from rest_framework import status

from rbac.models import OrganizationUser
from tables.clients.errors import ClientResourceNotFoundError
from tables.models import (
    DocumentContent,
    DocumentMetadata,
    Graph,
    GraphVersion,
    Session,
    SourceCollection,
    StorageFile,
)
from tables.models.default_models import DefaultModels
from tables.models.embedding_models import EmbeddingConfig, EmbeddingModel
from tables.models.knowledge_models import (
    BaseRagType,
    GraphRag,
    NaiveRag,
    NaiveRagDocumentConfig,
)
from tables.models.llm_models import LLMConfig, LLMModel
from tables.models.provider import Provider
from tables.models.webhook_models import (
    NgrokWebhookConfig,
    ProviderType,
    RealtimeChannel,
    TwilioChannel,
    WebhookTrigger,
)
from tables.services.knowledge_services.graph_rag_service import GraphRagService
from tables.services.secrets import secret_service
from tables.services.storage_service.manager import StorageManager
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403
from tables.views.knowledge_views.naive_rag_views import NaiveRagViewSet
from tests.storage_tests.in_memory_backend import InMemoryStorageBackend, seed_file
from user_audit.middleware import UserActionMiddleware

pytestmark = pytest.mark.django_db

DOCUMENT_STORAGE_MANAGER = (
    "tables.views.knowledge_views.document_management_views.get_storage_manager"
)


@pytest.fixture
def admin_client(client_as, admin_acme, acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


@pytest.fixture
def collection(acme):
    return SourceCollection.objects.create(collection_name="Manuals", org=acme)


@pytest.fixture
def flow(acme):
    return Graph.objects.create(name="Billing flow", org=acme)


def _embedder(org, name="Embedder") -> EmbeddingConfig:
    provider, _ = Provider.objects.get_or_create(name="embedding-provider")
    model, _ = EmbeddingModel.objects.get_or_create(
        name="embedding-model", defaults={"embedding_provider": provider}
    )
    return EmbeddingConfig.objects.create(custom_name=name, model=model, org=org)


def _llm_config(org, name="Writer LLM") -> LLMConfig:
    provider, _ = Provider.objects.get_or_create(name="llm-provider")
    model, _ = LLMModel.objects.get_or_create(name="llm-model", defaults={"llm_provider": provider})
    return LLMConfig.objects.create(custom_name=name, model=model, org=org)


def _document(collection, file_name="guide.txt") -> DocumentMetadata:
    return DocumentMetadata.objects.create(
        source_collection=collection,
        document_content=DocumentContent.objects.create(content=b"text"),
        file_name=file_name,
        file_type="txt",
        file_size=4,
    )


def _naive_rag(collection) -> NaiveRag:
    return NaiveRag.objects.create(
        base_rag_type=BaseRagType.objects.create(
            source_collection=collection, rag_type=BaseRagType.RagType.NAIVE
        ),
        embedder=_embedder(collection.org),
    )


def _document_config(naive_rag, collection) -> NaiveRagDocumentConfig:
    return NaiveRagDocumentConfig.objects.create(
        naive_rag=naive_rag,
        document=_document(collection),
        chunk_strategy="token",
        chunk_size=1000,
        chunk_overlap=150,
    )


def _send(client, method, url, capture, body=None, format="json"):
    with capture(execute=True):
        return getattr(client, method)(url, body, format=format)


def _target(event) -> tuple:
    return event.action, event.target_type, event.target_id, event.target_name


def _parent(event) -> tuple:
    return event.parent_type, event.parent_id, event.parent_name


def _hook_events(sent_events) -> list:
    # The fallback always sets a route; a hook never does.
    assert all(event.route is None for event in sent_events), sent_events
    return sent_events


def _collection_updated(collection) -> tuple:
    return ("updated", "source collection", str(collection.pk), collection.collection_name)


# ---- documents ----


def test_document_upload_records_each_document_created_in_its_collection(
    admin_client, acme, collection, sent_events, django_capture_on_commit_callbacks
):
    files = [
        SimpleUploadedFile("first.txt", b"one", content_type="text/plain"),
        SimpleUploadedFile("second.txt", b"two", content_type="text/plain"),
    ]

    response = _send(
        admin_client,
        "post",
        f"/api/documents/source-collection/{collection.collection_id}/upload/",
        django_capture_on_commit_callbacks,
        {"files": files},
        format="multipart",
    )

    assert response.status_code == status.HTTP_201_CREATED, response.content
    documents = {document.file_name: document for document in collection.documents.all()}
    events = _hook_events(sent_events)
    assert sorted(_target(event) for event in events) == [
        ("created", "document", str(documents["first.txt"].pk), "first.txt"),
        ("created", "document", str(documents["second.txt"].pk), "second.txt"),
    ]
    assert {_parent(event) for event in events} == {
        ("source collection", str(collection.pk), "Manuals")
    }
    assert {event.org_id for event in events} == {acme.id}


def test_document_import_from_storage_records_the_document_created(
    admin_client, acme, collection, sent_events, django_capture_on_commit_callbacks
):
    manager = StorageManager(InMemoryStorageBackend(organization_prefix=""))
    seed_file(manager._backend, acme.id, "notes/plan.txt", b"plan")
    stored = StorageFile.objects.get(org=acme, path="notes/plan.txt")

    with patch(DOCUMENT_STORAGE_MANAGER, return_value=manager):
        response = _send(
            admin_client,
            "post",
            f"/api/documents/source-collection/{collection.collection_id}/from-storage/",
            django_capture_on_commit_callbacks,
            {"storage_file_ids": [stored.id]},
        )

    assert response.status_code == status.HTTP_201_CREATED, response.content
    document = collection.documents.get()
    [event] = _hook_events(sent_events)
    assert _target(event) == ("created", "document", str(document.pk), "plan.txt")
    assert _parent(event) == ("source collection", str(collection.pk), "Manuals")


def test_document_copy_records_the_copy_under_the_target_collection(
    admin_client, acme, collection, sent_events, django_capture_on_commit_callbacks
):
    source = SourceCollection.objects.create(collection_name="Drafts", org=acme)
    original = _document(source)

    response = _send(
        admin_client,
        "post",
        "/api/documents/copy/",
        django_capture_on_commit_callbacks,
        {"collection_id": collection.collection_id, "document_ids": [original.document_id]},
    )

    assert response.status_code == status.HTTP_201_CREATED, response.content
    copy = collection.documents.get()
    [event] = _hook_events(sent_events)
    assert _target(event) == ("copied", "document", str(copy.pk), "guide.txt")
    assert _parent(event) == ("source collection", str(collection.pk), "Manuals")


def test_document_copy_that_skips_everything_records_nothing(
    admin_client, collection, sent_events, django_capture_on_commit_callbacks
):
    document = _document(collection)

    response = _send(
        admin_client,
        "post",
        "/api/documents/copy/",
        django_capture_on_commit_callbacks,
        {"collection_id": collection.collection_id, "document_ids": [document.document_id]},
    )

    assert response.status_code == status.HTTP_201_CREATED, response.content
    assert sent_events == []


def test_document_bulk_delete_records_each_document_deleted(
    admin_client, collection, sent_events, django_capture_on_commit_callbacks
):
    document = _document(collection)
    document_id = document.document_id

    response = _send(
        admin_client,
        "post",
        "/api/documents/bulk-delete/",
        django_capture_on_commit_callbacks,
        {"document_ids": [document_id]},
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert not DocumentMetadata.objects.filter(document_id=document_id).exists()
    [event] = _hook_events(sent_events)
    assert _target(event) == ("deleted", "document", str(document_id), "guide.txt")
    assert _parent(event) == ("source collection", str(collection.pk), "Manuals")


# ---- imports ----


def _exported_flow(client, flow) -> bytes:
    response = client.get(f"/api/graphs/{flow.id}/export/")
    assert response.status_code == status.HTTP_200_OK, response.content
    return response.content


def _import_flow(client, exported: bytes, capture, **settings):
    upload = SimpleUploadedFile("flow.json", exported, content_type="application/json")
    return _send(
        client,
        "post",
        "/api/graphs/import/",
        capture,
        {"file": upload, **settings},
        format="multipart",
    )


def test_flow_import_records_the_created_flow_by_name(
    admin_client, acme, flow, sent_events, django_capture_on_commit_callbacks
):
    exported = _exported_flow(admin_client, flow)

    response = _import_flow(admin_client, exported, django_capture_on_commit_callbacks)

    assert response.status_code == status.HTTP_200_OK, response.content
    imported = Graph.objects.exclude(pk=flow.pk).get(org=acme)
    [event] = _hook_events(sent_events)
    assert _target(event) == ("created", "flow", str(imported.pk), imported.name)
    assert imported.name.startswith("Billing flow")


def test_flow_import_replacing_a_flow_records_it_updated(
    admin_client, acme, flow, sent_events, django_capture_on_commit_callbacks
):
    exported = _exported_flow(admin_client, flow)

    response = _import_flow(
        admin_client,
        exported,
        django_capture_on_commit_callbacks,
        preserve_uuids=True,
        replace_existing=True,
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert Graph.objects.filter(org=acme).count() == 1
    [event] = _hook_events(sent_events)
    assert _target(event) == ("updated", "flow", str(flow.pk), "Billing flow")


def test_flow_import_of_a_file_without_flows_records_nothing(
    admin_client, flow, sent_events, django_capture_on_commit_callbacks
):
    exported = json.loads(_exported_flow(admin_client, flow))
    exported["Flow"] = []

    response = _import_flow(
        admin_client, json.dumps(exported).encode(), django_capture_on_commit_callbacks
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert sent_events == []


# ---- RAG settings, chunking and indexing ----


def test_naive_rag_create_records_the_rag_created_under_its_collection(
    admin_client, acme, collection, sent_events, django_capture_on_commit_callbacks
):
    response = _send(
        admin_client,
        "post",
        f"/api/naive-rag/collections/{collection.collection_id}/naive-rag/",
        django_capture_on_commit_callbacks,
        {"embedder_id": _embedder(acme).id},
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    rag = NaiveRag.objects.get(base_rag_type__source_collection=collection)
    [event] = _hook_events(sent_events)
    assert _target(event) == ("created", "naive RAG", str(rag.pk), "Manuals")
    assert _parent(event) == ("source collection", str(collection.pk), "Manuals")


@pytest.mark.parametrize("change_embedder", [True, False], ids=["changed", "unchanged"])
def test_naive_rag_resave_records_the_collection_updated_only_when_changed(
    change_embedder, admin_client, acme, collection, sent_events, django_capture_on_commit_callbacks
):
    rag = _naive_rag(collection)
    embedder = _embedder(acme, name="Other embedder") if change_embedder else rag.embedder

    response = _send(
        admin_client,
        "post",
        f"/api/naive-rag/collections/{collection.collection_id}/naive-rag/",
        django_capture_on_commit_callbacks,
        {"embedder_id": embedder.id},
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    expected = [_collection_updated(collection)] if change_embedder else []
    assert [_target(event) for event in _hook_events(sent_events)] == expected


def test_graph_rag_create_records_the_rag_created_under_its_collection(
    admin_client, acme, collection, sent_events, django_capture_on_commit_callbacks
):
    response = _send(
        admin_client,
        "post",
        f"/api/graph-rag/collections/{collection.collection_id}/graph-rag/",
        django_capture_on_commit_callbacks,
        {"embedder_id": _embedder(acme).id, "llm_id": _llm_config(acme).id},
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    rag = GraphRag.objects.get(base_rag_type__source_collection=collection)
    [event] = _hook_events(sent_events)
    assert _target(event) == ("created", "graph RAG", str(rag.pk), "Manuals")
    assert _parent(event) == ("source collection", str(collection.pk), "Manuals")


@pytest.mark.parametrize("has_new_document", [True, False], ids=["new-document", "nothing-new"])
def test_document_config_initialize_records_the_collection_updated_only_when_it_created_one(
    has_new_document, admin_client, collection, sent_events, django_capture_on_commit_callbacks
):
    rag = _naive_rag(collection)
    if has_new_document:
        _document(collection)

    response = _send(
        admin_client,
        "post",
        f"/api/naive-rag/{rag.pk}/document-configs/initialize/",
        django_capture_on_commit_callbacks,
    )

    assert response.status_code in (status.HTTP_200_OK, status.HTTP_201_CREATED), response.content
    expected = [_collection_updated(collection)] if has_new_document else []
    assert [_target(event) for event in _hook_events(sent_events)] == expected


@pytest.mark.parametrize("chunk_size", [800, 1000], ids=["changed", "unchanged"])
def test_document_config_bulk_update_records_the_collection_updated_only_when_changed(
    chunk_size, admin_client, collection, sent_events, django_capture_on_commit_callbacks
):
    rag = _naive_rag(collection)
    config = _document_config(rag, collection)

    response = _send(
        admin_client,
        "put",
        f"/api/naive-rag/{rag.pk}/document-configs/bulk-update/",
        django_capture_on_commit_callbacks,
        [{"id": config.pk, "chunk_size": chunk_size}],
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    expected = [_collection_updated(collection)] if chunk_size != 1000 else []
    assert [_target(event) for event in _hook_events(sent_events)] == expected


def test_document_config_bulk_delete_records_the_collection_updated(
    admin_client, collection, sent_events, django_capture_on_commit_callbacks
):
    rag = _naive_rag(collection)
    config = _document_config(rag, collection)

    response = _send(
        admin_client,
        "post",
        f"/api/naive-rag/{rag.pk}/document-configs/bulk-delete/",
        django_capture_on_commit_callbacks,
        {"config_ids": [config.pk]},
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert [_target(event) for event in _hook_events(sent_events)] == [
        _collection_updated(collection)
    ]


@pytest.fixture
def knowledge_client(monkeypatch):
    """Replace the HTTP client of the knowledge service in both views that call it."""
    client = MagicMock()
    client.__enter__.return_value = client
    monkeypatch.setattr("tables.views.views.KnowledgeClient", lambda **_: client)
    monkeypatch.setattr(
        "tables.views.knowledge_views.naive_rag_views.KnowledgeClient", lambda **_: client
    )
    return client


@pytest.mark.usefixtures("knowledge_client")
def test_chunking_run_records_the_collection_updated(
    admin_client, collection, sent_events, django_capture_on_commit_callbacks
):
    rag = _naive_rag(collection)
    config = _document_config(rag, collection)

    response = _send(
        admin_client,
        "post",
        f"/api/naive-rag/{rag.pk}/document-configs/{config.pk}/process-chunking/",
        django_capture_on_commit_callbacks,
        {"chunk_strategy": "token", "chunk_size": 1000, "chunk_overlap": 150},
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert [_target(event) for event in _hook_events(sent_events)] == [
        _collection_updated(collection)
    ]


@pytest.mark.usefixtures("knowledge_client")
def test_indexing_run_records_the_collection_updated(
    admin_client, collection, sent_events, django_capture_on_commit_callbacks
):
    rag = _naive_rag(collection)
    _document(collection)

    response = _send(
        admin_client,
        "post",
        "/api/process-rag-indexing/",
        django_capture_on_commit_callbacks,
        {"rag_id": rag.pk, "rag_type": "naive", "document_config_ids": []},
    )

    assert response.status_code == status.HTTP_202_ACCEPTED, response.content
    assert [_target(event) for event in _hook_events(sent_events)] == [
        _collection_updated(collection)
    ]


@pytest.mark.parametrize("operation", ["index", "chunking"])
@pytest.mark.parametrize("was_running", [True, False], ids=["running", "nothing-running"])
def test_cancel_records_the_collection_updated_only_when_a_run_was_cancelled(
    operation,
    was_running,
    knowledge_client,
    admin_client,
    collection,
    sent_events,
    django_capture_on_commit_callbacks,
):
    rag = _naive_rag(collection)
    config = _document_config(rag, collection)
    if not was_running:
        knowledge_client.cancel.side_effect = ClientResourceNotFoundError("nothing to cancel")
    url = (
        f"/api/process-rag-indexing/naive/{rag.pk}/cancel/"
        if operation == "index"
        else f"/api/naive-rag/{rag.pk}/document-configs/{config.pk}/process-chunking/cancel/"
    )

    response = _send(admin_client, "delete", url, django_capture_on_commit_callbacks)

    assert response.status_code == status.HTTP_204_NO_CONTENT, response.content
    expected = [_collection_updated(collection)] if was_running else []
    assert [_target(event) for event in _hook_events(sent_events)] == expected


# ---- flow assistant, default models, voice channel ----


def test_flow_assistant_settings_change_records_the_flow_updated_once(
    admin_client, acme, flow, sent_events, django_capture_on_commit_callbacks
):
    llm_config = _llm_config(acme)
    url = f"/api/flow-assistants/{flow.id}/"

    changed = _send(
        admin_client, "patch", url, django_capture_on_commit_callbacks, {"llm_config": llm_config.id}
    )
    assert changed.status_code == status.HTTP_200_OK, changed.content
    unchanged = _send(
        admin_client, "patch", url, django_capture_on_commit_callbacks, {"llm_config": llm_config.id}
    )

    assert unchanged.status_code == status.HTTP_200_OK, unchanged.content
    assert [_target(event) for event in _hook_events(sent_events)] == [
        ("updated", "flow", str(flow.pk), "Billing flow")
    ]


def test_default_models_change_records_them_updated_once(
    superadmin_in_acme, acme, sent_events, django_capture_on_commit_callbacks
):
    llm_config = _llm_config(acme)
    body = {"agent_llm_config": llm_config.id}

    changed = _send(
        superadmin_in_acme, "put", "/api/default-models/", django_capture_on_commit_callbacks, body
    )
    assert changed.status_code == status.HTTP_200_OK, changed.content
    unchanged = _send(
        superadmin_in_acme, "put", "/api/default-models/", django_capture_on_commit_callbacks, body
    )

    assert unchanged.status_code == status.HTTP_200_OK, unchanged.content
    default_models = DefaultModels.objects.get(org=acme)
    assert [(*_target(event), event.org_id) for event in _hook_events(sent_events)] == [
        ("updated", "default models", str(default_models.pk), None, acme.id)
    ]


def test_twilio_webhook_configuration_records_the_voice_channel_updated(
    admin_client, acme, sent_events, django_capture_on_commit_callbacks
):
    channel = RealtimeChannel.objects.create(name="Support line", org=acme)
    trigger = WebhookTrigger.objects.create(
        path="support-voice", provider_type=ProviderType.NGROK, org=acme
    )
    NgrokWebhookConfig.objects.create(
        trigger=trigger,
        name="tunnel",
        auth_token_secret=secret_service.create(text="ngrok", org=acme, name="NGROK_TOKEN"),
        region=NgrokWebhookConfig.Region.EU,
        domain="support.example.ngrok.io",
    )
    TwilioChannel.objects.create(
        channel=channel,
        account_sid="AC" + "0" * 32,
        auth_token_secret=secret_service.create(text="twilio", org=acme, name="TWILIO_TOKEN"),
        webhook_trigger=trigger,
    )

    with patch("tables.services.twilio_service._twilio_request"):
        response = _send(
            admin_client,
            "post",
            "/api/twilio/configure-webhook/",
            django_capture_on_commit_callbacks,
            {"phone_sid": "PN" + "0" * 32, "channel_token": str(channel.token)},
        )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert [_target(event) for event in _hook_events(sent_events)] == [
        ("updated", "realtime channel", str(channel.pk), "Support line")
    ]


# ---- bulk deletes ----


def test_session_bulk_delete_records_each_session_deleted_under_its_flow(
    admin_client, flow, sent_events, django_capture_on_commit_callbacks
):
    session = Session.objects.create(graph=flow, status=Session.SessionStatus.END)
    session_id = session.id

    response = _send(
        admin_client,
        "post",
        "/api/sessions/bulk_delete/",
        django_capture_on_commit_callbacks,
        {"ids": [session_id]},
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert not Session.objects.filter(id=session_id).exists()
    [event] = _hook_events(sent_events)
    assert _target(event) == ("deleted", "session", str(session_id), None)
    assert _parent(event) == ("flow", str(flow.pk), "Billing flow")


def test_bulk_delete_of_a_config_deleted_for_good_records_it_by_name(
    admin_client, acme, sent_events, django_capture_on_commit_callbacks
):
    llm_config = _llm_config(acme)
    llm_config_id = llm_config.id

    response = _send(
        admin_client,
        "post",
        "/api/llm-configs/bulk-delete/",
        django_capture_on_commit_callbacks,
        {"ids": [llm_config_id]},
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert not LLMConfig.objects.filter(id=llm_config_id).exists()
    assert [_target(event) for event in _hook_events(sent_events)] == [
        ("deleted", "LLM config", str(llm_config_id), "Writer LLM")
    ]


@pytest.mark.parametrize(
    "method, url, body",
    [
        ("post", "/api/llm-configs/bulk-delete/?dry_run=true", "llm-config"),
        ("post", "/api/llm-configs/bulk-delete/", {"ids": [987654]}),
        ("post", "/api/mcp-tools/bulk-delete/", {"ids": [987654]}),
        ("post", "/api/source-collections/bulk-delete/", {"collection_ids": [987654]}),
        ("post", "/api/sessions/bulk_delete/", {"ids": [987654]}),
        ("post", "/api/graphs/recycle-bin/restore/", {"all": True}),
        ("post", "/api/storage/recycle-bin/restore/", {"all": True}),
        ("delete", "/api/storage/delete/", {"paths": ["nothing/here.txt"]}),
    ],
    ids=[
        "dry-run",
        "bulk-delete-of-unknown-ids",
        "tool-bulk-delete-of-unknown-ids",
        "collection-bulk-delete-of-unknown-ids",
        "session-bulk-delete-of-unknown-ids",
        "restore-of-an-empty-bin",
        "storage-restore-of-an-empty-bin",
        "storage-delete-of-a-missing-path",
    ],
)
def test_a_bulk_request_that_changes_nothing_records_nothing(
    method, url, body, admin_client, acme, sent_events, django_capture_on_commit_callbacks
):
    if body == "llm-config":
        body = {"ids": [_llm_config(acme).id]}

    with patch(
        "tables.views.storage_views.get_storage_manager",
        return_value=StorageManager(InMemoryStorageBackend(organization_prefix="")),
    ):
        response = _send(admin_client, method, url, django_capture_on_commit_callbacks, body)

    assert response.status_code < status.HTTP_400_BAD_REQUEST, response.content
    assert sent_events == []


# ---- profile ----


@pytest.fixture
def admin_in_two_orgs(admin_acme, beta, role_member):
    OrganizationUser.objects.create(user=admin_acme, org=beta, role=role_member)
    return admin_acme


def test_profile_change_records_the_user_updated_in_each_of_their_orgs(
    client_as, admin_in_two_orgs, acme, beta, sent_events, django_capture_on_commit_callbacks
):
    client = client_as(admin_in_two_orgs)
    response = _send(
        client, "patch", "/api/profile/", django_capture_on_commit_callbacks, {"display_name": "Ada"}
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    events = _hook_events(sent_events)
    assert sorted((event.org_id, *_target(event)) for event in events) == sorted(
        (org.id, "updated", "user", str(admin_in_two_orgs.pk), admin_in_two_orgs.email)
        for org in (acme, beta)
    )


@pytest.mark.parametrize(
    "method, url, body",
    [
        ("patch", "/api/profile/", "same-display-name"),
        ("delete", "/api/profile/avatar/", None),
    ],
    ids=["same-display-name", "remove-a-missing-avatar"],
)
def test_profile_request_that_changes_nothing_records_nothing(
    method, url, body, client_as, admin_acme, sent_events, django_capture_on_commit_callbacks
):
    if body == "same-display-name":
        body = {"display_name": admin_acme.display_name}

    response = _send(client_as(admin_acme), method, url, django_capture_on_commit_callbacks, body)

    assert response.status_code < status.HTTP_400_BAD_REQUEST, response.content
    assert sent_events == []


def test_password_change_records_the_password_reset_of_the_user(
    client_as, admin_acme, acme, sent_events, django_capture_on_commit_callbacks
):
    client = client_as(admin_acme)
    ticket = client.post(
        "/api/profile/password-change/request/",
        {"current_password": "StrongPass123!"},
        format="json",
    ).json()["ticket"]

    response = _send(
        client,
        "post",
        "/api/profile/password-change/confirm/",
        django_capture_on_commit_callbacks,
        {"ticket": ticket, "new_password": "BrandNewPass456!"},
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert [(event.org_id, *_target(event)) for event in _hook_events(sent_events)] == [
        (acme.id, "password_reset", "user", str(admin_acme.pk), admin_acme.email)
    ]


# ---- collections, flow versions and RAG rows named by the fallback through their URL ----


@pytest.mark.parametrize(
    "body, expected",
    [
        ({"collection_name": "Manuals"}, []),
        ({"collection_name": "Handbooks"}, [("renamed", "Handbooks", "Manuals")]),
        ({"description": "Product manuals"}, [("updated", "Manuals", None)]),
    ],
    ids=["unchanged", "renamed", "description-changed"],
)
def test_collection_update_records_only_a_real_change(
    body, expected, admin_client, collection, sent_events, django_capture_on_commit_callbacks
):
    response = _send(
        admin_client,
        "patch",
        f"/api/source-collections/{collection.collection_id}/",
        django_capture_on_commit_callbacks,
        body,
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert [
        (event.action, event.target_name, event.previous_name)
        for event in _hook_events(sent_events)
    ] == expected
    assert {event.target_type for event in sent_events} <= {"source collection"}


def test_fallback_types_a_view_that_defines_only_get_queryset(
    admin_client, flow, sent_events, django_capture_on_commit_callbacks
):
    version = GraphVersion.objects.create(graph=flow, name="Before refactor", snapshot={})

    response = _send(
        admin_client,
        "patch",
        f"/api/graph-versions/{version.pk}/",
        django_capture_on_commit_callbacks,
        {"name": "After refactor"},
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    [event] = sent_events
    assert (event.target_type, event.target_id) == ("flow version", str(version.pk))


def test_fallback_names_a_document_config_after_its_document(
    admin_client, collection, sent_events, django_capture_on_commit_callbacks
):
    rag = _naive_rag(collection)
    config = _document_config(rag, collection)

    response = _send(
        admin_client,
        "put",
        f"/api/naive-rag/{rag.pk}/document-configs/{config.pk}/",
        django_capture_on_commit_callbacks,
        {"chunk_size": 1200},
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    [event] = sent_events
    assert _target(event) == (
        "updated",
        "document chunking settings",
        str(config.pk),
        "guide.txt",
    )
    assert _parent(event) == ("document", str(config.document_id), "guide.txt")


def test_fallback_names_a_graph_rag_after_its_collection(
    admin_client, acme, collection, sent_events, django_capture_on_commit_callbacks
):
    rag = GraphRagService.create_or_update_graph_rag(
        collection.collection_id, _embedder(acme).id, _llm_config(acme).id
    )

    response = _send(
        admin_client,
        "put",
        f"/api/graph-rag/{rag.pk}/index-config/",
        django_capture_on_commit_callbacks,
        {"chunk_size": rag.index_config.chunk_size + 100},
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    [event] = sent_events
    assert _target(event) == ("update_index_config", "graph RAG", str(rag.pk), "Manuals")
    assert _parent(event) == ("source collection", str(collection.pk), "Manuals")


def test_fallback_never_names_a_rag_of_another_org(
    admin_acme, acme, beta, sent_events, django_capture_on_commit_callbacks
):
    beta_collection = SourceCollection.objects.create(collection_name="Beta secrets", org=beta)
    beta_rag = _naive_rag(beta_collection)
    view = NaiveRagViewSet.as_view({"delete": "destroy"})
    request = RequestFactory().delete(f"/api/naive-rag/{beta_rag.pk}/")
    request.user = admin_acme
    request._rbac_active_org_id = acme.id

    def get_response(request_in_view):
        request_in_view.resolver_match = ResolverMatch(
            view, (), {"pk": str(beta_rag.pk)}, route="api/^naive-rag/(?P<pk>[^/.]+)/$"
        )
        return HttpResponse()

    with django_capture_on_commit_callbacks(execute=True):
        UserActionMiddleware(get_response)(request)

    [event] = sent_events
    assert (_target(event), _parent(event)) == (
        ("deleted", "naive RAG", str(beta_rag.pk), None),
        (None, None, None),
    )
