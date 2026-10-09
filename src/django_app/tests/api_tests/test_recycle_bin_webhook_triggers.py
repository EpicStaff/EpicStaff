"""Webhook triggers: bin, tunnels follow the trigger, a taken path comes back with -N."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from tables.models import (
    Graph,
    LocalhostWebhookConfig,
    PythonCode,
    TelegramTriggerNode,
    RealtimeChannel,
    Secret,
    TwilioChannel,
    WebhookTrigger,
    WebhookTriggerAuth,
    WebhookTriggerNode,
)
from tables.services.recycle_bin.restore_service import RestoreService
from tables.services.secrets.secret_service import secret_service
from tables.services.telegram_trigger_service import TelegramTriggerService
from tables.services.webhook_trigger_service import WebhookTriggerService
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

pytestmark = pytest.mark.django_db

TRIGGERS_URL = "/api/webhook-triggers/"
REGISTER = "tables.signals.webhook_signals.WebhookTriggerService.register_webhooks"


@pytest.fixture
def admin_client(client_as, admin_acme, acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


def _trigger(org, path="orders"):
    trigger = WebhookTrigger.objects.create(org=org, path=path, provider_type="localhost")
    LocalhostWebhookConfig.objects.create(trigger=trigger, name="local")
    return trigger


def test_binning_and_restoring_re_registers_the_tunnels(
    admin_client, acme, django_capture_on_commit_callbacks
):
    with patch(REGISTER, return_value=True):
        trigger = _trigger(acme)
    with patch(REGISTER, return_value=True) as register:
        with django_capture_on_commit_callbacks(execute=True):
            assert admin_client.delete(f"{TRIGGERS_URL}{trigger.pk}/").status_code == 204
        assert register.called
        assert not LocalhostWebhookConfig.objects.filter(trigger_id=trigger.pk).exists()
        assert trigger.__class__.all_objects.get(pk=trigger.pk).get_active_config() is None

        register.reset_mock()
        with django_capture_on_commit_callbacks(execute=True):
            assert admin_client.post(f"{TRIGGERS_URL}{trigger.pk}/restore/").status_code == 200
        assert register.called
        assert LocalhostWebhookConfig.objects.filter(trigger_id=trigger.pk).exists()


def test_a_path_another_org_took_comes_back_with_a_dash_number(admin_client, acme, beta):
    with patch(REGISTER, return_value=True):
        trigger = _trigger(acme)
        admin_client.delete(f"{TRIGGERS_URL}{trigger.pk}/")
        _trigger(beta, path="orders")

        restored = admin_client.post(f"{TRIGGERS_URL}{trigger.pk}/restore/").json()

    assert restored == {"id": trigger.pk, "name": "orders-2", "renamed_from": "orders"}


def test_a_twilio_channel_keeps_its_trigger_through_bin_and_restore_and_loses_it_on_purge(acme):
    with patch(REGISTER, return_value=True):
        trigger = WebhookTrigger.objects.create(org=acme, path="calls", provider_type="ngrok")
        channel = RealtimeChannel.objects.create(org=acme, name="Line")
        twilio = TwilioChannel.objects.create(
            channel=channel, account_sid="AC1", webhook_trigger=trigger
        )

        trigger.delete()
        twilio.refresh_from_db()
        assert twilio.webhook_trigger_id == trigger.pk
        assert twilio.validate_provider() == "No webhook trigger configured for this channel"

        RestoreService.restore(WebhookTrigger.all_objects.get(pk=trigger.pk))
        twilio.refresh_from_db()
        assert twilio.webhook_trigger_id == trigger.pk

        trigger.delete()
        WebhookTrigger.all_objects.get(pk=trigger.pk).purge()
        twilio.refresh_from_db()
        assert twilio.webhook_trigger_id is None


def test_a_telegram_node_on_a_binned_trigger_isnt_registered(acme):
    with patch(REGISTER, return_value=True):
        trigger = WebhookTrigger.objects.create(org=acme, path="bot", provider_type="ngrok")
        trigger.delete()
    node = SimpleNamespace(
        pk=1,
        telegram_bot_api_key_secret_id=1,
        webhook_trigger=WebhookTrigger.all_objects.get(pk=trigger.pk),
    )
    # The service is a singleton: call the method on a stand-in instead of building one.
    service = SimpleNamespace(webhook_trigger_service=Mock())

    assert TelegramTriggerService.register_telegram_trigger(service, node) is None
    service.webhook_trigger_service.wait_for_tunnel_url_for_trigger.assert_not_called()


def _routed_nodes(path, config_id=None):
    """The flow nodes a call to `path` starts (the query handle_webhook_trigger runs)."""
    # get_trigger_filters doesn't use the (singleton) service's state.
    filters = WebhookTriggerService.get_trigger_filters(None, path, config_id)
    return set(WebhookTriggerNode.objects.filter(**filters).values_list("pk", flat=True))


def _node(org, trigger, name):
    graph = Graph.objects.create(org=org, name=f"Flow {name}")
    return WebhookTriggerNode.objects.create(
        graph=graph,
        node_name=name,
        python_code=PythonCode.objects.create(code="def main(): pass"),
        webhook_trigger=trigger,
    )


@pytest.mark.parametrize("config_id", [None, "localhost:{org}:orders"], ids=["legacy", "tunnel"])
def test_a_binned_trigger_starts_no_flow_once_its_path_is_reused(acme, beta, config_id):
    with patch(REGISTER, return_value=True):
        binned = _trigger(acme)
        binned_node = _node(acme, binned, "old")
        binned.delete()
        reused = _trigger(beta)
        reused_node = _node(beta, reused, "new")

    routed = _routed_nodes("orders", config_id and config_id.format(org=beta.pk))

    assert binned_node.pk not in routed
    assert routed == {reused_node.pk}


def test_a_binned_trigger_starts_no_flow_after_its_org_makes_a_new_one(acme):
    with patch(REGISTER, return_value=True):
        binned = _trigger(acme)
        binned_node = _node(acme, binned, "old")
        binned.delete()
        new_node = _node(acme, _trigger(acme), "new")

    assert _routed_nodes("orders", f"localhost:{acme.pk}:orders") == {new_node.pk}
    assert binned_node.pk not in _routed_nodes("orders")


def test_restoring_a_trigger_registers_its_telegram_bots_again(
    acme, mock_telegram_service, django_capture_on_commit_callbacks
):
    with patch(REGISTER, return_value=True):
        trigger = WebhookTrigger.objects.create(org=acme, path="bot", provider_type="ngrok")
        graph = Graph.objects.create(org=acme, name="Telegram flow")
        node = TelegramTriggerNode.objects.create(graph=graph, node_name="bot", webhook_trigger=trigger)
        trigger.delete()
        mock_telegram_service.reset_mock()

        with django_capture_on_commit_callbacks(execute=True):
            RestoreService.restore(WebhookTrigger.all_objects.get(pk=trigger.pk))

    mock_telegram_service.assert_called_once()
    assert mock_telegram_service.call_args.kwargs["telegram_trigger_instance"].pk == node.pk


def test_binning_restoring_and_purging_a_tunnel_secret_re_pushes_the_registry(
    acme, django_capture_on_commit_callbacks
):
    with patch(REGISTER, return_value=True):
        trigger = _trigger(acme, path="signed")
        secret = secret_service.create(text="x" * 40, org=acme, name="HOOK_KEY")
        WebhookTriggerAuth.objects.create(trigger=trigger, kind="webhook", secret=secret)
        unused = secret_service.create(text="y" * 40, org=acme, name="UNUSED")

    for action in (
        lambda: secret.delete(),
        lambda: RestoreService.restore(Secret.all_objects.get(pk=secret.pk)),
        lambda: (secret.delete(), Secret.all_objects.get(pk=secret.pk).purge()),
    ):
        with patch(REGISTER, return_value=True) as register:
            with django_capture_on_commit_callbacks(execute=True):
                action()
        assert register.called

    with patch(REGISTER, return_value=True) as register:
        with django_capture_on_commit_callbacks(execute=True):
            unused.delete()
    assert not register.called


def _bin_details(admin_client, url):
    entry = admin_client.get(f"{url}recycle-bin/").json()[0]
    return {detail["label"]: detail for detail in entry["details"]}


def test_a_binned_trigger_says_what_still_uses_it(admin_client, acme):
    with patch(REGISTER, return_value=True):
        trigger = _trigger(acme, path="calls")
        _node(acme, trigger, "hook")
        channel = RealtimeChannel.objects.create(org=acme, name="Line")
        TwilioChannel.objects.create(channel=channel, account_sid="AC1", webhook_trigger=trigger)
        unused = _trigger(acme, path="spare")
        admin_client.delete(f"{TRIGGERS_URL}{trigger.pk}/")
        admin_client.delete(f"{TRIGGERS_URL}{unused.pk}/")

        entries = admin_client.get(f"{TRIGGERS_URL}recycle-bin/").json()

    used_by = {entry["name"]: _labels(entry)["Used by"]["value"] for entry in entries}
    assert used_by == {"calls": "1 flow, 1 voice channel", "spare": None}


def test_a_binned_trigger_shows_its_auth_type(admin_client, acme):
    with patch(REGISTER, return_value=True):
        signed = _trigger(acme, path="signed")
        WebhookTriggerAuth.objects.create(trigger=signed, kind="telegram")
        plain = _trigger(acme, path="plain")
        admin_client.delete(f"{TRIGGERS_URL}{signed.pk}/")
        admin_client.delete(f"{TRIGGERS_URL}{plain.pk}/")

        entries = admin_client.get(f"{TRIGGERS_URL}recycle-bin/").json()

    auth = {entry["name"]: _labels(entry)["Auth"]["value"] for entry in entries}
    assert auth == {"signed": "Telegram", "plain": None}


def test_a_binned_channel_warns_when_its_trigger_is_binned_too(admin_client, acme):
    with patch(REGISTER, return_value=True):
        trigger = WebhookTrigger.objects.create(org=acme, path="calls", provider_type="ngrok")
        channel = RealtimeChannel.objects.create(org=acme, name="Line")
        TwilioChannel.objects.create(channel=channel, account_sid="AC1", webhook_trigger=trigger)
        channel.delete()
        trigger.delete()

        warning = _bin_details(admin_client, "/api/realtime-channels/")["Comes back"]

    assert warning["format"] == "notice"
    assert 'until its webhook trigger "calls" is restored' in warning["value"]


def test_a_binned_flow_warns_when_its_trigger_node_points_at_a_binned_trigger(admin_client, acme):
    with patch(REGISTER, return_value=True):
        trigger = _trigger(acme, path="hook")
        node = _node(acme, trigger, "hook")
        node.graph.delete()
        trigger.delete()

        warning = _bin_details(admin_client, "/api/graphs/")["Comes back"]

    assert warning["format"] == "notice"
    assert 'Its webhook trigger "hook" is in the recycle bin' in warning["value"]


def _labels(entry):
    return {detail["label"]: detail for detail in entry["details"]}
