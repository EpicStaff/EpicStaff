import pytest
from django.urls import reverse

from tables.models.webhook_models import (
    LocalhostWebhookConfig,
    NgrokWebhookConfig,
    ProviderType,
    RealtimeChannel,
    TwilioChannel,
    WebhookTrigger,
)
from tables.models.realtime_models import RealtimeAgent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_realtime_channel(db, org, **kwargs):
    """Create a minimal RealtimeChannel (no RealtimeAgent required).

    RealtimeChannel is org-scoped (EST-3491 follow-up) — every direct ORM
    .create() must pass `org`, same as the API path stamps it via the
    active org (OrgScopedViewSetMixin.perform_create).
    """
    return RealtimeChannel.objects.create(name="test-channel", org=org, **kwargs)


def _make_twilio_channel(realtime_channel, org=None, **kwargs):
    """Create a TwilioChannel attached to `realtime_channel`.

    TwilioChannel itself has no `org` column (EST-3491 follow-up) — org
    lives on the parent RealtimeChannel. `org` is accepted only for
    call-site compatibility (it is not written anywhere here); callers must
    have already created `realtime_channel` with the right org via
    `_make_realtime_channel`.
    """
    return TwilioChannel.objects.create(
        channel=realtime_channel,
        account_sid="AC_test",
        auth_token="auth_test",
        **kwargs,
    )


def _make_webhook_trigger_with_ngrok(org, path="test-voice"):
    # WebhookTrigger is now org-owned (EST-3491) — every direct ORM .create()
    # must pass `org`, same as the API path stamps it via the active org.
    trigger = WebhookTrigger.objects.create(
        path=path, provider_type=ProviderType.NGROK, org=org
    )
    NgrokWebhookConfig.objects.create(
        trigger=trigger,
        name="test-ngrok",
        auth_token="tok",
        region=NgrokWebhookConfig.Region.EU,
    )
    return trigger


