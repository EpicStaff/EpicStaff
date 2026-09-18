"""Regression coverage for security finding #33: `RealtimeSessionItem`
(`tables/models/realtime_models.py`) previously had no org FK at all — session
transcript/event rows (which can include base64 audio) were keyed only by an
opaque `connection_key`, with no way to scope them to a tenant.

`RealtimeSessionItem` now inherits `OrgScopedModel`, giving it a nullable
`org` FK (populated going forward by the `src/realtime` microservice at
write time; existing rows and any org-less write stay `org=None`).
"""

import pytest
from django.contrib.auth import get_user_model

from tables.models.realtime_models import RealtimeSessionItem
from tables.models.rbac_models import Organization


@pytest.mark.django_db
def test_realtime_session_item_can_be_created_with_org():
    org = Organization.objects.create(name="Acme")

    item = RealtimeSessionItem.objects.create(
        connection_key="conn-1",
        data={"type": "response.done"},
        org=org,
    )

    item.refresh_from_db()
    assert item.org_id == org.id


@pytest.mark.django_db
def test_realtime_session_item_org_defaults_to_null():
    item = RealtimeSessionItem.objects.create(
        connection_key="conn-2",
        data={"type": "response.done"},
    )

    item.refresh_from_db()
    assert item.org_id is None


@pytest.mark.django_db
def test_realtime_session_item_deleted_when_org_deleted():
    org = Organization.objects.create(name="Acme")
    item = RealtimeSessionItem.objects.create(
        connection_key="conn-3",
        data={"type": "response.done"},
        org=org,
    )
    item_id = item.id

    org.delete()

    assert not RealtimeSessionItem.objects.filter(id=item_id).exists()


@pytest.mark.django_db
def test_realtime_session_item_can_be_created_with_created_by():
    """Follow-up to finding #33: `created_by` (from `OrgScopedModel`) is
    populated for browser `/chats` sessions where the requesting user is
    known — see `src/realtime/infrastructure/persistence/database.py`
    `save_realtime_session_item_to_db`."""
    user = get_user_model().objects.create_user(
        email="voice-user@example.com", password="StrongPass123!"
    )

    item = RealtimeSessionItem.objects.create(
        connection_key="conn-4",
        data={"type": "response.done"},
        created_by=user,
    )

    item.refresh_from_db()
    assert item.created_by_id == user.id


@pytest.mark.django_db
def test_realtime_session_item_created_by_defaults_to_null():
    """Twilio voice calls have no end-user to attribute the session to —
    `created_by` must stay `None` for those rows."""
    item = RealtimeSessionItem.objects.create(
        connection_key="conn-5",
        data={"type": "response.done"},
    )

    item.refresh_from_db()
    assert item.created_by_id is None


@pytest.mark.django_db
def test_realtime_session_item_kept_when_created_by_deleted():
    """`created_by` uses `on_delete=SET_NULL` (see `OrgScopedModel`) — deleting
    the user must not cascade-delete the session item, only null the FK."""
    user = get_user_model().objects.create_user(
        email="voice-user-2@example.com", password="StrongPass123!"
    )
    item = RealtimeSessionItem.objects.create(
        connection_key="conn-6",
        data={"type": "response.done"},
        created_by=user,
    )
    item_id = item.id

    user.delete()

    item.refresh_from_db()
    assert item.id == item_id
    assert item.created_by_id is None
