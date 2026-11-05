import io
import zipfile

import pytest
from django.http import HttpResponse
from django.test import RequestFactory
from django.urls import ResolverMatch, reverse
from rest_framework import status, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from rbac.models import OrganizationUser
from tables.models import AuditFilterPreset, Graph, Provider, SourceCollection, StorageFile
from tables.models.default_models import DefaultModels
from tables.services.quickstart_service import QuickstartService
from tables.services.storage_service.upload import admission, archive_upload, file_upload
from tables.views.model_view_sets import AuditFilterPresetViewSet, GraphViewSet
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403
from tests.storage_tests.in_memory_backend import InMemoryStorageBackend
from tests.storage_tests.storage_writes import stream_upload
from user_audit.middleware import FALLBACK_EXCLUDED_VIEWS, UserActionMiddleware

pytestmark = pytest.mark.django_db


@pytest.fixture
def flow(acme):
    return Graph.objects.create(name="Billing flow", org=acme)


@pytest.fixture
def admin_client(client_as, admin_acme, acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


@pytest.fixture
def admin_in_two_orgs(admin_acme, beta, role_member):
    OrganizationUser.objects.create(user=admin_acme, org=beta, role=role_member)
    return admin_acme


class _PlainChangeView(APIView):
    """A view the fallback has no reason to skip."""


class _CollectionViewSet(viewsets.GenericViewSet):
    """Serves source collections, which are named by `collection_name`."""

    queryset = SourceCollection.objects.all()


def _serve(request, *, view_class, actions=None, route="api/things/", kwargs=None):
    """Serve `request` through the middleware, resolved to `view_class` (a viewset with
    `actions`) as Django's handler resolves it, and answer 200."""
    view = view_class.as_view(actions) if actions else view_class.as_view()

    def get_response(request_in_view):
        request_in_view.resolver_match = ResolverMatch(view, (), kwargs or {}, route=route)
        return HttpResponse()

    return UserActionMiddleware(get_response)(request)


def _checked_request(user, org_id, *, method="post", path="/api/things/"):
    """A request whose org was checked, as `OrgContextService` leaves it."""
    request = getattr(RequestFactory(), method)(path)
    request.user = user
    request._rbac_active_org_id = org_id
    return request


def test_fallback_records_a_flow_copy_as_copied(
    admin_client, admin_acme, acme, flow, sent_events, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        response = admin_client.post(reverse("graphs-copy", args=[flow.pk]), {}, format="json")

    assert response.status_code == status.HTTP_201_CREATED, response.content
    [event] = sent_events
    assert (event.action, event.org_id, event.actor_user_id) == ("copied", acme.id, admin_acme.id)
    assert (event.target_type, event.target_id, event.target_name) == (
        "flow",
        str(flow.pk),
        "Billing flow",
    )
    assert event.route == "POST api/graphs/<pk>/copy/"


def test_fallback_skips_when_tracker_recorded(
    admin_client, flow, sent_events, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        response = admin_client.patch(
            reverse("graphs-detail", args=[flow.pk]),
            {"name": "Invoices flow", "save_version": flow.save_version},
            format="json",
        )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert [(event.action, event.route) for event in sent_events] == [("renamed", None)]


@pytest.mark.parametrize(
    "method, url_name, expected_status",
    [
        ("get", "graphs-detail", status.HTTP_200_OK),
        ("head", "graphs-detail", status.HTTP_200_OK),
        ("patch", "graphs-detail", status.HTTP_400_BAD_REQUEST),
        ("post", "graphs-copy", status.HTTP_404_NOT_FOUND),
    ],
)
def test_fallback_skips_safe_methods_and_failures(
    method,
    url_name,
    expected_status,
    admin_client,
    beta,
    flow,
    sent_events,
    django_capture_on_commit_callbacks,
):
    # The 404 copies another org's flow, which the caller cannot see; the 400 patches
    # without the save_version every update needs.
    target = (
        Graph.objects.create(name="Beta", org=beta)
        if expected_status == status.HTTP_404_NOT_FOUND
        else flow
    )
    with django_capture_on_commit_callbacks(execute=True):
        response = getattr(admin_client, method)(reverse(url_name, args=[target.pk]))

    assert response.status_code == expected_status
    assert sent_events == []


@pytest.mark.parametrize(
    "view_class",
    sorted(FALLBACK_EXCLUDED_VIEWS, key=lambda view_class: view_class.__name__),
    ids=lambda view_class: view_class.__name__,
)
def test_fallback_skips_excluded_views(
    view_class, admin_acme, acme, sent_events, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        _serve(_checked_request(admin_acme, acme.id), view_class=view_class)

    assert sent_events == []


def test_fallback_records_a_view_it_does_not_exclude(
    admin_acme, acme, sent_events, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        _serve(_checked_request(admin_acme, acme.id, method="delete"), view_class=_PlainChangeView)

    [event] = sent_events
    assert (event.action, event.org_id, event.route) == ("deleted", acme.id, "DELETE api/things/")
    assert event.target_type is None


@pytest.mark.parametrize(
    "method, drf_action, expected_action",
    [
        ("post", "create", "created"),
        ("put", "update", "updated"),
        ("patch", "partial_update", "updated"),
        ("delete", "destroy", "deleted"),
    ],
)
def test_fallback_records_a_generic_viewset_action_as_the_recorder_verb(
    method, drf_action, expected_action, admin_acme, acme, sent_events, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        _serve(
            _checked_request(admin_acme, acme.id, method=method),
            view_class=_CollectionViewSet,
            actions={method: drf_action},
        )

    [event] = sent_events
    assert event.action == expected_action


@pytest.mark.parametrize(
    "collection_name, expected_name", [("Contracts", "Contracts"), ("", None)]
)
def test_fallback_labels_a_collection_by_its_collection_name(
    collection_name, expected_name, admin_acme, acme, sent_events, django_capture_on_commit_callbacks
):
    collection = SourceCollection.objects.create(org=acme, collection_name="Contracts")
    # Saving fills an empty name in, so the empty case is written past save().
    SourceCollection.objects.filter(pk=collection.pk).update(collection_name=collection_name)

    with django_capture_on_commit_callbacks(execute=True):
        _serve(
            _checked_request(admin_acme, acme.id),
            view_class=_CollectionViewSet,
            actions={"post": "copy"},
            route="api/^source-collections/(?P<pk>[^/.]+)/copy/$",
            kwargs={"pk": str(collection.pk)},
        )

    [event] = sent_events
    assert (event.target_type, event.target_id, event.target_name) == (
        "source collection",
        str(collection.pk),
        expected_name,
    )


def test_fallback_keeps_a_custom_action_name(
    admin_acme, acme, sent_events, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        _serve(
            _checked_request(admin_acme, acme.id),
            view_class=_CollectionViewSet,
            actions={"post": "reindex"},
            route="api/^source-collections/reindex/$",
        )

    [event] = sent_events
    assert event.action == "reindex"


def test_quickstart_apply_records_the_default_models_update_and_no_fallback_record(
    admin_in_two_orgs, client_as, acme, sent_events, django_capture_on_commit_callbacks
):
    Provider.objects.create(name="openai")
    QuickstartService().quickstart(provider="openai", api_key="sk-test", org_id=acme.id, user=None)
    client = client_as(admin_in_two_orgs)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

    with django_capture_on_commit_callbacks(execute=True):
        response = client.post("/api/quickstart/apply/", {}, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    default_models = DefaultModels.objects.get(org=acme)
    assert [
        (event.action, event.org_id, event.actor_user_id, event.target_type, event.target_id, event.route)
        for event in sent_events
    ] == [("updated", acme.id, admin_in_two_orgs.id, "default models", str(default_models.pk), None)]


def test_fallback_names_an_untracked_generic_create_by_the_id_its_response_names(
    admin_client, acme, sent_events, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        response = admin_client.post(
            "/api/audit-filter-presets/",
            {"name": "Failed runs", "filter_body": {"query": "status = failed"}},
            format="json",
        )

    assert response.status_code == status.HTTP_201_CREATED, response.content
    preset = AuditFilterPreset.objects.get(org=acme, name="Failed runs")
    [event] = sent_events
    assert (
        event.action,
        event.target_type,
        event.target_id,
        event.target_name,
        event.route,
    ) == ("created", "audit filter preset", str(preset.pk), "Failed runs", "POST api/audit-filter-presets/")
    assert "status = failed" not in event.model_dump_json()


@pytest.mark.parametrize("response_data", ["other-org-row", {"name": "no id"}, None])
def test_fallback_names_no_create_target_it_cannot_find_in_the_org(
    response_data, admin_acme, acme, beta, sent_events, django_capture_on_commit_callbacks
):
    if response_data == "other-org-row":
        other_org_preset = AuditFilterPreset.objects.create(
            org=beta, created_by=admin_acme, name="Beta secret preset", filter_body={}
        )
        response_data = {"id": other_org_preset.pk}
    view = AuditFilterPresetViewSet.as_view({"post": "create"})

    def get_response(request_in_view):
        request_in_view.resolver_match = ResolverMatch(
            view, (), {}, route="api/^audit-filter-presets/$"
        )
        if response_data is None:
            return HttpResponse(status=status.HTTP_201_CREATED)
        return Response(response_data, status=status.HTTP_201_CREATED)

    with django_capture_on_commit_callbacks(execute=True):
        UserActionMiddleware(get_response)(_checked_request(admin_acme, acme.id))

    [event] = sent_events
    assert (event.action, event.target_type, event.target_id, event.target_name) == (
        "created",
        None,
        None,
        None,
    )


def test_fallback_ignores_unverified_org_header(
    admin_acme, beta, sent_events, django_capture_on_commit_callbacks
):
    request = RequestFactory().post("/api/things/", HTTP_X_ORGANIZATION_ID=str(beta.id))
    request.user = admin_acme

    with django_capture_on_commit_callbacks(execute=True):
        _serve(request, view_class=_PlainChangeView)

    assert sent_events == []


def test_fallback_never_labels_a_target_from_another_org(
    admin_acme, acme, beta, sent_events, django_capture_on_commit_callbacks
):
    other_org_flow = Graph.objects.create(name="Beta secret flow", org=beta)

    with django_capture_on_commit_callbacks(execute=True):
        _serve(
            _checked_request(admin_acme, acme.id),
            view_class=GraphViewSet,
            actions={"post": "copy"},
            route="api/^graphs/(?P<pk>[^/.]+)/copy/$",
            kwargs={"pk": str(other_org_flow.pk)},
        )

    [event] = sent_events
    assert (event.action, event.target_type, event.target_id, event.target_name) == (
        "copied",
        "flow",
        str(other_org_flow.pk),
        None,
    )


def test_fallback_change_outside_any_org_fans_out_under_the_profile_prefix(
    admin_in_two_orgs, acme, beta, sent_events, django_capture_on_commit_callbacks
):
    request = RequestFactory().post("/api/profile/things/")
    request.user = admin_in_two_orgs

    with django_capture_on_commit_callbacks(execute=True):
        _serve(request, view_class=_PlainChangeView, route="api/profile/things/")

    assert sorted((event.action, event.org_id, event.route) for event in sent_events) == sorted(
        [("created", acme.id, "POST api/profile/things/"), ("created", beta.id, "POST api/profile/things/")]
    )


def test_profile_change_with_a_foreign_org_header_reaches_only_own_orgs(
    client_as, admin_acme, acme, beta, sent_events, django_capture_on_commit_callbacks
):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(beta.id))
    with django_capture_on_commit_callbacks(execute=True):
        response = client.patch("/api/profile/", {"display_name": "Ada"}, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    assert [(event.action, event.org_id) for event in sent_events] == [("updated", acme.id)]


def test_fallback_never_reads_request_body(
    admin_client, flow, sent_events, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        response = admin_client.post(
            reverse("graphs-copy", args=[flow.pk]),
            {"name": "Copied flow", "password": "s3cret"},
            format="json",
        )

    assert response.status_code == status.HTTP_201_CREATED, response.content
    [event] = sent_events
    assert "s3cret" not in event.model_dump_json()


@pytest.fixture
def stream_storage(monkeypatch, settings):
    settings.ORG_STORAGE_QUOTA = 10**9
    settings.MAX_STREAM_UPLOAD_FILE_SIZE = None
    backend = InMemoryStorageBackend(organization_prefix="")
    monkeypatch.setattr(file_upload, "get_storage_backend", lambda **_: backend)
    monkeypatch.setattr(archive_upload, "get_storage_backend", lambda **_: backend)
    # The upload gate is a per-worker singleton built from settings.
    monkeypatch.setattr(admission, "_admission", None)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("stream_storage")
async def test_a_streamed_upload_records_the_created_file_by_path(admin_acme, acme, sent_events):
    response = await stream_upload(admin_acme, acme, "docs", "report.txt", b"password=s3cret")

    assert response.status_code == status.HTTP_200_OK, response.text
    stored = await StorageFile.objects.aget(org=acme, path="docs/report.txt")
    [event] = sent_events
    assert (
        event.action,
        event.target_type,
        event.target_id,
        event.target_name,
        event.org_id,
        event.actor_user_id,
        event.route,
    ) == ("created", "storage file", str(stored.pk), "docs/report.txt", acme.id, admin_acme.id, None)
    assert "s3cret" not in event.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("stream_storage")
async def test_a_streamed_upload_over_a_file_records_it_updated(admin_acme, acme, sent_events):
    await stream_upload(admin_acme, acme, "docs", "report.txt", b"first")
    sent_events.clear()

    response = await stream_upload(admin_acme, acme, "docs", "report.txt", b"second")

    assert response.status_code == status.HTTP_200_OK, response.text
    assert [(event.action, event.target_name) for event in sent_events] == [
        ("updated", "docs/report.txt")
    ]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("stream_storage")
async def test_a_streamed_archive_records_the_folder_it_unpacked_into(
    admin_acme, acme, sent_events
):
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("a.txt", b"a")
        zipped.writestr("nested/b.txt", b"b")

    response = await stream_upload(admin_acme, acme, "docs", "bundle.zip", archive.getvalue())

    assert response.status_code == status.HTTP_200_OK, response.text
    folder = await StorageFile.objects.aget(org=acme, path="docs/bundle/")
    assert [(event.action, event.target_id, event.target_name) for event in sent_events] == [
        ("created", str(folder.pk), "docs/bundle/")
    ]