def _make_webhook_trigger_with_localhost(org, path="test-localhost"):
    trigger = WebhookTrigger.objects.create(
        path=path, provider_type=ProviderType.LOCALHOST, org=org
    )
    LocalhostWebhookConfig.objects.create(
        trigger=trigger,
        name="test-localhost",
        domain="localhost:8000",
    )
    return trigger


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestTwilioChannelWebhookTrigger:
    def test_create_twilio_channel_without_webhook_trigger(self, auth_client, db, default_org):
        """POST without webhook_trigger should create successfully with null trigger."""
        rc = _make_realtime_channel(db, default_org)
        url = reverse("twiliochannel-list")
        payload = {
            "channel": rc.pk,
            "account_sid": "AC_nosid",
            "auth_token": "tok_noauth",
        }
        response = auth_client.post(url, payload, format="json")
        assert response.status_code == 201, response.json()
        assert response.json()["webhook_trigger"] is None

    def test_create_twilio_channel_with_ngrok_trigger(self, auth_client, db, default_org):
        """POST with webhook_trigger FK; GET should return nested webhook_trigger with live_url=null."""
        rc = _make_realtime_channel(db, default_org)
        trigger = _make_webhook_trigger_with_ngrok(default_org, path="voice-ngrok-test")

        url = reverse("twiliochannel-list")
        payload = {
            "channel": rc.pk,
            "account_sid": "AC_ngrok",
            "auth_token": "tok_ngrok",
            "webhook_trigger": trigger.pk,
        }
        create_response = auth_client.post(url, payload, format="json")
        assert create_response.status_code == 201, create_response.json()

        twilio_pk = create_response.json()["channel"]
        get_response = auth_client.get(
            reverse("twiliochannel-detail", args=[twilio_pk])
        )
        assert get_response.status_code == 200, get_response.json()

        data = get_response.json()
        # The read path still returns the FK id (TwilioChannelSerializer is used for both)
        assert data["webhook_trigger"] == trigger.pk

    def test_two_channels_share_one_trigger(self, auth_client, db, default_org):
        """Two TwilioChannels may point at the same WebhookTrigger."""
        rc1 = _make_realtime_channel(db, default_org)
        rc2 = RealtimeChannel.objects.create(name="channel-b", org=default_org)
        trigger = _make_webhook_trigger_with_ngrok(default_org, path="shared-trigger")

        url = reverse("twiliochannel-list")
        for rc, sid in [(rc1, "AC_one"), (rc2, "AC_two")]:
            response = auth_client.post(
                url,
                {
                    "channel": rc.pk,
                    "account_sid": sid,
                    "auth_token": "auth",
                    "webhook_trigger": trigger.pk,
                },
                format="json",
            )
            assert response.status_code == 201, response.json()

        # Both channels are linked to the same trigger
        assert TwilioChannel.objects.filter(webhook_trigger=trigger).count() == 2

        # GET each channel and confirm path matches
        for tc in TwilioChannel.objects.filter(webhook_trigger=trigger):
            get_resp = auth_client.get(
                reverse("twiliochannel-detail", args=[tc.channel_id])
            )
            assert get_resp.status_code == 200
            assert get_resp.json()["webhook_trigger"] == trigger.pk

    def test_patch_twilio_channel_remove_trigger(self, auth_client, db, default_org):
        """PATCH webhook_trigger=null should clear the FK."""
        rc = _make_realtime_channel(db, default_org)
        trigger = _make_webhook_trigger_with_ngrok(default_org, path="removable-trigger")
        tc = _make_twilio_channel(rc, default_org, webhook_trigger=trigger)

        url = reverse("twiliochannel-detail", args=[tc.channel_id])
        response = auth_client.patch(url, {"webhook_trigger": None}, format="json")
        assert response.status_code == 200, response.json()
        assert response.json()["webhook_trigger"] is None

        tc.refresh_from_db()
        assert tc.webhook_trigger_id is None

    def test_configure_webhook_rejects_localhost_provider(self, auth_client, db, default_org):
        """configure-webhook must 400 when the trigger uses the localhost provider."""
        rc = _make_realtime_channel(db, default_org)
        trigger = _make_webhook_trigger_with_localhost(default_org, path="cfg-localhost")
        _make_twilio_channel(rc, default_org, webhook_trigger=trigger)

        url = reverse("twilio-configure-webhook")
        response = auth_client.post(
            url,
            {"phone_sid": "PN_test", "channel_token": str(rc.token)},
            format="json",
        )
        assert response.status_code == 400, response.json()
        assert "localhost" in response.json()["error"].lower()

    def test_validate_provider_rejects_localhost(self, db, default_org):
        """validate_provider() returns an error message for local-only providers."""
        rc = _make_realtime_channel(db, default_org)
        trigger = _make_webhook_trigger_with_localhost(default_org, path="vp-localhost")
        tc = _make_twilio_channel(rc, default_org, webhook_trigger=trigger)

        error = tc.validate_provider()
        assert error is not None
        assert "localhost" in error.lower()

    def test_validate_provider_accepts_ngrok(self, db, default_org):
        """validate_provider() returns None for a publicly reachable provider."""
        rc = _make_realtime_channel(db, default_org)
        trigger = _make_webhook_trigger_with_ngrok(default_org, path="vp-ngrok")
        tc = _make_twilio_channel(rc, default_org, webhook_trigger=trigger)

        assert tc.validate_provider() is None

    def test_validate_provider_rejects_missing_trigger(self, db, default_org):
        """validate_provider() returns an error when no trigger is configured."""
        rc = _make_realtime_channel(db, default_org)
        tc = _make_twilio_channel(rc, default_org)

        error = tc.validate_provider()
        assert error is not None
        assert "no webhook trigger" in error.lower()

    def test_realtime_channel_get_expands_twilio_webhook_trigger(self, auth_client, db, default_org):
        """GET /realtime-channels/{id}/ should include twilio.webhook_trigger with path and live_url."""
        trigger = _make_webhook_trigger_with_ngrok(default_org, path="realtime-voice")
        rc = _make_realtime_channel(db, default_org)
        _make_twilio_channel(rc, default_org, webhook_trigger=trigger)

        url = reverse("realtimechannel-detail", args=[rc.pk])
        response = auth_client.get(url)
        assert response.status_code == 200, response.json()

        data = response.json()
        twilio = data.get("twilio")
        assert twilio is not None, "twilio nested object missing"

        wt = twilio.get("webhook_trigger")
        assert wt is not None, "webhook_trigger missing in twilio"
        assert wt["path"] == "realtime-voice"
        # live_url is null in test env (no Redis tunnel running)
        assert "live_url" in wt
        assert wt["live_url"] is None
