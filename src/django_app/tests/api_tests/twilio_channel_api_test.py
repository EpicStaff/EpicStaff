import itertools
import urllib.error
from unittest import mock

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from agents.models import AgentDefinition

from tables.models.webhook_models import (
    LocalhostWebhookConfig,
    NgrokWebhookConfig,
    ProviderType,
    RealtimeChannel,
    TwilioChannel,
    WebhookTrigger,
)
from tables.models import Agent
from tables.models.realtime_models import RealtimeAgent, RealtimeAgentDefinition
from rbac.authorship import record_last_edit
from rbac.models import Organization
from tables.services.secrets import secret_resolver, secret_service

# Every fixture/test in this module needs a uniquely-named Secret (org-scoped
# unique name) — a bare counter keeps that trivial without threading a name
# through every call site.
_secret_name_counter = itertools.count(1)


def _make_secret(org, text):
    return secret_service.create(
        text=text, org=org, name=f"twilio-test-secret-{next(_secret_name_counter)}"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_realtime_channel(db, org, **kwargs):
    """Create a minimal RealtimeChannel (no RealtimeAgent required).

    RealtimeChannel is org-scoped — every direct ORM
    .create() must pass `org`, same as the API path stamps it via the
    active org (OrgScopedViewSetMixin.perform_create).
    """
    return RealtimeChannel.objects.create(name="test-channel", org=org, **kwargs)


def _make_twilio_channel(realtime_channel, org=None, **kwargs):
    """Create a TwilioChannel attached to `realtime_channel`.

    TwilioChannel itself has no `org` column — org
    lives on the parent RealtimeChannel. `org` is accepted only for
    call-site compatibility; it is also used to scope the Secret created for
    `auth_token_secret` when the caller doesn't supply its own.

    `auth_token` is now a Secret reference (`auth_token_secret`) rather than a
    plaintext CharField — mirrors the fixture pattern already established for
    Telegram in `telegram_trigger_node_api_test.py`. Callers may pass their
    own `auth_token_secret=` kwarg to control the plaintext exactly.
    """
    if "auth_token_secret" not in kwargs:
        kwargs["auth_token_secret"] = _make_secret(
            org or realtime_channel.org, "auth_test"
        )
    account_sid = kwargs.pop("account_sid", "AC_test")
    return TwilioChannel.objects.create(
        channel=realtime_channel,
        account_sid=account_sid,
        **kwargs,
    )


def _make_webhook_trigger_with_ngrok(org, path="test-voice", domain=None):
    # WebhookTrigger is now org-owned — every direct ORM .create()
    # must pass `org`, same as the API path stamps it via the active org.
    trigger = WebhookTrigger.objects.create(
        path=path, provider_type=ProviderType.NGROK, org=org
    )
    NgrokWebhookConfig.objects.create(
        trigger=trigger,
        name="test-ngrok",
        auth_token_secret=_make_secret(org, "tok"),
        region=NgrokWebhookConfig.Region.EU,
        domain=domain,
    )
    return trigger


def _make_realtime_agent(org):
    """Create a staff RealtimeAgent (the removed legacy destination).

    `RealtimeAgent.agent` is a OneToOneField primary key onto the also-removed
    staff `Agent` model, so this is the only way to build a value for
    `RealtimeChannel.realtime_agent` — the model and FK are still on the DB,
    only their API surface was removed.
    """
    agent = Agent.objects.create(role="r", goal="g", backstory="b", org=org)
    return RealtimeAgent.objects.create(agent=agent)


def _make_realtime_agent_definition(org):
    """Create a RealtimeAgentDefinition — the only supported destination
    going forward for `RealtimeChannel.realtime_agent_definition`."""
    agent_definition = AgentDefinition.objects.create(
        org=org, name="voice-agent-definition"
    )
    return RealtimeAgentDefinition.objects.create(agent_definition=agent_definition)


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
    def test_create_twilio_channel_without_webhook_trigger(
        self, auth_client, db, default_org
    ):
        """POST without webhook_trigger should create successfully with null trigger."""
        rc = _make_realtime_channel(db, default_org)
        secret = _make_secret(default_org, "tok_noauth")
        url = reverse("twiliochannel-list")
        payload = {
            "channel": rc.pk,
            "account_sid": "AC_nosid",
            "auth_token_secret_id": secret.id,
        }
        response = auth_client.post(url, payload, format="json")
        assert response.status_code == 201, response.json()
        assert response.json()["webhook_trigger"] is None

    def test_create_twilio_channel_with_ngrok_trigger(
        self, auth_client, db, default_org
    ):
        """POST with webhook_trigger FK; GET should return nested webhook_trigger with live_url=null."""
        rc = _make_realtime_channel(db, default_org)
        trigger = _make_webhook_trigger_with_ngrok(default_org, path="voice-ngrok-test")
        secret = _make_secret(default_org, "tok_ngrok")

        url = reverse("twiliochannel-list")
        payload = {
            "channel": rc.pk,
            "account_sid": "AC_ngrok",
            "auth_token_secret_id": secret.id,
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

    def test_create_twilio_channel_rejected_when_trigger_already_kind_webhook(
        self, auth_client, db, default_org
    ):
        """A trigger already claimed by `kind=webhook` auth cannot
        be repointed to by a TwilioChannel -- claiming it would silently
        collide with the Twilio-kind auth sync."""
        from tables.models.webhook_models import WebhookTriggerAuth, WebhookTriggerAuthKind

        rc = _make_realtime_channel(db, default_org)
        trigger = _make_webhook_trigger_with_ngrok(default_org, path="claimed-webhook-kind")
        WebhookTriggerAuth.objects.create(
            trigger=trigger, kind=WebhookTriggerAuthKind.WEBHOOK
        )
        secret = _make_secret(default_org, "tok_conflict")

        url = reverse("twiliochannel-list")
        response = auth_client.post(
            url,
            {
                "channel": rc.pk,
                "account_sid": "AC_conflict",
                "auth_token_secret_id": secret.id,
                "webhook_trigger": trigger.pk,
            },
            format="json",
        )

        assert response.status_code == 400, response.json()
        assert not TwilioChannel.objects.filter(channel=rc).exists()

    def test_update_twilio_channel_rejected_when_trigger_already_kind_telegram(
        self, auth_client, db, default_org
    ):
        """Same rejection on update (repointing an existing TwilioChannel at
        an already-telegram-claimed trigger)."""
        from tables.models.webhook_models import WebhookTriggerAuth, WebhookTriggerAuthKind

        rc = _make_realtime_channel(db, default_org)
        tc = _make_twilio_channel(rc, default_org)
        trigger = _make_webhook_trigger_with_ngrok(default_org, path="claimed-telegram-kind")
        WebhookTriggerAuth.objects.create(
            trigger=trigger, kind=WebhookTriggerAuthKind.TELEGRAM
        )

        url = reverse("twiliochannel-detail", args=[tc.channel_id])
        response = auth_client.patch(
            url, {"webhook_trigger": trigger.pk}, format="json"
        )

        assert response.status_code == 400, response.json()
        tc.refresh_from_db()
        assert tc.webhook_trigger_id is None

    def test_two_channels_share_one_trigger(self, auth_client, db, default_org):
        """Two TwilioChannels may point at the same WebhookTrigger."""
        rc1 = _make_realtime_channel(db, default_org)
        rc2 = RealtimeChannel.objects.create(name="channel-b", org=default_org)
        trigger = _make_webhook_trigger_with_ngrok(default_org, path="shared-trigger")

        url = reverse("twiliochannel-list")
        for rc, sid in [(rc1, "AC_one"), (rc2, "AC_two")]:
            secret = _make_secret(default_org, "auth")
            response = auth_client.post(
                url,
                {
                    "channel": rc.pk,
                    "account_sid": sid,
                    "auth_token_secret_id": secret.id,
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
        trigger = _make_webhook_trigger_with_ngrok(
            default_org, path="removable-trigger"
        )
        tc = _make_twilio_channel(rc, default_org, webhook_trigger=trigger)

        url = reverse("twiliochannel-detail", args=[tc.channel_id])
        response = auth_client.patch(url, {"webhook_trigger": None}, format="json")
        assert response.status_code == 200, response.json()
        assert response.json()["webhook_trigger"] is None

        tc.refresh_from_db()
        assert tc.webhook_trigger_id is None

    def test_create_twilio_channel_rejected_when_trigger_is_localhost_provider(
        self, auth_client, db, default_org
    ):
        """`TwilioChannelSerializer.validate()` already rejects a localhost
        `provider_type` at attach time (this was live-tested to confirm it's
        wired, not a dangling `TwilioChannel.validate_provider()` check that
        only fires later at `configure-webhook` dispatch)."""
        rc = _make_realtime_channel(db, default_org)
        trigger = _make_webhook_trigger_with_localhost(
            default_org, path="create-time-localhost-reject"
        )
        secret = _make_secret(default_org, "tok_localhost_reject")

        url = reverse("twiliochannel-list")
        response = auth_client.post(
            url,
            {
                "channel": rc.pk,
                "account_sid": "AC_localhost_reject",
                "auth_token_secret_id": secret.id,
                "webhook_trigger": trigger.pk,
            },
            format="json",
        )

        assert response.status_code == 400, response.json()
        assert "localhost" in str(response.json()).lower()
        assert not TwilioChannel.objects.filter(channel=rc).exists()

    def test_configure_webhook_rejects_localhost_provider(
        self, auth_client, db, default_org
    ):
        """configure-webhook must 400 when the trigger uses the localhost provider."""
        rc = _make_realtime_channel(db, default_org)
        trigger = _make_webhook_trigger_with_localhost(
            default_org, path="cfg-localhost"
        )
        _make_twilio_channel(
            rc,
            default_org,
            webhook_trigger=trigger,
            account_sid="AC" + "0" * 32,
        )

        url = reverse("twilio-configure-webhook")
        response = auth_client.post(
            url,
            {
                "phone_sid": "PN" + "0" * 32,
                "channel_token": str(rc.token),
            },
            format="json",
        )
        assert response.status_code == 400, response.json()
        assert "localhost" in response.json()["error"].lower()

    @pytest.mark.parametrize(
        ("make_trigger", "error"),
        [
            (lambda org: _make_webhook_trigger_with_ngrok(org, path="vp-ngrok"), None),
            (lambda org: _make_webhook_trigger_with_localhost(org, path="vp-localhost"), "localhost"),
            (lambda org: None, "no webhook trigger"),
        ],
        ids=["ngrok", "localhost", "no-trigger"],
    )
    def test_validate_provider_accepts_only_a_publicly_reachable_trigger(self, db, default_org, make_trigger, error):
        rc = _make_realtime_channel(db, default_org)
        trigger = make_trigger(default_org)
        tc = _make_twilio_channel(rc, default_org, **({"webhook_trigger": trigger} if trigger else {}))

        message = tc.validate_provider()

        if error is None:
            assert message is None
        else:
            assert error in message.lower()

    def test_realtime_channel_get_expands_twilio_webhook_trigger(
        self, auth_client, db, default_org
    ):
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
    """create() looks up an existing TwilioChannel row via a raw,
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
        original_secret_id = tc_b.auth_token_secret_id
        # The attacker calls as a member of `default_org` (the active org for
        # `auth_client`) — an `OrgScopedPrimaryKeyRelatedField` only resolves
        # pks visible to the caller's own active org, so the hijack secret
        # must belong to `default_org`, not `org_b`.
        hijack_secret = _make_secret(default_org, "hijacked-token")

        url = reverse("twiliochannel-list")
        response = auth_client.post(
            url,
            {
                "channel": rc_b.pk,
                "account_sid": "AC_hijacked",
                "auth_token_secret_id": hijack_secret.id,
                "phone_number": "+19999999999",
            },
            format="json",
        )

        assert response.status_code == 404, response.json()

        tc_b.refresh_from_db()
        assert tc_b.account_sid == "AC_test"
        assert tc_b.auth_token_secret_id == original_secret_id
        assert (
            secret_resolver.resolve(
                secret_id=tc_b.auth_token_secret_id, org_id=org_b.id
            )
            == "auth_test"
        )
        assert tc_b.phone_number == "+10000000000"


@pytest.mark.django_db
class TestTwilioChannelUpdateCannotMoveToOtherOrgChannel:
    """`channel` is the model's primary key and its serializer field is not
    org-scoped. An update that rewrites it makes Django INSERT a new row, so
    without a parent-org check on update a caller would create a Twilio config
    under another org's realtime channel (which then blocks that org's own)."""

    @pytest.mark.parametrize("method", ["put", "patch"])
    def test_update_rejects_moving_config_to_other_org_channel(
        self, method, auth_client, db, default_org
    ):
        org_b = Organization.objects.create(name="Org B")
        victim_channel = _make_realtime_channel(db, org_b)
        own_channel = _make_realtime_channel(db, default_org)
        own_twilio = _make_twilio_channel(own_channel, default_org)
        secret = _make_secret(default_org, "attacker-token")

        response = getattr(auth_client, method)(
            reverse("twiliochannel-detail", args=[own_channel.pk]),
            {
                "channel": victim_channel.pk,
                "account_sid": "AC_attacker",
                "auth_token_secret_id": secret.id,
            },
            format="json",
        )

        assert response.status_code == 404, response.content
        assert not TwilioChannel.objects.filter(channel=victim_channel).exists()
        own_twilio.refresh_from_db()
        assert own_twilio.account_sid == "AC_test"

    def test_update_still_works_within_the_active_org(
        self, auth_client, db, default_org
    ):
        own_channel = _make_realtime_channel(db, default_org)
        _make_twilio_channel(own_channel, default_org)
        secret = _make_secret(default_org, "new-token")

        response = auth_client.put(
            reverse("twiliochannel-detail", args=[own_channel.pk]),
            {
                "channel": own_channel.pk,
                "account_sid": "AC_renamed",
                "auth_token_secret_id": secret.id,
            },
            format="json",
        )

        assert response.status_code == 200, response.content
        assert TwilioChannel.objects.get(channel=own_channel).account_sid == "AC_renamed"


@pytest.mark.django_db
class TestTwilioChannelAuthTokenNotLeaked:
    """auth_token must never appear in a twilio-channels response
    body (list/retrieve/create/update), though it must remain writable.
    Regression guard: the realtime-channels nested read path
    (_TwilioChannelReadSerializer) must also keep omitting it."""

    @pytest.mark.parametrize("operation", ["create", "update"])
    def test_auth_token_is_writable_but_never_echoed(self, auth_client, db, default_org, operation):
        rc = _make_realtime_channel(db, default_org)
        secret = _make_secret(default_org, "super-secret-token")
        if operation == "create":
            response = auth_client.post(
                reverse("twiliochannel-list"),
                {"channel": rc.pk, "account_sid": "AC_secret", "auth_token_secret_id": secret.id},
                format="json",
            )
            assert response.status_code == 201, response.json()
        else:
            TwilioChannel.objects.create(
                channel=rc, account_sid="AC_test", auth_token_secret=_make_secret(default_org, "old-secret")
            )
            response = auth_client.patch(
                reverse("twiliochannel-detail", args=[rc.pk]), {"auth_token_secret_id": secret.id}, format="json"
            )
            assert response.status_code == 200, response.json()

        assert "auth_token" not in response.json()
        stored = TwilioChannel.objects.get(channel=rc)
        assert secret_resolver.resolve(secret_id=stored.auth_token_secret_id, org_id=default_org.id) == "super-secret-token"

    @pytest.mark.parametrize(
        "read",
        [
            lambda client, rc: client.get(reverse("twiliochannel-detail", args=[rc.pk])),
            lambda client, rc: client.get(reverse("twiliochannel-list")),
            # The realtime-channels nested read path (_TwilioChannelReadSerializer).
            lambda client, rc: client.get(reverse("realtimechannel-detail", args=[rc.pk])),
        ],
        ids=["retrieve", "list", "realtime-channel-nested"],
    )
    def test_reads_never_carry_the_auth_token(self, auth_client, db, default_org, read):
        rc = _make_realtime_channel(db, default_org)
        TwilioChannel.objects.create(
            channel=rc, account_sid="AC_test", auth_token_secret=_make_secret(default_org, "read-secret")
        )

        response = read(auth_client, rc)

        assert response.status_code == 200, response.json()
        assert '"auth_token":' not in response.content.decode()
        assert "read-secret" not in response.content.decode()

@pytest.mark.django_db
class TestRealtimeChannelLookupByToken:
    """inbound Twilio calls have no logged-in user and no
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

    @pytest.mark.parametrize(
        "token",
        [lambda rc: str(rc.token), lambda rc: "00000000-0000-0000-0000-000000000000", lambda rc: "not-a-uuid"],
        ids=["disabled-channel", "unknown-token", "malformed-token"],
    )
    def test_lookup_of_a_channel_that_cannot_answer_is_one_indistinguishable_404(
        self, api_client, db, default_org, env_api_key, token
    ):
        """A disabled channel (an operator's containment action) must not resolve, and
        must look exactly like an unknown token, so the response never confirms a
        guessed token. A malformed token is a 404 too, not a 500."""
        raw_key, _key = env_api_key
        rc = _make_realtime_channel(db, default_org, is_enabled=False)
        api_client.credentials(HTTP_X_API_KEY=raw_key)
        unknown = api_client.get(self._url(), {"token": "00000000-0000-0000-0000-000000000000"})

        response = api_client.get(self._url(), {"token": token(rc)})

        assert response.status_code == 404
        assert response.content == unknown.content

    def test_lookup_by_token_missing_token_returns_400(
        self, api_client, db, env_api_key
    ):
        raw_key, _key = env_api_key
        api_client.credentials(HTTP_X_API_KEY=raw_key)

        response = api_client.get(self._url())

        assert response.status_code == 400

    @pytest.mark.parametrize(
        ("caller", "own_org", "expected_status"),
        [
            ("anonymous", True, 401),
            # Only a SYSTEM api key may use this org-bypass path: no org filter applies here.
            ("jwt-user", True, 403),
            ("user-api-key", True, 403),
            ("user-api-key", False, 403),
        ],
        ids=["anonymous", "jwt-user", "user-api-key", "user-api-key-other-org"],
    )
    def test_lookup_by_token_is_only_for_the_system_api_key(
        self, request, api_client, db, default_org, caller, own_org, expected_status
    ):
        org = default_org if own_org else Organization.objects.create(name="Other Org")
        rc = _make_realtime_channel(db, org)
        TwilioChannel.objects.create(
            channel=rc, account_sid="AC_test", auth_token_secret=_make_secret(org, "lookup-secret")
        )
        client = api_client
        if caller == "jwt-user":
            client = request.getfixturevalue("auth_client")
        elif caller == "user-api-key":
            raw_key, _key = request.getfixturevalue("user_api_key")
            client.credentials(HTTP_X_API_KEY=raw_key)

        response = client.get(self._url(), {"token": str(rc.token)})

        assert response.status_code == expected_status
        assert "lookup-secret" not in response.content.decode()

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
        """lookup-by-token is the ONE legitimate internal
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
            auth_token_secret=_make_secret(default_org, "webhook-signature-secret"),
        )
        api_client.credentials(HTTP_X_API_KEY=raw_key)

        response = api_client.get(self._url(), {"token": str(rc.token)})

        assert response.status_code == 200, response.json()
        twilio = response.json().get("twilio")
        assert twilio is not None
        assert twilio["auth_token"] == "webhook-signature-secret"

    def test_lookup_by_token_omits_authorship_and_reads_no_user(
        self, api_client, db, default_org, env_api_key, django_user_model
    ):
        """The realtime service never reads authorship, so lookup-by-token sends no
        user ids, names or avatars -- top level or on the nested webhook trigger --
        and loads no user or last edit to render them."""
        raw_key, _key = env_api_key
        editor = django_user_model.objects.create_user(
            email="lookup-editor@example.com",
            password="StrongPass123!",
            display_name="Lookup Editor Name",
        )
        rc = _make_realtime_channel(db, default_org, created_by=editor)
        trigger = _make_webhook_trigger_with_ngrok(default_org, path="lookup-authorship")
        _make_twilio_channel(rc, webhook_trigger=trigger)
        record_last_edit(rc, editor)
        record_last_edit(trigger, editor)
        api_client.credentials(HTTP_X_API_KEY=raw_key)

        with CaptureQueriesContext(connection) as captured:
            response = api_client.get(self._url(), {"token": str(rc.token)})

        assert response.status_code == 200, response.json()
        body = response.json()
        assert body["twilio"]["webhook_trigger"]["id"] == trigger.pk
        authorship_keys = {"created_by", "last_edited_by", "last_edited_at"}
        assert not authorship_keys & set(body)
        assert not authorship_keys & set(body["twilio"]["webhook_trigger"])
        assert "Lookup Editor Name" not in response.content.decode()
        authorship_tables = ('FROM "rbac_user"', 'FROM "rbac_resourcelastedit"')
        assert not [
            query["sql"]
            for query in captured.captured_queries
            if any(table in query["sql"] for table in authorship_tables)
        ]

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


# A syntactically valid Account SID: the action rejects anything else before
# resolving the secret.
VALID_ACCOUNT_SID = "AC" + "0" * 32


@pytest.mark.django_db
class TestTwilioChannelPhoneNumbersAction:
    """GET /twilio-channels/phone-numbers/?sid=&auth_token_secret_id= lists an
    account's Twilio numbers before a channel is saved. The caller sends the
    account SID and the id of a Secret in its own org; the auth token is
    resolved server-side, so the frontend never handles the raw token."""

    def _fake_twilio_response(self, *args, **kwargs):
        return {
            "incoming_phone_numbers": [
                {
                    "sid": "PNxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
                    "phone_number": "+15551234567",
                    "friendly_name": "My Twilio Number",
                    "voice_url": "https://example.com/voice",
                }
            ]
        }

    def test_returns_phone_numbers_for_own_org_secret(self, auth_client, default_org):
        secret = _make_secret(default_org, "auth_test")

        url = reverse("twiliochannel-phone-numbers")
        with mock.patch(
            "tables.services.twilio_service._twilio_request",
            side_effect=self._fake_twilio_response,
        ) as mocked:
            response = auth_client.get(
                url, {"sid": VALID_ACCOUNT_SID, "auth_token_secret_id": secret.id}
            )

        assert response.status_code == 200, response.json()
        assert response.json() == {
            "results": [
                {
                    "sid": "PNxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
                    "phone_number": "+15551234567",
                    "friendly_name": "My Twilio Number",
                    "voice_url": "https://example.com/voice",
                }
            ]
        }
        assert "auth_test" not in response.content.decode()
        # The resolved plaintext token (not the secret id) was passed through
        # to the Twilio call, together with the requested account SID.
        called_account_sid, called_auth_token = mocked.call_args.args[:2]
        assert called_account_sid == VALID_ACCOUNT_SID
        assert called_auth_token == "auth_test"

    @pytest.mark.parametrize(
        "query",
        [
            lambda foreign: {"sid": VALID_ACCOUNT_SID},
            # A secret id of another org resolves like any unknown id, and its token never leaks.
            lambda foreign: {"sid": VALID_ACCOUNT_SID, "auth_token_secret_id": foreign.id},
            lambda foreign: {"sid": VALID_ACCOUNT_SID, "auth_token_secret_id": "not-an-id"},
            lambda foreign: {"sid": "not-a-valid-sid", "auth_token_secret_id": "1"},
        ],
        ids=["no-secret", "other-orgs-secret", "non-integer-secret-id", "invalid-account-sid"],
    )
    def test_bad_credentials_are_400_without_calling_twilio(self, auth_client, db, query):
        foreign_secret = _make_secret(Organization.objects.create(name="Other Org (phone-numbers)"), "foreign_auth_token")

        with mock.patch("tables.services.twilio_service._twilio_request") as mocked:
            response = auth_client.get(reverse("twiliochannel-phone-numbers"), query(foreign_secret))

        assert response.status_code == 400, response.content
        assert "error" in response.json()
        assert "foreign_auth_token" not in response.content.decode()
        mocked.assert_not_called()

    def test_foreign_secret_rejection_matches_a_nonexistent_id(self, auth_client, db):
        """Existence in another org must not leak: both ids get the same 400."""
        other_org = Organization.objects.create(name="Other Org (phone-numbers leak)")
        foreign_secret = _make_secret(other_org, "foreign_auth_token")
        missing_id = foreign_secret.id + 1000

        url = reverse("twiliochannel-phone-numbers")
        with mock.patch("tables.services.twilio_service._twilio_request") as mocked:
            foreign = auth_client.get(
                url,
                {"sid": VALID_ACCOUNT_SID, "auth_token_secret_id": foreign_secret.id},
            )
            missing = auth_client.get(
                url, {"sid": VALID_ACCOUNT_SID, "auth_token_secret_id": missing_id}
            )

        mocked.assert_not_called()
        assert foreign.status_code == missing.status_code == 400

        def without_digits(body):
            return "".join(character for character in body if not character.isdigit())

        assert without_digits(foreign.content.decode()) == without_digits(missing.content.decode())

@pytest.mark.django_db
class TestTwilioConfigureWebhookInputValidation:
    """TwilioConfigureWebhookView must reject malformed SIDs before
    ever interpolating them into a Twilio REST URL, and must never reflect a
    raw upstream Twilio error body back to the caller."""

    @pytest.mark.parametrize(
        ("account_sid", "phone_sid", "token", "enabled", "expected_status", "error"),
        [
            ("AC" + "0" * 32, "PN_not_a_valid_sid", None, True, 400, "Invalid phone_sid"),
            # Not client-supplied here, but a malformed stored value must not reach the Twilio URL either.
            ("AC_not_valid", "PN" + "0" * 32, None, True, 400, "Invalid account_sid"),
            # RealtimeChannel.token is a UUIDField: a malformed token is a 404, not a 500.
            ("AC" + "0" * 32, "PN" + "0" * 32, "qwe", True, 404, "Channel not found"),
            # A disabled channel looks exactly like a missing one.
            ("AC" + "0" * 32, "PN" + "0" * 32, None, False, 404, "Channel not found"),
        ],
        ids=["invalid-phone-sid", "invalid-stored-account-sid", "malformed-token", "disabled-channel"],
    )
    def test_invalid_request_never_reaches_twilio(
        self, auth_client, db, default_org, account_sid, phone_sid, token, enabled, expected_status, error
    ):
        rc = _make_realtime_channel(db, default_org, is_enabled=enabled)
        trigger = _make_webhook_trigger_with_ngrok(default_org, path="cfg-invalid")
        _make_twilio_channel(rc, default_org, webhook_trigger=trigger, account_sid=account_sid)

        with mock.patch("tables.services.twilio_service._twilio_request") as mocked:
            response = auth_client.post(
                reverse("twilio-configure-webhook"),
                {"phone_sid": phone_sid, "channel_token": token or str(rc.token)},
                format="json",
            )

        assert response.status_code == expected_status, response.json()
        assert response.json() == {"error": error}
        mocked.assert_not_called()

    def test_twilio_http_error_returns_generic_sanitized_body(
        self, auth_client, db, default_org
    ):
        """A raw upstream Twilio error body (which can contain account
        details) must never be reflected verbatim to the caller."""
        rc = _make_realtime_channel(db, default_org)
        trigger = _make_webhook_trigger_with_ngrok(
            default_org,
            path="cfg-twilio-http-error",
            domain="cfg-error.example.ngrok.io",
        )
        _make_twilio_channel(
            rc,
            default_org,
            webhook_trigger=trigger,
            account_sid="AC" + "0" * 32,
        )

        raw_twilio_body = (
            '{"code": 20404, "message": "The requested resource '
            '/Accounts/ACxxxx/IncomingPhoneNumbers/PNxxxx.json was not found"}'
        )
        http_error = urllib.error.HTTPError(
            url="https://api.twilio.com/2010-04-01/Accounts/ACxxxx/IncomingPhoneNumbers/PNxxxx.json",
            code=404,
            msg="Not Found",
            hdrs=None,
            fp=mock.mock_open(read_data=raw_twilio_body.encode())(),
        )

        url = reverse("twilio-configure-webhook")
        with mock.patch(
            "tables.services.twilio_service._twilio_request", side_effect=http_error
        ):
            response = auth_client.post(
                url,
                {"phone_sid": "PN" + "0" * 32, "channel_token": str(rc.token)},
                format="json",
            )

        assert response.status_code == 404, response.json()
        assert response.json() == {"error": "Failed to configure Twilio webhook"}
        body_text = response.content.decode()
        assert "20404" not in body_text
        assert "ACxxxx" not in body_text

    def test_unexpected_twilio_failure_returns_generic_502(self, auth_client, db, default_org):
        """An error that is not a Twilio HTTP answer (unreachable host, bad
        JSON, a bug) is a 502 whose body never carries the error's text."""
        rc = _make_realtime_channel(db, default_org)
        trigger = _make_webhook_trigger_with_ngrok(
            default_org,
            path="cfg-twilio-unexpected-error",
            domain="cfg-unexpected.example.ngrok.io",
        )
        _make_twilio_channel(
            rc,
            default_org,
            webhook_trigger=trigger,
            account_sid="AC" + "0" * 32,
        )
        internal_detail = "egress-proxy.internal.svc:3128 refused the connection"

        with mock.patch(
            "tables.services.twilio_service._twilio_request",
            side_effect=urllib.error.URLError(internal_detail),
        ):
            response = auth_client.post(
                reverse("twilio-configure-webhook"),
                {"phone_sid": "PN" + "0" * 32, "channel_token": str(rc.token)},
                format="json",
            )

        assert response.status_code == 502, response.json()
        assert response.json() == {"error": "Failed to communicate with Twilio"}
        assert "egress-proxy" not in response.content.decode()


@pytest.mark.django_db
class TestRealtimeChannelLegacyAgentPointer:
    """`RealtimeChannel.realtime_agent` points at the removed staff-agent API
    surface (`RealtimeAgent`/`Agent`) and can no longer be served. The field
    and its DB column stay (migrations are frozen on this branch), but the
    serializer must make it read-only and self-healing so old rows are
    diagnosable and repairable through the API instead of permanently
    unrepairable 400s."""

    def test_create_ignores_realtime_agent_in_payload(
        self, auth_client, db, default_org
    ):
        """realtime_agent is read-only: sending it on create must not set it,
        and must not be rejected either — the field is simply ignored."""
        rt_agent = _make_realtime_agent(default_org)

        url = reverse("realtimechannel-list")
        response = auth_client.post(
            url,
            {"name": "ignores-realtime-agent", "realtime_agent": rt_agent.pk},
            format="json",
        )

        assert response.status_code == 201, response.json()
        assert response.json()["realtime_agent"] is None

        channel = RealtimeChannel.objects.get(pk=response.json()["id"])
        assert channel.realtime_agent_id is None

    def test_patch_realtime_agent_definition_repairs_stranded_channel(
        self, auth_client, db, default_org
    ):
        """A channel whose `realtime_agent` was already set in the DB
        (simulating a row created on `main`, before this field existed) is
        repaired by PATCHing `realtime_agent_definition`: the new
        destination wins and the dead legacy pointer is cleared, instead of
        the update being rejected as "both set"."""
        rt_agent = _make_realtime_agent(default_org)
        stranded_channel = RealtimeChannel.objects.create(
            name="stranded-channel", org=default_org, realtime_agent=rt_agent
        )
        rt_agent_definition = _make_realtime_agent_definition(default_org)

        url = reverse("realtimechannel-detail", args=[stranded_channel.pk])
        response = auth_client.patch(
            url,
            {"realtime_agent_definition": rt_agent_definition.pk},
            format="json",
        )

        assert response.status_code == 200, response.json()

        stranded_channel.refresh_from_db()
        assert stranded_channel.realtime_agent_id is None
        assert stranded_channel.realtime_agent_definition_id == rt_agent_definition.pk

    def test_get_still_exposes_stranded_realtime_agent(
        self, auth_client, db, default_org
    ):
        """GET must keep returning realtime_agent for a stranded row so
        operators can see which channels are still pointing at the removed
        destination — read-only visibility is preserved, only writes are
        blocked."""
        rt_agent = _make_realtime_agent(default_org)
        stranded_channel = RealtimeChannel.objects.create(
            name="visible-stranded-channel", org=default_org, realtime_agent=rt_agent
        )

        url = reverse("realtimechannel-detail", args=[stranded_channel.pk])
        response = auth_client.get(url)

        assert response.status_code == 200, response.json()
        assert response.json()["realtime_agent"] == rt_agent.pk

    def test_filter_by_realtime_agent_returns_only_stranded_channel(
        self, auth_client, db, default_org
    ):
        """`realtime_agent` was dropped from filterset_fields at one point
        with the field itself left read-only, which silently turned
        `?realtime_agent=<pk>` into a no-op filter — DjangoFilterBackend
        ignores unknown query params, so the endpoint returned every channel
        in the org instead of just the one bound to that legacy agent.
        Regression guard: the filter must still narrow the result set."""
        rt_agent = _make_realtime_agent(default_org)
        stranded_channel = RealtimeChannel.objects.create(
            name="stranded-for-filter", org=default_org, realtime_agent=rt_agent
        )
        rt_agent_definition = _make_realtime_agent_definition(default_org)
        RealtimeChannel.objects.create(
            name="other-destination-channel",
            org=default_org,
            realtime_agent_definition=rt_agent_definition,
        )

        url = reverse("realtimechannel-list")
        response = auth_client.get(url, {"realtime_agent": rt_agent.pk})

        assert response.status_code == 200, response.json()
        results = response.json()["results"]
        assert [row["id"] for row in results] == [stranded_channel.pk]

    def test_filter_by_realtime_agent_definition_still_works(
        self, auth_client, db, default_org
    ):
        """Adding `realtime_agent` back to filterset_fields must not disturb
        the existing, still-writable `realtime_agent_definition` filter."""
        rt_agent = _make_realtime_agent(default_org)
        RealtimeChannel.objects.create(
            name="stranded-not-matched", org=default_org, realtime_agent=rt_agent
        )
        rt_agent_definition = _make_realtime_agent_definition(default_org)
        matching_channel = RealtimeChannel.objects.create(
            name="matches-definition-filter",
            org=default_org,
            realtime_agent_definition=rt_agent_definition,
        )

        url = reverse("realtimechannel-list")
        response = auth_client.get(
            url, {"realtime_agent_definition": rt_agent_definition.pk}
        )

        assert response.status_code == 200, response.json()
        results = response.json()["results"]
        assert [row["id"] for row in results] == [matching_channel.pk]


@pytest.mark.django_db
class TestRealtimeChannelInactiveChannelStaysManageable:
    """`RealtimeChannel.enabled_objects` (the is_enabled-filtered manager)
    must only be used by inbound lookup paths (lookup_by_token,
    TwilioService.configure_webhook). The admin CRUD surface
    (RealtimeChannelViewSet) keeps using the plain, unfiltered `objects`
    manager so an operator who disabled a channel can still find it
    through list/retrieve in order to re-enable it -- disabling a
    channel must never make it disappear from normal management."""

    def test_inactive_channel_still_visible_in_list(self, auth_client, db, default_org):
        rc = _make_realtime_channel(db, default_org, is_enabled=False)

        url = reverse("realtimechannel-list")
        response = auth_client.get(url)

        assert response.status_code == 200, response.json()
        ids = [row["id"] for row in response.json()["results"]]
        assert rc.pk in ids

    def test_inactive_channel_still_retrievable_by_id(
        self, auth_client, db, default_org
    ):
        rc = _make_realtime_channel(db, default_org, is_enabled=False)

        url = reverse("realtimechannel-detail", args=[rc.pk])
        response = auth_client.get(url)

        assert response.status_code == 200, response.json()
        assert response.json()["is_enabled"] is False

    def test_inactive_channel_can_be_reactivated_via_patch(
        self, auth_client, db, default_org
    ):
        rc = _make_realtime_channel(db, default_org, is_enabled=False)

        url = reverse("realtimechannel-detail", args=[rc.pk])
        response = auth_client.patch(url, {"is_enabled": True}, format="json")

        assert response.status_code == 200, response.json()
        rc.refresh_from_db()
        assert rc.is_enabled is True
