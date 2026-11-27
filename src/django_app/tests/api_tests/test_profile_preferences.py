"""PATCH /api/profile/preferences/<section>/ and the `preferences` of GET /api/profile/."""

import threading
import time

import pytest
from django.db import connection, transaction
from rest_framework import serializers, status
from rest_framework.test import APIClient

from rbac.models import OrganizationUser
from rbac.profile.preferences.sections import (
    PREFERENCE_SECTIONS,
    OrgKeyedIdField,
    PreferenceSectionSerializer,
)
from rbac.profile.preferences.service import UserPreferencesService
from src.shared.models import UserAction
from tables.models import Graph
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

PROFILE_URL = "/api/profile/"

FLOW_EDITOR_DEFAULTS = {
    "arrow_colors": True,
    "show_inputs_outputs": False,
    "edge_style": "orthogonal",
    "always_show_node_numbers": False,
    "highlight_unused_nodes": False,
    "show_minimap": True,
    "on_open": "fit",
}


def section_url(section: str) -> str:
    return f"/api/profile/preferences/{section}/"


@pytest.fixture
def member_client(client_as, member_only):
    return client_as(member_only)


class _OrgKeyedSectionSerializer(PreferenceSectionSerializer):
    """A section holding an organization's object, as the AI and knowledge sections will."""

    favorite_flow = OrgKeyedIdField(Graph)
    label = serializers.CharField(required=False, default="none")


@pytest.fixture
def org_keyed_section(monkeypatch):
    monkeypatch.setitem(PREFERENCE_SECTIONS, "org_keyed", _OrgKeyedSectionSerializer)
    return "org_keyed"


@pytest.fixture
def member_of_both(member_only, beta, role_member):
    OrganizationUser.objects.create(user=member_only, org=beta, role=role_member)
    return member_only


# ---- Reading ----


@pytest.mark.django_db
def test_profile_returns_default_preferences(member_client):
    response = member_client.get(PROFILE_URL)

    assert response.status_code == status.HTTP_200_OK
    preferences = response.json()["preferences"]
    assert preferences["general"] == {"display_timezone": None, "default_timezone": None}
    assert preferences["flow_editor"] == FLOW_EDITOR_DEFAULTS


@pytest.mark.django_db
def test_profile_shows_stored_values_over_the_defaults(member_client, member_only):
    member_only.preferences = {"flow_editor": {"show_minimap": False}}
    member_only.save(update_fields=["preferences"])

    response = member_client.get(PROFILE_URL)

    assert response.json()["preferences"]["flow_editor"] == {
        **FLOW_EDITOR_DEFAULTS,
        "show_minimap": False,
    }


# ---- Changing a section ----


