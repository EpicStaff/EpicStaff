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
from utils.request_target import model_of, url_path_pattern

pytestmark = pytest.mark.django_db

WRITE_METHODS = ("post", "put", "patch", "delete")

# Every write route that changes something, other than DRF's generic create, update,
# partial_update and destroy, which change their row by definition, is in one of the two
# sets below. A write route that changes nothing gets `@reads_only` on its handler, one
# that only keeps a run's own state `@not_a_user_change`.
#
# Routes the middleware's fallback may record: their URL names the changed object by
# `<pk>` or `<id>`, which the fallback resolves to a type and name. Many are recorded by a
# hook first; the fallback covers the rest, provided the request has a checked org.
FALLBACK_RECORDED_ROUTES = frozenset(
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
        "POST api/audit-filter-presets/<pk>/copy/",
        "PUT api/classification-decision-table-node/<pk>/explanations/",
        "DELETE api/graph-rag/<pk>/documents/<document_id>/",
        "POST api/graph-rag/<pk>/documents/bulk-delete/",
        "POST api/graph-rag/<pk>/documents/initialize/",
        "PUT api/graph-rag/<pk>/index-config/",
        "POST api/graph-versions/<pk>/create-graph/",
        "POST api/graph-versions/<pk>/restore/",
        "POST api/graphs/<pk>/copy/",
        "POST api/graphs/<pk>/partial-import/",
        "DELETE api/graphs/<pk>/purge/",
        "POST api/graphs/<pk>/restore/",
        "POST api/graphs/<pk>/save/",
        "DELETE api/key-value-tables/<pk>/purge/",
        "POST api/key-value-tables/<pk>/restore/",
        "POST api/mcp-tools/<pk>/copy/",
        "DELETE api/mcp-tools/<pk>/purge/",
        "POST api/mcp-tools/<pk>/restore/",
        "POST api/python-code-tool/<pk>/copy/",
        "DELETE api/python-code-tool/<pk>/purge/",
        "POST api/python-code-tool/<pk>/restore/",
        "DELETE api/realtime-channels/<pk>/purge/",
        "POST api/realtime-channels/<pk>/restore/",
        "DELETE api/secrets/<pk>/purge/",
        "POST api/secrets/<pk>/restore/",
        "POST api/source-collections/<pk>/copy/",
        "DELETE api/source-collections/<pk>/purge/",
        "POST api/source-collections/<pk>/restore/",
        "DELETE api/surfaces/<pk>/purge/",
        "POST api/surfaces/<pk>/restore/",
        "POST api/telegram-trigger-nodes/<pk>/register-webhook/",
        "DELETE api/webhook-triggers/<pk>/purge/",
        "POST api/webhook-triggers/<pk>/restore/",
    }
)

# Routes whose URL does not name what they change, so a fallback record would name no
# target: an explicit hook records each changed object, and marks a request that changed
# nothing handled so the fallback stays out.
HOOK_RECORDED_ROUTES = frozenset(
    {
        # RecycleBinBulkService and StorageRecycleBinService: RestoreService and
        # PurgeService record each item; RecycleBinEmptyView purges through them.
        "POST api/agent-definitions/recycle-bin/purge/",
        "POST api/agent-definitions/recycle-bin/restore/",
        "POST api/graphs/recycle-bin/purge/",
        "POST api/graphs/recycle-bin/restore/",
        "POST api/key-value-tables/recycle-bin/purge/",
        "POST api/key-value-tables/recycle-bin/restore/",
        "POST api/mcp-tools/recycle-bin/purge/",
        "POST api/mcp-tools/recycle-bin/restore/",
        "POST api/python-code-tool/recycle-bin/purge/",
        "POST api/python-code-tool/recycle-bin/restore/",
        "POST api/realtime-channels/recycle-bin/purge/",
        "POST api/realtime-channels/recycle-bin/restore/",
        "POST api/secrets/recycle-bin/purge/",
        "POST api/secrets/recycle-bin/restore/",
        "POST api/source-collections/recycle-bin/purge/",
        "POST api/source-collections/recycle-bin/restore/",
        "POST api/storage/recycle-bin/purge/",
        "POST api/storage/recycle-bin/restore/",
        "POST api/surfaces/recycle-bin/purge/",
        "POST api/surfaces/recycle-bin/restore/",
        "POST api/webhook-triggers/recycle-bin/purge/",
        "POST api/webhook-triggers/recycle-bin/restore/",
        "POST api/recycle-bin/empty/",
        # BulkDeleteMixin: DeleteService records each binned row, BaseDeleteService each
        # row it deletes for good.
        "POST api/elevenlabs-realtime-configs/bulk-delete/",
        "POST api/embedding-configs/bulk-delete/",
        "POST api/gemini-realtime-configs/bulk-delete/",
        "POST api/graph-versions/bulk-delete/",
        "POST api/graphs/bulk-delete/",
        "POST api/llm-configs/bulk-delete/",
        "POST api/openai-realtime-configs/bulk-delete/",
        "POST api/system-one-configs/bulk-delete/",
        # move_to_recycle_bin (DeleteService) records each binned row.
        "POST api/mcp-tools/bulk-delete/",
        "POST api/python-code-tool/bulk-delete/",
        "POST api/source-collections/bulk-delete/",
        "DELETE api/graphs/uuid/<graph_uuid>/",
        # SessionViewSet.bulk_delete records each deleted session under its flow.
        "POST api/sessions/bulk_delete/",
        # ImportService records each main entity the file creates.
        "POST api/agent-definitions/import/",
        "POST api/audit-filter-presets/import/",
        "POST api/graphs/import/",
        "POST api/mcp-tools/import/",
        "POST api/python-code-tool/import/",
        # DocumentManagementService records each uploaded, copied or deleted document
        # under its collection.
        "POST api/documents/bulk-delete/",
        "POST api/documents/copy/",
        "POST api/documents/source-collection/<collection_id>/from-storage/",
        "POST api/documents/source-collection/<collection_id>/upload/",
        # record_rag_change records the collection a RAG change belongs to; a created RAG
        # is recorded under its collection by NaiveRagService and GraphRagService.
        "POST api/graph-rag/collections/<collection_id>/graph-rag/",
        "POST api/naive-rag/collections/<collection_id>/naive-rag/",
        "DELETE api/naive-rag/<naive_rag_id>/document-configs/<document_config_id>/process-chunking/cancel/",
        "POST api/naive-rag/<naive_rag_id>/document-configs/<document_config_id>/process-chunking/",
        "POST api/naive-rag/<naive_rag_id>/document-configs/bulk-delete/",
        "PUT api/naive-rag/<naive_rag_id>/document-configs/bulk-update/",
        "POST api/naive-rag/<naive_rag_id>/document-configs/initialize/",
        "POST api/process-rag-indexing/",
        "DELETE api/process-rag-indexing/<rag_type>/<rag_id>/cancel/",
        # StorageFileSync and StorageAPIView record each storage entry and flow they change.
        "POST api/storage/add-to-graph/",
        "POST api/storage/copy/",
        "DELETE api/storage/delete/",
        "POST api/storage/mkdir/",
        "POST api/storage/move/",
        "DELETE api/storage/remove-from-graph/",
        "POST api/storage/rename/",
        # Record the flow, the default models and the voice channel they update.
        "PATCH api/flow-assistants/<graph_id>/",
        "PUT api/default-models/",
        "POST api/twilio/configure-webhook/",
        # QuickstartService records what it creates and applies.
        "POST api/quickstart/",
        "POST api/quickstart/apply/",
        # Record the user in each of their orgs: the profile views, ApiKeyService, and
        # the password resets in rbac.views.auth.
        "PATCH api/profile/",
        "DELETE api/profile/avatar/",
        "POST api/profile/avatar/",
        "POST api/profile/password-change/confirm/",
        "POST api/profile/api-keys/",
        "DELETE api/profile/api-keys/<key_id>/",
        "POST api/profile/api-keys/<key_id>/revoke/",
        "POST api/auth/admin/password-reset/",
        "POST api/auth/password-reset/confirm/",
        # Records the chat service's desk changes itself, under the user who made them.
        "POST api/internal/user-actions/",
    }
)


