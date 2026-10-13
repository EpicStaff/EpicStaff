"""Regression coverage for security finding #33: `RealtimeSessionItem` rows
(transcripts and events, which can include base64 audio) used to be keyed only by
an opaque `connection_key`. They are now org-scoped, so they go with their tenant,
and may carry the user who held the session (Twilio calls have none)."""

import pytest
from django.contrib.auth import get_user_model

from rbac.models import Organization
from tables.models.realtime_models import RealtimeSessionItem


@pytest.mark.django_db
def test_deleting_the_org_deletes_its_session_items():
    org = Organization.objects.create(name="Acme")
    item = RealtimeSessionItem.objects.create(connection_key="conn-3", data={"type": "response.done"}, org=org)

    org.delete()

    assert not RealtimeSessionItem.objects.filter(id=item.id).exists()


@pytest.mark.django_db
def test_deleting_the_user_keeps_the_session_item_unattributed():
    user = get_user_model().objects.create_user(email="voice-user-2@example.com", password="StrongPass123!")
    item = RealtimeSessionItem.objects.create(connection_key="conn-6", data={"type": "response.done"}, created_by=user)

    user.delete()

    item.refresh_from_db()
    assert item.created_by_id is None
