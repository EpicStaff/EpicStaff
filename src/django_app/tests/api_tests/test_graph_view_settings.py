"""/api/graphs/<graph_id>/my-view-settings/: a user's own flow-editor settings and default
timezone for one flow."""

import pytest
from django.contrib.contenttypes.models import ContentType
from rest_framework import status
from rest_framework.test import APIClient

from rbac.models import ResourceLastEdit
from rbac.models.enums import Permission, ResourceType
from src.shared.models import UserAction
from tables.models import Graph, UserGraphViewSettings
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

pytestmark = pytest.mark.django_db


def view_settings_url(graph_id: int) -> str:
    return f"/api/graphs/{graph_id}/my-view-settings/"


@pytest.fixture
def flow(acme):
    return Graph.objects.create(name="Billing flow", org=acme)


@pytest.fixture
def org_client(client_as, acme):
    """An APIClient for `user` working in Acme."""

    def _make(user):
        client = client_as(user)
        client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
        return client

    return _make


@pytest.fixture
def member_client(org_client, member_only):
    return org_client(member_only)


def test_get_without_settings_returns_empty(member_client, flow):
    response = member_client.get(view_settings_url(flow.pk))

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"settings": {}}


def test_put_then_get_returns_override(member_client, member_only, flow):
    body = {
        "settings": {
            "default_timezone": "America/New_York",
            "edge_style": "adaptive-curve",
            "show_minimap": False,
        }
    }

    put_response = member_client.put(view_settings_url(flow.pk), body, format="json")
    get_response = member_client.get(view_settings_url(flow.pk))

    assert put_response.status_code == status.HTTP_200_OK
    assert put_response.json() == body
    assert get_response.json() == body
    assert UserGraphViewSettings.objects.get(user=member_only, graph=flow).settings == body["settings"]


def test_put_replaces_the_whole_value(member_client, member_only, flow):
    member_client.put(view_settings_url(flow.pk), {"settings": {"show_minimap": False}}, format="json")

    response = member_client.put(
        view_settings_url(flow.pk), {"settings": {"on_open": "restore"}}, format="json"
    )

    assert response.json() == {"settings": {"on_open": "restore"}}
    assert UserGraphViewSettings.objects.filter(user=member_only, graph=flow).count() == 1
    assert UserGraphViewSettings.objects.get(user=member_only, graph=flow).settings == {
        "on_open": "restore"
    }


def test_delete_clears_override(member_client, member_only, flow):
    member_client.put(view_settings_url(flow.pk), {"settings": {"show_minimap": False}}, format="json")

    response = member_client.delete(view_settings_url(flow.pk))

    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert not UserGraphViewSettings.objects.filter(user=member_only, graph=flow).exists()
    assert member_client.get(view_settings_url(flow.pk)).json() == {"settings": {}}


def test_delete_without_settings_is_204(member_client, flow):
    response = member_client.delete(view_settings_url(flow.pk))

    assert response.status_code == status.HTTP_204_NO_CONTENT


