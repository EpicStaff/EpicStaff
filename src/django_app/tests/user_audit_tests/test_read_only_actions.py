"""Write-method requests that change nothing record nothing, and every write route is
either recorded as a change or declared read-only.

The HTTP tests are presentation tests through real endpoints; only the object store and
the knowledge service's HTTP call are replaced. The route tests read the URL resolver.
"""

from unittest.mock import patch

import httpx
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpResponse
from django.test import RequestFactory
from django.urls import ResolverMatch, get_resolver
from django.urls.resolvers import URLPattern, URLResolver
from rest_framework import status

from tables.models import Graph, SourceCollection
from tables.models.knowledge_models import BaseRagType, NaiveRag
from tables.services.storage_service.manager import StorageManager
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403
from tests.storage_tests.in_memory_backend import InMemoryStorageBackend, seed_file
from user_audit.middleware import (
    FALLBACK_EXCLUDED_ACTIONS,
    FALLBACK_EXCLUDED_VIEWS,
    GENERIC_ACTIONS,
    UserActionMiddleware,
)
from user_audit.read_only import handler_reads_only
from utils.request_target import url_path_pattern

pytestmark = pytest.mark.django_db

WRITE_METHODS = ("post", "put", "patch", "delete")

# Every write route that changes something, other than DRF's generic create, update,
# partial_update and destroy, which change their row by definition. The fallback or a
# layer-2 hook records each one, provided the request has a checked org (the admin and
# internal routes mostly have none). A new write route belongs here when it changes
# something, and gets `@reads_only` on its handler when it does not.
CHANGING_WRITE_ROUTES = frozenset(
    {
        "POST api/admin/api-keys/<pk>/revoke/",
        "POST api/admin/organizations/<pk>/deactivate/",
        "POST api/admin/organizations/<pk>/reactivate/",
        "POST api/admin/users/<pk>/deactivate/",
        "POST api/admin/users/<pk>/grant-superadmin/",
        "POST api/admin/users/<pk>/reactivate/",
        "POST api/admin/users/<pk>/revoke-superadmin/",
        "DELETE api/agent-definitions/<pk>/purge/",
        "POST api/agent-definitions/<pk>/restore/",
        "POST api/agent-definitions/recycle-bin/purge/",
        "POST api/agent-definitions/recycle-bin/restore/",
        "POST api/audit-filter-presets/<pk>/copy/",
        "POST api/audit-filter-presets/import/",
        "POST api/auth/admin/password-reset/",
        "POST api/auth/first-setup/",
        "POST api/auth/password-reset/confirm/",
        "POST api/auth/password-reset/request/",
        "POST api/auth/reset-user/",
        "PUT api/classification-decision-table-node/<pk>/explanations/",
        "PUT api/default-models/",
        "POST api/documents/bulk-delete/",
        "POST api/documents/copy/",
        "POST api/documents/source-collection/<collection_id>/from-storage/",
        "POST api/documents/source-collection/<collection_id>/upload/",
        "POST api/elevenlabs-realtime-configs/bulk-delete/",
        "POST api/embedding-configs/bulk-delete/",
        "PATCH api/flow-assistants/<graph_id>/",
        "POST api/flow-assistants/<graph_id>/conversations/",
        "DELETE api/flow-assistants/<graph_id>/conversations/<conversation_id>/",
        "POST api/flow-assistants/<graph_id>/conversations/<conversation_id>/cancel/",
        "POST api/flow-assistants/<graph_id>/conversations/<conversation_id>/messages/",
        "POST api/gemini-realtime-configs/bulk-delete/",
        "DELETE api/graph-rag/<pk>/documents/<document_id>/",
        "POST api/graph-rag/<pk>/documents/bulk-delete/",
        "POST api/graph-rag/<pk>/documents/initialize/",
        "PUT api/graph-rag/<pk>/index-config/",
        "POST api/graph-rag/collections/<collection_id>/graph-rag/",
        "POST api/graph-versions/<pk>/create-graph/",
        "POST api/graph-versions/<pk>/restore/",
        "POST api/graph-versions/bulk-delete/",
        "POST api/graphs/<pk>/copy/",
        "POST api/graphs/<pk>/partial-import/",
        "DELETE api/graphs/<pk>/purge/",
        "POST api/graphs/<pk>/restore/",
        "POST api/graphs/<pk>/save/",
        "POST api/graphs/bulk-delete/",
        "POST api/graphs/import/",
        "POST api/graphs/recycle-bin/purge/",
        "POST api/graphs/recycle-bin/restore/",
        "DELETE api/graphs/uuid/<graph_uuid>/",
        "POST api/init-realtime/",
        # Crew's key-value calls share one handler; `read` changes nothing, but none of
        # them is recorded: the system key's requests have no checked org.
        "POST api/internal/sessions/<session_id>/key-value-tables/<table_id>/delete/",
        "POST api/internal/sessions/<session_id>/key-value-tables/<table_id>/read/",
        "POST api/internal/sessions/<session_id>/key-value-tables/<table_id>/write/",
        "DELETE api/key-value-tables/<pk>/purge/",
        "POST api/key-value-tables/<pk>/restore/",
        "POST api/key-value-tables/recycle-bin/purge/",
        "POST api/key-value-tables/recycle-bin/restore/",
        "POST api/llm-configs/bulk-delete/",
        "POST api/mcp-tools/<pk>/copy/",
        "DELETE api/mcp-tools/<pk>/purge/",
        "POST api/mcp-tools/<pk>/restore/",
        "POST api/mcp-tools/bulk-delete/",
        "POST api/mcp-tools/import/",
        "POST api/mcp-tools/recycle-bin/purge/",
        "POST api/mcp-tools/recycle-bin/restore/",
        "DELETE api/naive-rag/<naive_rag_id>/document-configs/<document_config_id>/process-chunking/cancel/",
        "POST api/naive-rag/<naive_rag_id>/document-configs/<document_config_id>/process-chunking/",
        "POST api/naive-rag/<naive_rag_id>/document-configs/bulk-delete/",
        "PUT api/naive-rag/<naive_rag_id>/document-configs/bulk-update/",
        "POST api/naive-rag/<naive_rag_id>/document-configs/initialize/",
        "POST api/naive-rag/collections/<collection_id>/naive-rag/",
        # Sends mail: no change to the org's data, but an act, not a read.
        "POST api/notify/email/",
        "POST api/openai-realtime-configs/bulk-delete/",
        "POST api/process-rag-indexing/",
        "DELETE api/process-rag-indexing/<rag_type>/<rag_id>/cancel/",
        "PATCH api/profile/",
        "POST api/profile/api-keys/",
        "DELETE api/profile/api-keys/<key_id>/",
        "POST api/profile/api-keys/<key_id>/revoke/",
        "DELETE api/profile/avatar/",
        "POST api/profile/avatar/",
        "POST api/profile/password-change/confirm/",
        "POST api/profile/password-change/request/",
        "POST api/profile/tours/<tour_key>/complete/",
        "POST api/python-code-tool/<pk>/copy/",
        "DELETE api/python-code-tool/<pk>/purge/",
        "POST api/python-code-tool/<pk>/restore/",
        "POST api/python-code-tool/bulk-delete/",
        "POST api/python-code-tool/import/",
        "POST api/python-code-tool/recycle-bin/purge/",
        "POST api/python-code-tool/recycle-bin/restore/",
        "POST api/quickstart/",
        "POST api/quickstart/apply/",
        "POST api/realtime-agent-chats/end/",
        "DELETE api/realtime-channels/<pk>/purge/",
        "POST api/realtime-channels/<pk>/restore/",
        "POST api/realtime-channels/recycle-bin/purge/",
        "POST api/realtime-channels/recycle-bin/restore/",
        "POST api/recycle-bin/empty/",
        "POST api/run-python-code/",
        "POST api/run-session/",
        "POST api/run-session/test/",
        "DELETE api/secrets/<pk>/purge/",
        "POST api/secrets/<pk>/restore/",
        "POST api/secrets/recycle-bin/purge/",
        "POST api/secrets/recycle-bin/restore/",
        "POST api/sessions/<session_id>/stop/",
        "POST api/sessions/bulk_delete/",
        "POST api/source-collections/<pk>/copy/",
        "DELETE api/source-collections/<pk>/purge/",
        "POST api/source-collections/<pk>/restore/",
        "POST api/source-collections/bulk-delete/",
        "POST api/source-collections/recycle-bin/purge/",
        "POST api/source-collections/recycle-bin/restore/",
        "POST api/storage/add-to-graph/",
        "POST api/storage/copy/",
        "DELETE api/storage/delete/",
        "POST api/storage/mkdir/",
        "POST api/storage/move/",
        "POST api/storage/recycle-bin/purge/",
        "POST api/storage/recycle-bin/restore/",
        "DELETE api/storage/remove-from-graph/",
        "POST api/storage/rename/",
        "DELETE api/surfaces/<pk>/purge/",
        "POST api/surfaces/<pk>/restore/",
        "POST api/surfaces/recycle-bin/purge/",
        "POST api/surfaces/recycle-bin/restore/",
        "POST api/telegram-trigger-nodes/<pk>/register-webhook/",
        "POST api/twilio/configure-webhook/",
        "DELETE api/webhook-triggers/<pk>/purge/",
        "POST api/webhook-triggers/<pk>/restore/",
        "POST api/webhook-triggers/recycle-bin/purge/",
        "POST api/webhook-triggers/recycle-bin/restore/",
    }
)


