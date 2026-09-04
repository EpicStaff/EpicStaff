"""Coverage for `webhook_signals.twilio_channel_post_save_handler`/
`twilio_channel_post_delete_handler` -- keeping `WebhookTriggerAuth(kind=twilio)`
in sync with `TwilioChannel.auth_token_secret` purely for query uniformity
(any `WebhookTrigger` can report which of the three strategies applies). This
does NOT drive actual Twilio verification, which stays
`validate_twilio_signature` (`src/realtime`) directly against
`auth_token_secret` -- see `ConverterService._convert_trigger_auth`, which
skips `kind=twilio` rows when building the payload for `src/webhook`.
"""

import pytest

from tables.models.rbac_models import Organization
from tables.models.webhook_models import (
    NgrokWebhookConfig,
    ProviderType,
    RealtimeChannel,
    TwilioChannel,
    WebhookTrigger,
    WebhookTriggerAuth,
    WebhookTriggerAuthKind,
)
from tables.services.secrets import secret_service


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org TwilioAuthSync")


def _make_trigger(org, path):
    trigger = WebhookTrigger.objects.create(
        path=path, provider_type=ProviderType.NGROK, org=org
    )
    NgrokWebhookConfig.objects.create(
        trigger=trigger,
        name=f"cfg-{path}",
        auth_token_secret=secret_service.create(
            text="tok", org=org, name=f"{path}-ngrok-secret"
        ),
    )
    return trigger


def _make_twilio_channel(org, trigger, secret):
    channel = RealtimeChannel.objects.create(name="Voice line", org=org)
    return TwilioChannel.objects.create(
        channel=channel,
        account_sid="AC_test",
        auth_token_secret=secret,
        webhook_trigger=trigger,
    )