@pytest.mark.parametrize(
    "body",
    [
        {"settings": {"nope": True}},
        {"settings": "orthogonal"},
    ],
    ids=["unknown-key", "not-an-object"],
)
def test_put_rejects_invalid_settings(member_client, flow, body):
    response = member_client.put(view_settings_url(flow.pk), body, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert not UserGraphViewSettings.objects.filter(graph=flow).exists()


def test_get_hides_a_stored_key_the_override_no_longer_defines(member_client, member_only, flow):
    UserGraphViewSettings.objects.create(
        user=member_only, graph=flow, settings={"show_minimap": False, "retired_key": "x"}
    )

    get_response = member_client.get(view_settings_url(flow.pk))
    put_response = member_client.put(view_settings_url(flow.pk), get_response.json(), format="json")

    assert get_response.status_code == status.HTTP_200_OK
    assert get_response.json() == {"settings": {"show_minimap": False}}
    assert put_response.status_code == status.HTTP_200_OK
    assert UserGraphViewSettings.objects.get(user=member_only, graph=flow).settings == {
        "show_minimap": False
    }


@pytest.mark.parametrize("zone", ["Mars/Base", None], ids=["unknown", "null"])
def test_put_rejects_an_invalid_default_timezone(member_client, flow, zone):
    response = member_client.put(
        view_settings_url(flow.pk), {"settings": {"default_timezone": zone}}, format="json"
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "default_timezone" in response.json()["message"]
    assert not UserGraphViewSettings.objects.filter(graph=flow).exists()


@pytest.mark.parametrize("method", ["get", "put", "delete"])
def test_other_org_graph_is_404(member_client, beta, method):
    beta_flow = Graph.objects.create(name="Beta flow", org=beta)

    response = getattr(member_client, method)(
        view_settings_url(beta_flow.pk), {"settings": {"show_minimap": False}}, format="json"
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert not UserGraphViewSettings.objects.filter(graph=beta_flow).exists()


def test_other_org_graph_with_my_own_row_is_404_and_kept(member_client, member_only, beta):
    beta_flow = Graph.objects.create(name="Beta flow", org=beta)
    UserGraphViewSettings.objects.create(user=member_only, graph=beta_flow, settings={"show_minimap": False})

    get_response = member_client.get(view_settings_url(beta_flow.pk))
    delete_response = member_client.delete(view_settings_url(beta_flow.pk))

    assert (get_response.status_code, delete_response.status_code) == (
        status.HTTP_404_NOT_FOUND,
        status.HTTP_404_NOT_FOUND,
    )
    assert UserGraphViewSettings.objects.filter(user=member_only, graph=beta_flow).exists()


@pytest.mark.parametrize("method", ["get", "put", "delete"])
def test_binned_graph_is_404(member_client, flow, method):
    flow.delete()

    response = getattr(member_client, method)(
        view_settings_url(flow.pk), {"settings": {"show_minimap": False}}, format="json"
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_binning_the_graph_keeps_the_override_for_a_restore(member_only, flow):
    UserGraphViewSettings.objects.create(user=member_only, graph=flow, settings={"show_minimap": False})

    flow.delete()

    assert UserGraphViewSettings.objects.get(user=member_only, graph=flow).settings == {
        "show_minimap": False
    }


def test_hard_delete_graph_cascades(member_only, flow):
    UserGraphViewSettings.objects.create(user=member_only, graph=flow, settings={"show_minimap": False})
    flow.delete()

    flow.purge()

    assert not UserGraphViewSettings.objects.filter(graph_id=flow.pk).exists()


def test_second_user_does_not_see_my_override(member_client, org_client, admin_acme, flow):
    member_client.put(view_settings_url(flow.pk), {"settings": {"edge_style": "adaptive-curve"}}, format="json")
    admin_client = org_client(admin_acme)

    response = admin_client.get(view_settings_url(flow.pk))
    admin_client.delete(view_settings_url(flow.pk))

    assert response.json() == {"settings": {}}
    assert member_client.get(view_settings_url(flow.pk)).json() == {
        "settings": {"edge_style": "adaptive-curve"}
    }


def test_viewer_role_can_save_override(org_client, viewer_only, flow):
    client = org_client(viewer_only)

    put_response = client.put(view_settings_url(flow.pk), {"settings": {"show_minimap": False}}, format="json")
    delete_response = client.delete(view_settings_url(flow.pk))

    assert put_response.status_code == status.HTTP_200_OK
    assert delete_response.status_code == status.HTTP_204_NO_CONTENT


@pytest.mark.parametrize("method", ["get", "put", "delete"])
def test_role_without_flow_read_is_403(org_client, custom_role_user, acme, flow, method):
    user = custom_role_user(acme, "agents-only@x.test", {ResourceType.AGENTS: Permission.READ})

    response = getattr(org_client(user), method)(
        view_settings_url(flow.pk), {"settings": {"show_minimap": False}}, format="json"
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert not UserGraphViewSettings.objects.filter(graph=flow).exists()


def test_missing_org_header_is_400(client_as, member_only, flow):
    response = client_as(member_only).get(view_settings_url(flow.pk))

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["code"] == "org_context_required"


def test_api_key_cannot_save_override(member_only, issue_api_key, acme, flow):
    raw_key, _ = issue_api_key(user=member_only, org=acme)
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=raw_key)

    response = client.put(view_settings_url(flow.pk), {"settings": {"show_minimap": False}}, format="json")

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert not UserGraphViewSettings.objects.filter(graph=flow).exists()


def test_put_does_not_touch_graph_updated_at_or_last_editor(member_client, flow):
    updated_at_before = flow.updated_at
    graph_last_edits = ResourceLastEdit.objects.filter(
        content_type=ContentType.objects.get_for_model(Graph), object_id=flow.pk
    )
    last_edits_before = list(graph_last_edits.values_list("edited_by_id", "edited_at"))

    member_client.put(view_settings_url(flow.pk), {"settings": {"show_minimap": False}}, format="json")
    member_client.delete(view_settings_url(flow.pk))

    flow.refresh_from_db()
    assert flow.updated_at == updated_at_before
    assert list(graph_last_edits.values_list("edited_by_id", "edited_at")) == last_edits_before


def test_put_and_delete_record_no_user_action(
    member_client, flow, sent_audit_events, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        put_response = member_client.put(
            view_settings_url(flow.pk), {"settings": {"show_minimap": False}}, format="json"
        )
        delete_response = member_client.delete(view_settings_url(flow.pk))

    assert (put_response.status_code, delete_response.status_code) == (
        status.HTTP_200_OK,
        status.HTTP_204_NO_CONTENT,
    )
    assert sent_audit_events == []

    # The same caller's rename of the flow is recorded, so the capture above did work.
    with django_capture_on_commit_callbacks(execute=True):
        rename_response = member_client.patch(
            f"/api/graphs/{flow.pk}/",
            {"name": "Renamed flow", "save_version": flow.save_version},
            format="json",
        )
    assert rename_response.status_code == status.HTTP_200_OK
    assert [event.action for event in sent_audit_events] == [UserAction.RENAMED]
