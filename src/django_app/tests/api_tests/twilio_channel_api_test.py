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
from tables.models.rbac_models import Organization


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


@pytest.mark.django_db
class TestTwilioChannelCrossOrgCreateGuard:
    """EST-1869: create() looks up an existing TwilioChannel row via a raw,
    unfiltered `TwilioChannel.objects.filter(channel_id=...)` (channel_id is
    the global PK, not scoped by get_queryset()) before it ever checks org.
    Without an explicit guard, an org A caller could POST an org B channel_id
    and overwrite org B's account_sid/auth_token/phone_number."""

    def test_create_rejects_overwrite_of_other_org_channel(
        self, auth_client, db, default_org
    ):
        org_b = Organization.objects.create(name="Org B")
        rc_b = _make_realtime_channel(db, org_b)
        tc_b = _make_twilio_channel(rc_b, org_b, phone_number="+10000000000")

        url = reverse("twiliochannel-list")
        response = auth_client.post(
            url,
            {
                "channel": rc_b.pk,
                "account_sid": "AC_hijacked",
                "auth_token": "hijacked-token",
                "phone_number": "+19999999999",
            },
            format="json",
        )

        assert response.status_code == 404, response.json()

        tc_b.refresh_from_db()
        assert tc_b.account_sid == "AC_test"
        assert tc_b.auth_token == "auth_test"
        assert tc_b.phone_number == "+10000000000"


@pytest.mark.django_db
class TestTwilioChannelAuthTokenNotLeaked:
    """EST-3633: auth_token must never appear in a twilio-channels response
    body (list/retrieve/create/update), though it must remain writable.
    Regression guard: the realtime-channels nested read path
    (_TwilioChannelReadSerializer) must also keep omitting it."""

    def test_create_accepts_but_does_not_echo_auth_token(
        self, auth_client, db, default_org
    ):
        rc = _make_realtime_channel(db, default_org)
        url = reverse("twiliochannel-list")
        payload = {
            "channel": rc.pk,
            "account_sid": "AC_secret",
            "auth_token": "super-secret-token",
        }
        response = auth_client.post(url, payload, format="json")
        assert response.status_code == 201, response.json()
        assert "auth_token" not in response.json()

        # The token was actually persisted, even though it's never echoed back.
        tc = TwilioChannel.objects.get(channel=rc)
        assert tc.auth_token == "super-secret-token"

    def test_retrieve_does_not_leak_auth_token(self, auth_client, db, default_org):
        rc = _make_realtime_channel(db, default_org)
        TwilioChannel.objects.create(
            channel=rc, account_sid="AC_test", auth_token="retrieve-secret"
        )

        url = reverse("twiliochannel-detail", args=[rc.pk])
        response = auth_client.get(url)
        assert response.status_code == 200, response.json()
        assert "auth_token" not in response.json()

    def test_list_does_not_leak_auth_token(self, auth_client, db, default_org):
        rc = _make_realtime_channel(db, default_org)
        TwilioChannel.objects.create(
            channel=rc, account_sid="AC_test", auth_token="list-secret"
        )

        url = reverse("twiliochannel-list")
        response = auth_client.get(url)
        assert response.status_code == 200, response.json()
        results = response.json()
        results = results.get("results", results)
        assert len(results) >= 1
        for item in results:
            assert "auth_token" not in item

    def test_update_accepts_but_does_not_echo_auth_token(
        self, auth_client, db, default_org
    ):
        rc = _make_realtime_channel(db, default_org)
        tc = TwilioChannel.objects.create(
            channel=rc, account_sid="AC_test", auth_token="old-secret"
        )

        url = reverse("twiliochannel-detail", args=[rc.pk])
        response = auth_client.patch(
            url, {"auth_token": "new-secret"}, format="json"
        )
        assert response.status_code == 200, response.json()
        assert "auth_token" not in response.json()

        tc.refresh_from_db()
        assert tc.auth_token == "new-secret"

    def test_realtime_channel_nested_read_still_omits_auth_token(
        self, auth_client, db, default_org
    ):
        """Regression guard for the realtime-channels read path
        (_TwilioChannelReadSerializer), which was already correct before
        this fix and must remain so."""
        rc = _make_realtime_channel(db, default_org)
        TwilioChannel.objects.create(
            channel=rc, account_sid="AC_test", auth_token="nested-secret"
        )

        url = reverse("realtimechannel-detail", args=[rc.pk])
        response = auth_client.get(url)
        assert response.status_code == 200, response.json()

        twilio = response.json().get("twilio")
        assert twilio is not None
        assert "auth_token" not in twilio