def _url_patterns(patterns, prefix=""):
    for pattern in patterns:
        if isinstance(pattern, URLResolver):
            yield from _url_patterns(pattern.url_patterns, prefix + str(pattern.pattern))
        elif isinstance(pattern, URLPattern):
            yield prefix + str(pattern.pattern), pattern.callback


def _write_handlers():
    """(route key, view class, handler name, DRF actions or None) of every write method a
    view serves, skipping DRF's generic actions and the `.json` format-suffix twins."""
    for route, callback in _url_patterns(get_resolver().url_patterns):
        view_class = getattr(callback, "cls", None)
        if view_class is None or "(?P<format>" in route:
            continue
        actions = getattr(callback, "actions", None)
        if actions is not None:
            handlers = [(method, name) for method, name in actions.items() if method in WRITE_METHODS]
        else:
            handlers = [(method, method) for method in WRITE_METHODS if hasattr(view_class, method)]
        for method, name in handlers:
            if actions is not None and name in GENERIC_ACTIONS:
                continue
            yield f"{method.upper()} {url_path_pattern(route)}", view_class, name, route, actions


def _excluded(view_class, handler_name: str) -> bool:
    return view_class in FALLBACK_EXCLUDED_VIEWS or handler_name in FALLBACK_EXCLUDED_ACTIONS