@pytest.mark.django_db
def test_patch_section_saves_and_returns_effective(member_client, member_only):
    response = member_client.patch(
        section_url("flow_editor"), {"edge_style": "adaptive-curve"}, format="json"
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["edge_style"] == "adaptive-curve"
    assert response.json()["arrow_colors"] is True
    member_only.refresh_from_db()
    assert member_only.preferences == {"flow_editor": {"edge_style": "adaptive-curve"}}


@pytest.mark.django_db
@pytest.mark.parametrize(
    "body",
    [
        {"edge_style": "zigzag"},
        {"nope": 1},
        {"edge_style": "adaptive-curve", "nope": 1},
    ],
    ids=["bad-edge-style", "unknown-key", "valid-plus-unknown-key"],
)
def test_patch_rejects_unknown_key_and_bad_value(member_client, member_only, body):
    response = member_client.patch(section_url("flow_editor"), body, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    member_only.refresh_from_db()
    assert member_only.preferences == {}


@pytest.mark.django_db
def test_patch_rejects_a_body_that_is_not_an_object(member_client, member_only):
    response = member_client.patch(section_url("flow_editor"), "42", content_type="application/json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    member_only.refresh_from_db()
    assert member_only.preferences == {}


@pytest.mark.django_db
def test_patch_unknown_section_is_404(member_client, member_only):
    response = member_client.patch(section_url("nope"), {"edge_style": "orthogonal"}, format="json")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["code"] == "preference_section_not_found"
    member_only.refresh_from_db()
    assert member_only.preferences == {}


@pytest.mark.django_db
def test_patch_normalises_kiev(member_client, member_only):
    response = member_client.patch(
        section_url("general"), {"display_timezone": "Europe/Kiev"}, format="json"
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"display_timezone": "Europe/Kyiv", "default_timezone": None}
    member_only.refresh_from_db()
    assert member_only.preferences == {"general": {"display_timezone": "Europe/Kyiv"}}


@pytest.mark.django_db
@pytest.mark.parametrize("zone", ["Mars/Base", "europe/kyiv"], ids=["unknown", "wrong-case"])
def test_patch_rejects_an_unknown_timezone(member_client, member_only, zone):
    response = member_client.patch(section_url("general"), {"default_timezone": zone}, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    member_only.refresh_from_db()
    assert member_only.preferences == {}


@pytest.mark.django_db
def test_patch_null_timezone_follows_the_browser_again(member_client, member_only):
    member_only.preferences = {"general": {"display_timezone": "UTC", "default_timezone": "UTC"}}
    member_only.save(update_fields=["preferences"])

    response = member_client.patch(section_url("general"), {"display_timezone": None}, format="json")

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"display_timezone": None, "default_timezone": "UTC"}


@pytest.mark.django_db
def test_patch_section_leaves_other_sections(member_client, member_only):
    first = member_client.patch(section_url("general"), {"display_timezone": "UTC"}, format="json")
    second = member_client.patch(section_url("flow_editor"), {"show_minimap": False}, format="json")

    assert (first.status_code, second.status_code) == (status.HTTP_200_OK, status.HTTP_200_OK)
    member_only.refresh_from_db()
    assert member_only.preferences == {
        "general": {"display_timezone": "UTC"},
        "flow_editor": {"show_minimap": False},
    }


@pytest.mark.django_db
def test_patch_keeps_the_other_keys_of_the_section(member_client, member_only):
    member_client.patch(section_url("flow_editor"), {"show_minimap": False}, format="json")
    response = member_client.patch(section_url("flow_editor"), {"on_open": "restore"}, format="json")

    assert response.json() == {**FLOW_EDITOR_DEFAULTS, "show_minimap": False, "on_open": "restore"}
    member_only.refresh_from_db()
    assert member_only.preferences == {"flow_editor": {"show_minimap": False, "on_open": "restore"}}


@pytest.mark.django_db
def test_patch_does_not_touch_the_profile_updated_at(member_client, member_only):
    updated_at_before = member_only.updated_at

    member_client.patch(section_url("general"), {"display_timezone": "UTC"}, format="json")

    member_only.refresh_from_db()
    assert member_only.updated_at == updated_at_before


def _wait_until_another_connection_waits_for_a_lock(timeout_seconds: float = 10.0) -> None:
    with connection.cursor() as cursor:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            cursor.execute(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                "AND wait_event_type = 'Lock' AND pid <> pg_backend_pid()"
            )
            if cursor.fetchone()[0]:
                return
            time.sleep(0.05)
    pytest.fail("The second save never waited for the first one's lock.")


@pytest.mark.django_db(transaction=True)
def test_patch_sections_concurrently_keeps_both(django_user_model):
    user = django_user_model.objects.create_user(email="two-tabs@x.test", password="StrongPass123!")
    other_tab_user = django_user_model.objects.get(pk=user.pk)
    service = UserPreferencesService()
    other_tab_errors = []

    def save_in_other_tab():
        try:
            service.patch_section(
                other_tab_user, "flow_editor", {"edge_style": "adaptive-curve"}, lambda: None
            )
        except Exception as error:  # noqa: BLE001 - re-raised on the test thread below
            other_tab_errors.append(error)
        finally:
            connection.close()

    other_tab = threading.Thread(target=save_in_other_tab)
    # The first tab's save stays uncommitted until the second tab's save is blocked on
    # it, so the second one starts while the first one is still in flight.
    with transaction.atomic():
        service.patch_section(user, "general", {"display_timezone": "UTC"}, lambda: None)
        other_tab.start()
        _wait_until_another_connection_waits_for_a_lock()
    other_tab.join(timeout=10)

    assert not other_tab.is_alive()
    assert other_tab_errors == []
    user.refresh_from_db()
    assert user.preferences == {
        "general": {"display_timezone": "UTC"},
        "flow_editor": {"edge_style": "adaptive-curve"},
    }


# ---- Who may change them, and what gets recorded ----


@pytest.mark.django_db
def test_patch_writes_no_audit_rows(
    member_client, acme, sent_audit_events, django_capture_on_commit_callbacks
):
    member_client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

    with django_capture_on_commit_callbacks(execute=True):
        response = member_client.patch(
            section_url("flow_editor"), {"show_minimap": False}, format="json"
        )
    assert response.status_code == status.HTTP_200_OK
    assert sent_audit_events == []

    # The same caller's profile edit is recorded, so the capture above did work.
    with django_capture_on_commit_callbacks(execute=True):
        member_client.patch(PROFILE_URL, {"display_name": "Renamed"}, format="json")
    assert [event.action for event in sent_audit_events] == [UserAction.UPDATED]


@pytest.mark.django_db
def test_api_key_cannot_patch_preferences(member_only, issue_api_key):
    raw_key, _ = issue_api_key(user=member_only)
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=raw_key)

    response = client.patch(section_url("general"), {"display_timezone": "UTC"}, format="json")

    assert response.status_code == status.HTTP_403_FORBIDDEN
    member_only.refresh_from_db()
    assert member_only.preferences == {}


@pytest.mark.django_db
def test_anonymous_cannot_patch_preferences():
    response = APIClient().patch(section_url("general"), {"display_timezone": "UTC"}, format="json")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


# ---- A stale X-Organization-Id header ----


@pytest.fixture
def header_of_an_org_the_member_left(member_of_both, beta):
    OrganizationUser.objects.filter(user=member_of_both, org=beta).delete()
    return str(beta.id)


@pytest.fixture
def header_of_a_deactivated_org(member_only, acme):
    acme.is_active = False
    acme.save(update_fields=["is_active"])
    return str(acme.id)


@pytest.fixture
def header_that_is_not_an_id():
    return "not-an-id"


@pytest.fixture
def no_org_header():
    return None


def _send_org_header(client, header: str | None) -> None:
    if header is not None:
        client.credentials(HTTP_X_ORGANIZATION_ID=header)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "header_fixture",
    [
        "header_of_an_org_the_member_left",
        "header_of_a_deactivated_org",
        "header_that_is_not_an_id",
        "no_org_header",
    ],
    ids=["org-left", "org-deactivated", "malformed", "no-header"],
)
def test_stale_org_header_does_not_block_saving_what_needs_no_org(
    request, member_client, member_only, org_keyed_section, header_fixture
):
    _send_org_header(member_client, request.getfixturevalue(header_fixture))

    response = member_client.patch(section_url(org_keyed_section), {"label": "x"}, format="json")

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"favorite_flow": {}, "label": "x"}
    member_only.refresh_from_db()
    assert member_only.preferences == {org_keyed_section: {"label": "x"}}


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("header_fixture", "expected_status", "expected_code"),
    [
        ("header_of_an_org_the_member_left", status.HTTP_403_FORBIDDEN, "org_membership_required"),
        ("header_of_a_deactivated_org", status.HTTP_403_FORBIDDEN, "organization_deactivated"),
        ("header_that_is_not_an_id", status.HTTP_400_BAD_REQUEST, "org_context_required"),
        ("no_org_header", status.HTTP_400_BAD_REQUEST, "invalid"),
    ],
    ids=["org-left", "org-deactivated", "malformed", "no-header"],
)
def test_org_keyed_write_without_a_usable_active_org_is_refused(
    request,
    member_client,
    member_only,
    acme,
    org_keyed_section,
    header_fixture,
    expected_status,
    expected_code,
):
    flow = Graph.objects.create(name="Mine", org=acme)
    _send_org_header(member_client, request.getfixturevalue(header_fixture))

    response = member_client.patch(
        section_url(org_keyed_section), {"favorite_flow": {str(acme.id): flow.pk}}, format="json"
    )

    assert response.status_code == expected_status
    assert response.json()["code"] == expected_code
    member_only.refresh_from_db()
    assert member_only.preferences == {}