def _url_patterns(patterns, prefix=""):
    for pattern in patterns:
        if isinstance(pattern, URLResolver):
            yield from _url_patterns(pattern.url_patterns, prefix + str(pattern.pattern))
        elif isinstance(pattern, URLPattern):
            yield prefix + str(pattern.pattern), pattern.callback


def _write_handlers(*, include_generic_actions=False):
    """(route key, view class, handler name, DRF actions or None) of every write method a
    view serves, skipping the `.json` format-suffix twins, and DRF's generic actions unless
    asked for."""
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
            if actions is not None and name in GENERIC_ACTIONS and not include_generic_actions:
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
    classified = FALLBACK_RECORDED_ROUTES | HOOK_RECORDED_ROUTES
    unclassified = sorted(
        key
        for key, view_class, name, _route, _actions in _write_handlers()
        if not handler_reads_only(view_class, name)
        and not _excluded(view_class, name)
        and key not in classified
    )

    assert unclassified == [], (
        "Classify each new write route. If it changes nothing, mark its handler with "
        "user_audit.read_only.reads_only (or not_a_user_change for a run's own state). If "
        "its URL names the changed object by <pk> or <id>, add it to "
        "FALLBACK_RECORDED_ROUTES. Otherwise the fallback would record it with no target: "
        "record each changed object with user_audit.recorder.record_user_action (and call "
        "mark_request_handled when nothing changed), then add it to HOOK_RECORDED_ROUTES."
    )


def test_fallback_recorded_routes_name_their_target_in_the_url():
    unnamed = sorted(
        route for route in FALLBACK_RECORDED_ROUTES if "<pk>" not in route and "<id>" not in route
    )

    assert unnamed == [], (
        "The fallback names a target only from a <pk> or <id> URL kwarg. Record these routes "
        "with an explicit hook and move them to HOOK_RECORDED_ROUTES."
    )


def test_every_view_the_fallback_records_names_its_model():
    """The fallback types and names its target through `model_of`, so a view it records
    must declare its model: a class `queryset` (`Model.objects.none()` when the view only
    defines `get_queryset`) or `serializer_class`."""
    unresolvable = sorted(
        {
            f"{key} ({view_class.__name__})"
            for key, view_class, name, _route, actions in _write_handlers(
                include_generic_actions=True
            )
            if (key in FALLBACK_RECORDED_ROUTES or (actions is not None and name in GENERIC_ACTIONS))
            and not handler_reads_only(view_class, name)
            and not _excluded(view_class, name)
            and model_of(view_class) is None
        }
    )

    assert unresolvable == [], (
        "The fallback cannot tell what these routes change. Give the view a class "
        "`queryset = Model.objects.none()` (it may keep its get_queryset), or record the "
        "route with an explicit hook and list it in HOOK_RECORDED_ROUTES."
    )


def test_classified_routes_list_only_live_unmarked_routes():
    live = {
        key
        for key, view_class, name, _route, _actions in _write_handlers()
        if not handler_reads_only(view_class, name) and not _excluded(view_class, name)
    }

    assert sorted((FALLBACK_RECORDED_ROUTES | HOOK_RECORDED_ROUTES) - live) == []
    assert FALLBACK_RECORDED_ROUTES.isdisjoint(HOOK_RECORDED_ROUTES)


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