READ_ONLY_HANDLERS = sorted(
    {
        (key, view_class, name, route, tuple(sorted(actions.items())) if actions else None)
        for key, view_class, name, route, actions in _write_handlers()
        if handler_reads_only(view_class, name)
    },
    key=lambda handler: handler[0],
)


def test_every_write_route_is_classified():
    unclassified = sorted(
        key
        for key, view_class, name, _route, _actions in _write_handlers()
        if not handler_reads_only(view_class, name)
        and not _excluded(view_class, name)
        and key not in CHANGING_WRITE_ROUTES
    )

    assert unclassified == [], (
        "Each new write route either changes something (add it to CHANGING_WRITE_ROUTES) "
        "or only reads (mark its handler with user_audit.read_only.reads_only)."
    )


def test_changing_write_routes_lists_only_live_unmarked_routes():
    live = {
        key
        for key, view_class, name, _route, _actions in _write_handlers()
        if not handler_reads_only(view_class, name) and not _excluded(view_class, name)
    }

    assert sorted(CHANGING_WRITE_ROUTES - live) == []


@pytest.mark.parametrize(
    "key, view_class, handler_name, route, actions",
    READ_ONLY_HANDLERS,
    ids=[handler[0] for handler in READ_ONLY_HANDLERS],
)
def test_a_read_only_handler_records_nothing_in_the_fallback(
    key, view_class, handler_name, route, actions, admin_acme, acme, sent_events,
    django_capture_on_commit_callbacks,
):
    method = key.split(" ", 1)[0].lower()
    view = view_class.as_view(dict(actions)) if actions else view_class.as_view()
    request = getattr(RequestFactory(), method)(f"/{url_path_pattern(route)}")
    request.user = admin_acme
    request._rbac_active_org_id = acme.id

    def get_response(request_in_view):
        request_in_view.resolver_match = ResolverMatch(view, (), {}, route=route)
        return HttpResponse()

    with django_capture_on_commit_callbacks(execute=True):
        UserActionMiddleware(get_response)(request)

    assert sent_events == []