@pytest.mark.django_db
class TestRealtimeChannelLookupByToken:
    """EST-3631 (2nd STR): inbound Twilio calls have no logged-in user and no
    X-Organization-Id header. `realtime`'s get_channel_config() resolves the
    answering agent via GET /api/realtime-channels/lookup-by-token/?token=...,
    which must succeed for a valid token without any org context, while
    normal org-scoped CRUD on /realtime-channels/ keeps requiring it."""

    def _url(self):
        return reverse("realtimechannel-lookup-by-token")

    def test_lookup_by_token_succeeds_with_system_api_key_no_org_header(
        self, api_client, db, default_org, env_api_key
    ):
        """A system-API-key caller (matching realtime's actual request shape:
        no Bearer JWT, no X-Organization-Id) resolves the channel by token."""
        raw_key, _key = env_api_key
        rc = _make_realtime_channel(db, default_org)
        api_client.credentials(HTTP_X_API_KEY=raw_key)

        response = api_client.get(self._url(), {"token": str(rc.token)})

        assert response.status_code == 200, response.json()
        assert response.json()["id"] == rc.pk

    def test_lookup_by_token_unknown_token_returns_404(
        self, api_client, db, env_api_key
    ):
        raw_key, _key = env_api_key
        api_client.credentials(HTTP_X_API_KEY=raw_key)

        response = api_client.get(
            self._url(), {"token": "00000000-0000-0000-0000-000000000000"}
        )

        assert response.status_code == 404

    def test_lookup_by_token_invalid_token_returns_404(
        self, api_client, db, env_api_key
    ):
        """A malformed (non-UUID) token must 404, not 500."""
        raw_key, _key = env_api_key
        api_client.credentials(HTTP_X_API_KEY=raw_key)

        response = api_client.get(self._url(), {"token": "not-a-uuid"})

        assert response.status_code == 404

    def test_lookup_by_token_missing_token_returns_400(
        self, api_client, db, env_api_key
    ):
        raw_key, _key = env_api_key
        api_client.credentials(HTTP_X_API_KEY=raw_key)

        response = api_client.get(self._url())

        assert response.status_code == 400

    def test_lookup_by_token_rejects_unauthenticated_caller(self, api_client, db, default_org):
        rc = _make_realtime_channel(db, default_org)

        response = api_client.get(self._url(), {"token": str(rc.token)})

        assert response.status_code == 401

    def test_lookup_by_token_rejects_jwt_session_bypass(
        self, auth_client, db, default_org
    ):
        """A regular JWT-authenticated user must NOT be able to use this
        org-bypass path even for their own org's channel — IsSystemApiKeyAuthenticated
        requires ApiKey auth specifically, not just IsAuthenticated."""
        rc = _make_realtime_channel(db, default_org)

        response = auth_client.get(self._url(), {"token": str(rc.token)})

        assert response.status_code == 403

    def test_lookup_by_token_rejects_user_scoped_api_key(
        self, api_client, db, default_org, user_api_key
    ):
        """EST-3633 regression: a self-issued `key_type=USER` API key (any org
        member can mint one via POST /api/profile/api-keys/) must NOT be able
        to use this org-bypass path, even for their own org's channel.
        IsSystemApiKeyAuthenticated requires key_type=SYSTEM specifically —
        the generic IsApiKeyAuthenticated (system OR user) is not enough here,
        since this action performs no org filter of its own."""
        raw_key, _key = user_api_key
        rc = _make_realtime_channel(db, default_org)
        api_client.credentials(HTTP_X_API_KEY=raw_key)

        response = api_client.get(self._url(), {"token": str(rc.token)})

        assert response.status_code == 403

    def test_lookup_by_token_user_scoped_api_key_cannot_leak_other_org_twilio_secret(
        self, api_client, db, user_api_key
    ):
        """EST-3633 regression: a USER-scoped API key must not be able to read
        another org's TwilioChannel.auth_token by guessing/observing a
        RealtimeChannel token — it is rejected before any lookup happens."""
        raw_key, _key = user_api_key
        other_org = Organization.objects.create(name="Other Org")
        rc = _make_realtime_channel(db, other_org)
        TwilioChannel.objects.create(
            channel=rc, account_sid="AC_test", auth_token="other-org-secret"
        )
        api_client.credentials(HTTP_X_API_KEY=raw_key)

        response = api_client.get(self._url(), {"token": str(rc.token)})

        assert response.status_code == 403

    def test_lookup_by_token_crosses_org_boundary_for_api_key_caller(
        self, api_client, db, env_api_key
    ):
        """By design: the token itself is the authorization key, so a valid
        system-API-key caller can resolve a channel regardless of which org
        owns it — this is the whole point (Twilio has no org context)."""
        raw_key, _key = env_api_key
        org_a = Organization.objects.create(name="Org A")
        org_b = Organization.objects.create(name="Org B")
        rc_a = _make_realtime_channel(db, org_a)
        rc_b = _make_realtime_channel(db, org_b)
        api_client.credentials(HTTP_X_API_KEY=raw_key)

        resp_a = api_client.get(self._url(), {"token": str(rc_a.token)})
        resp_b = api_client.get(self._url(), {"token": str(rc_b.token)})

        assert resp_a.status_code == 200
        assert resp_a.json()["id"] == rc_a.pk
        assert resp_b.status_code == 200
        assert resp_b.json()["id"] == rc_b.pk

    def test_lookup_by_token_includes_twilio_auth_token_for_api_key_caller(
        self, api_client, db, default_org, env_api_key
    ):
        """EST-3633 follow-up: lookup-by-token is the ONE legitimate internal
        consumer that must still receive twilio.auth_token — `realtime`'s
        get_channel_config()/_twilio_voice_webhook() needs it to validate the
        inbound X-Twilio-Signature header. This is gated by
        IsSystemApiKeyAuthenticated (key_type=SYSTEM only), so it does not
        reopen the public leak fixed by TestTwilioChannelAuthTokenNotLeaked,
        nor the USER-key regression fixed in
        test_lookup_by_token_rejects_user_scoped_api_key."""
        raw_key, _key = env_api_key
        rc = _make_realtime_channel(db, default_org)
        TwilioChannel.objects.create(
            channel=rc,
            account_sid="AC_test",
            auth_token="webhook-signature-secret",
        )
        api_client.credentials(HTTP_X_API_KEY=raw_key)

        response = api_client.get(self._url(), {"token": str(rc.token)})

        assert response.status_code == 200, response.json()
        twilio = response.json().get("twilio")
        assert twilio is not None
        assert twilio["auth_token"] == "webhook-signature-secret"

    def test_list_still_requires_org_context(self, api_client, db, env_api_key):
        """Regression guard: normal list/CRUD on /realtime-channels/ must keep
        requiring org context — only the dedicated lookup-by-token action is
        exempt. A system-API-key caller with no X-Organization-Id still 400s
        on list() because get_queryset() (OrgScopedViewSetMixin) always
        resolves org context, superadmin bypass or not."""
        raw_key, _key = env_api_key
        api_client.credentials(HTTP_X_API_KEY=raw_key)

        response = api_client.get(reverse("realtimechannel-list"))

        assert response.status_code == 400
        assert response.json()["code"] == "org_context_required"