# ---- Organization-keyed preferences ----


@pytest.mark.django_db
def test_org_keyed_id_is_stored_under_the_active_org(
    member_client, member_only, acme, org_keyed_section
):
    flow = Graph.objects.create(name="Mine", org=acme)
    member_client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

    response = member_client.patch(
        section_url(org_keyed_section), {"favorite_flow": {str(acme.id): flow.pk}}, format="json"
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["favorite_flow"] == {str(acme.id): flow.pk}
    member_only.refresh_from_db()
    assert member_only.preferences == {org_keyed_section: {"favorite_flow": {str(acme.id): flow.pk}}}


@pytest.mark.django_db
def test_org_keyed_id_of_another_org_is_400(member_client, member_only, acme, beta, org_keyed_section):
    beta_flow = Graph.objects.create(name="Theirs", org=beta)
    member_client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

    response = member_client.patch(
        section_url(org_keyed_section), {"favorite_flow": {str(acme.id): beta_flow.pk}}, format="json"
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    member_only.refresh_from_db()
    assert member_only.preferences == {}


@pytest.mark.django_db
def test_org_keyed_id_of_a_binned_object_is_400(member_client, acme, org_keyed_section):
    flow = Graph.objects.create(name="Binned", org=acme)
    flow.delete()
    member_client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

    response = member_client.patch(
        section_url(org_keyed_section), {"favorite_flow": {str(acme.id): flow.pk}}, format="json"
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_org_keyed_write_keeps_other_orgs_entries_and_ignores_the_clients(
    member_client, member_of_both, acme, beta, org_keyed_section
):
    acme_flow = Graph.objects.create(name="Acme flow", org=acme)
    beta_flow = Graph.objects.create(name="Beta flow", org=beta)
    member_of_both.preferences = {org_keyed_section: {"favorite_flow": {str(beta.id): beta_flow.pk}}}
    member_of_both.save(update_fields=["preferences"])
    member_client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

    response = member_client.patch(
        section_url(org_keyed_section),
        {"favorite_flow": {str(acme.id): acme_flow.pk, str(beta.id): 999999}},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    expected = {str(acme.id): acme_flow.pk, str(beta.id): beta_flow.pk}
    assert response.json()["favorite_flow"] == expected
    member_of_both.refresh_from_db()
    assert member_of_both.preferences[org_keyed_section]["favorite_flow"] == expected


@pytest.mark.django_db
def test_org_keyed_null_entry_clears_only_the_active_org(
    member_client, member_of_both, acme, beta, org_keyed_section
):
    stored = {str(acme.id): 1, str(beta.id): 2}
    member_of_both.preferences = {org_keyed_section: {"favorite_flow": stored}}
    member_of_both.save(update_fields=["preferences"])
    member_client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

    response = member_client.patch(
        section_url(org_keyed_section), {"favorite_flow": {str(acme.id): None}}, format="json"
    )

    assert response.status_code == status.HTTP_200_OK
    member_of_both.refresh_from_db()
    assert member_of_both.preferences[org_keyed_section]["favorite_flow"] == {str(beta.id): 2}


@pytest.mark.django_db
@pytest.mark.parametrize(
    "make_value",
    [
        lambda organization_id: [organization_id],
        lambda organization_id: {str(organization_id): True},
    ],
    ids=["list", "bool-id"],
)
def test_org_keyed_rejects_a_malformed_value(member_client, acme, org_keyed_section, make_value):
    member_client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

    response = member_client.patch(
        section_url(org_keyed_section), {"favorite_flow": make_value(acme.id)}, format="json"
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_org_keyed_entry_of_an_org_the_user_left_is_not_effective(
    member_client, member_only, acme, beta, org_keyed_section
):
    member_only.preferences = {
        org_keyed_section: {"favorite_flow": {str(acme.id): 1, str(beta.id): 2}}
    }
    member_only.save(update_fields=["preferences"])

    response = member_client.get(PROFILE_URL)

    assert response.json()["preferences"][org_keyed_section]["favorite_flow"] == {str(acme.id): 1}
    member_only.refresh_from_db()
    assert member_only.preferences[org_keyed_section]["favorite_flow"] == {
        str(acme.id): 1,
        str(beta.id): 2,
    }


@pytest.mark.django_db
def test_org_keyed_entry_of_a_deactivated_org_is_not_effective(
    member_of_both, acme, beta, org_keyed_section
):
    stored = {str(acme.id): 1, str(beta.id): 2}
    member_of_both.preferences = {org_keyed_section: {"favorite_flow": stored}}
    member_of_both.save(update_fields=["preferences"])
    beta.is_active = False
    beta.save(update_fields=["is_active"])

    effective = UserPreferencesService().effective(member_of_both)

    assert effective[org_keyed_section]["favorite_flow"] == {str(acme.id): 1}
    member_of_both.refresh_from_db()
    assert member_of_both.preferences[org_keyed_section]["favorite_flow"] == stored


@pytest.mark.django_db
def test_org_keyed_entries_stay_effective_for_a_superadmin(superadmin, acme, beta, org_keyed_section):
    stored = {str(acme.id): 1, str(beta.id): 2}
    superadmin.preferences = {org_keyed_section: {"favorite_flow": stored}}
    superadmin.save(update_fields=["preferences"])

    effective = UserPreferencesService().effective(superadmin)

    assert effective[org_keyed_section]["favorite_flow"] == stored