# ---- the read-only endpoints over HTTP ----


@pytest.fixture
def admin_client(client_as, admin_acme, acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


@pytest.fixture
def storage_manager(acme):
    manager = StorageManager(InMemoryStorageBackend(organization_prefix=""))
    with patch("tables.views.storage_views.get_storage_manager", return_value=manager):
        seed_file(manager._backend, acme.id, "reports/march.pdf", b"pdf")
        yield manager


@pytest.fixture
def knowledge_estimate(monkeypatch):
    """Answer the HTTP call to knowledge_new with a fixed estimate."""

    def fake_request(self, method, url, **kwargs):
        # litellm fetches its remote price map on first import; keep it offline.
        if str(url).startswith("http"):
            return httpx.Response(503, request=httpx.Request(method, str(url)))
        estimate = {"rag_type": "naive", "document_count": 0, "chunk_count": 0}
        return httpx.Response(200, json=estimate, request=httpx.Request(method, str(url)))

    monkeypatch.setattr(httpx.Client, "request", fake_request)


def _naive_rag(org, status_value=NaiveRag.NaiveRagStatus.COMPLETED) -> NaiveRag:
    collection = SourceCollection.objects.create(collection_name="Manuals", org=org)
    base = BaseRagType.objects.create(
        rag_type=BaseRagType.RagType.NAIVE, source_collection=collection
    )
    return NaiveRag.objects.create(base_rag_type=base, rag_status=status_value)


def _post_records_nothing(client, url, body, capture, sent_events, format="json"):
    with capture(execute=True):
        response = client.post(url, body, format=format)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert sent_events == []


@pytest.mark.usefixtures("storage_manager")
@pytest.mark.parametrize("url", ["/api/storage/download-zip/", "/api/storage/usage/"])
def test_storage_reads_sent_as_post_record_nothing(
    url, admin_client, sent_events, django_capture_on_commit_callbacks
):
    _post_records_nothing(
        admin_client,
        url,
        {"paths": ["reports/march.pdf"]},
        django_capture_on_commit_callbacks,
        sent_events,
    )


def test_import_inspect_records_nothing(
    admin_client, acme, sent_events, django_capture_on_commit_callbacks
):
    flow = Graph.objects.create(name="Billing flow", org=acme)
    exported = admin_client.get(f"/api/graphs/{flow.id}/export/")
    assert exported.status_code == status.HTTP_200_OK, exported.content
    upload = SimpleUploadedFile("flow.json", exported.content, content_type="application/json")

    _post_records_nothing(
        admin_client,
        "/api/graphs/import/inspect/",
        {"file": upload},
        django_capture_on_commit_callbacks,
        sent_events,
        format="multipart",
    )


def test_naive_rag_suggest_params_records_nothing(
    admin_client, acme, sent_events, django_capture_on_commit_callbacks
):
    naive_rag = _naive_rag(acme)

    _post_records_nothing(
        admin_client,
        "/api/naive-rag/suggest-search-params/",
        {"knowledge_collection_id": naive_rag.base_rag_type.source_collection_id},
        django_capture_on_commit_callbacks,
        sent_events,
    )


@pytest.mark.usefixtures("knowledge_estimate")
def test_indexing_estimate_records_nothing(
    admin_client, acme, sent_events, django_capture_on_commit_callbacks
):
    naive_rag = _naive_rag(acme, NaiveRag.NaiveRagStatus.NEW)

    _post_records_nothing(
        admin_client,
        "/api/process-rag-indexing/estimate/",
        {"rag_id": naive_rag.naive_rag_id, "rag_type": "naive", "document_config_ids": []},
        django_capture_on_commit_callbacks,
        sent_events,
    )