@pytest.mark.django_db
class TestTwilioChannelAuthSync:
    def test_saving_twilio_channel_creates_twilio_kind_auth_on_its_trigger(self, org):
        trigger = _make_trigger(org, "twilio-sync-path")
        secret = secret_service.create(text="auth-token-1", org=org, name="tw-secret-1")

        _make_twilio_channel(org, trigger, secret)

        auth = WebhookTriggerAuth.objects.get(trigger=trigger)
        assert auth.kind == WebhookTriggerAuthKind.TWILIO
        assert auth.secret_id == secret.id

    def test_updating_auth_token_secret_updates_the_synced_auth(self, org):
        trigger = _make_trigger(org, "twilio-sync-update-path")
        first_secret = secret_service.create(
            text="auth-token-2", org=org, name="tw-secret-2"
        )
        channel = _make_twilio_channel(org, trigger, first_secret)

        second_secret = secret_service.create(
            text="auth-token-3", org=org, name="tw-secret-3"
        )
        channel.auth_token_secret = second_secret
        channel.save()

        auth = WebhookTriggerAuth.objects.get(trigger=trigger)
        assert auth.secret_id == second_secret.id

    def test_does_not_overwrite_auth_when_trigger_has_conflicting_auth_kind(self, org):
        """`TwilioChannelSerializer.validate()` already rejects this at the API
        boundary (400). This signal is the last line of defense for any path
        that bypasses the serializer (direct `.save()`, fixtures, management
        commands) -- it must not silently let the `TwilioChannel` steal/overwrite
        the trigger's existing auth row. It no longer raises (the `TwilioChannel`
        save itself succeeds), but the conflicting `WebhookTriggerAuth` row must
        be left completely untouched."""
        trigger = _make_trigger(org, "twilio-sync-conflict-path")
        WebhookTriggerAuth.objects.create(
            trigger=trigger, kind=WebhookTriggerAuthKind.WEBHOOK
        )
        secret = secret_service.create(text="auth-token-4", org=org, name="tw-secret-4")

        _make_twilio_channel(org, trigger, secret)

        auth = WebhookTriggerAuth.objects.get(trigger=trigger)
        assert auth.kind == WebhookTriggerAuthKind.WEBHOOK
        assert auth.secret_id is None

    def test_deleting_the_twilio_channel_removes_the_synced_auth(self, org):
        trigger = _make_trigger(org, "twilio-sync-delete-path")
        secret = secret_service.create(text="auth-token-5", org=org, name="tw-secret-5")
        channel = _make_twilio_channel(org, trigger, secret)
        assert WebhookTriggerAuth.objects.filter(trigger=trigger).exists()

        channel.delete()

        assert not WebhookTriggerAuth.objects.filter(trigger=trigger).exists()

    def test_deleting_one_of_two_channels_sharing_a_trigger_keeps_the_auth(
        self, org
    ):
        """Regression: `webhook_trigger` has `related_name="twilio_channels"`
        (plural) -- more than one `TwilioChannel` can legally point at the
        same `WebhookTrigger`. Deleting ONE must not delete the trigger's
        `kind=twilio` auth row while another channel is still relying on it.
        """
        trigger = _make_trigger(org, "twilio-sync-shared-delete-path")
        secret = secret_service.create(
            text="auth-token-shared-1", org=org, name="tw-secret-shared-1"
        )
        channel_a = _make_twilio_channel(org, trigger, secret)
        channel_b_realtime = RealtimeChannel.objects.create(
            name="Second voice line", org=org
        )
        TwilioChannel.objects.create(
            channel=channel_b_realtime,
            account_sid="AC_test_b",
            auth_token_secret=secret,
            webhook_trigger=trigger,
        )

        channel_a.delete()

        auth = WebhookTriggerAuth.objects.get(trigger=trigger)
        assert auth.kind == WebhookTriggerAuthKind.TWILIO

    def test_deleting_the_last_channel_on_a_shared_trigger_removes_the_auth(
        self, org
    ):
        trigger = _make_trigger(org, "twilio-sync-shared-delete-last-path")
        secret = secret_service.create(
            text="auth-token-shared-2", org=org, name="tw-secret-shared-2"
        )
        channel_a = _make_twilio_channel(org, trigger, secret)
        realtime_b = RealtimeChannel.objects.create(
            name="Second voice line b", org=org
        )
        channel_b = TwilioChannel.objects.create(
            channel=realtime_b,
            account_sid="AC_test_b2",
            auth_token_secret=secret,
            webhook_trigger=trigger,
        )

        channel_a.delete()
        channel_b.delete()

        assert not WebhookTriggerAuth.objects.filter(trigger=trigger).exists()

    def test_repointing_a_channel_cleans_up_the_old_triggers_auth(self, org):
        trigger_a = _make_trigger(org, "twilio-sync-repoint-a")
        trigger_b = _make_trigger(org, "twilio-sync-repoint-b")
        secret = secret_service.create(
            text="auth-token-repoint", org=org, name="tw-secret-repoint"
        )
        channel = _make_twilio_channel(org, trigger_a, secret)
        assert WebhookTriggerAuth.objects.filter(trigger=trigger_a).exists()

        channel.webhook_trigger = trigger_b
        channel.save()

        assert not WebhookTriggerAuth.objects.filter(trigger=trigger_a).exists()
        auth_b = WebhookTriggerAuth.objects.get(trigger=trigger_b)
        assert auth_b.kind == WebhookTriggerAuthKind.TWILIO
        assert auth_b.secret_id == secret.id

    def test_repointing_away_from_a_shared_trigger_keeps_the_old_auth(self, org):
        """The old trigger's auth must survive a repoint if another channel
        still references it."""
        trigger_a = _make_trigger(org, "twilio-sync-repoint-shared-a")
        trigger_b = _make_trigger(org, "twilio-sync-repoint-shared-b")
        secret = secret_service.create(
            text="auth-token-repoint-shared", org=org, name="tw-secret-repoint-shared"
        )
        channel_a = _make_twilio_channel(org, trigger_a, secret)
        realtime_c = RealtimeChannel.objects.create(
            name="Third voice line", org=org
        )
        TwilioChannel.objects.create(
            channel=realtime_c,
            account_sid="AC_test_c",
            auth_token_secret=secret,
            webhook_trigger=trigger_a,
        )

        channel_a.webhook_trigger = trigger_b
        channel_a.save()

        assert WebhookTriggerAuth.objects.filter(
            trigger=trigger_a, kind=WebhookTriggerAuthKind.TWILIO
        ).exists()

    def test_channel_with_no_webhook_trigger_creates_no_auth(self, org):
        channel_obj = RealtimeChannel.objects.create(name="No trigger line", org=org)
        secret = secret_service.create(text="auth-token-6", org=org, name="tw-secret-6")

        TwilioChannel.objects.create(
            channel=channel_obj, account_sid="AC_test", auth_token_secret=secret
        )

        assert not WebhookTriggerAuth.objects.exists()

    def test_the_converter_skips_twilio_kind_auth_for_the_webhook_service(self, org):
        """Twilio verification never runs through `src/webhook` -- the
        converter that feeds `WebhookConfigData` must treat a `kind=twilio`
        row the same as no auth at all."""
        from tables.services.converter_service import ConverterService

        trigger = _make_trigger(org, "twilio-sync-converter-path")
        secret = secret_service.create(text="auth-token-7", org=org, name="tw-secret-7")
        _make_twilio_channel(org, trigger, secret)

        ngrok_config = NgrokWebhookConfig.objects.select_related(
            "trigger", "trigger__auth", "trigger__auth__secret"
        ).get(trigger=trigger)
        pydantic_config = ConverterService().convert_ngrok_webhook_config_to_pydantic(
            ngrok_config
        )

        assert pydantic_config.auth is None
