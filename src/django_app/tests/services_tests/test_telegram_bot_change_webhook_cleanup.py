"""A bot a Telegram trigger node stops using must lose the webhook that still posts to the trigger.

Telegram keeps one webhook per bot key. When a node's bot key changes, or the
node is binned or deleted, the old bot's webhook still posts to the same
callback URL with the same `secret_token`, so the incoming request passes the
header check and starts every flow on the path. Only the outbound Telegram HTTP
call is faked here: an in-memory Telegram that keeps one webhook per bot token,
so the tests assert Telegram's resulting state, not which calls were made.
"""

import pytest
import requests
from django.db import transaction
from django.utils import timezone

from tables.models import Secret
from tables.models.graph_models import Graph, TelegramTriggerNode
from tables.models.webhook_models import (
    NgrokWebhookConfig,
    ProviderType,
    WebhookTrigger,
    WebhookTriggerAuthKind,
)
from tables.services import telegram_trigger_service as telegram_trigger_module
from tables.services.recycle_bin.restore_service import RestoreService
from tables.services.secrets import secret_service
from tables.services.soft_delete import DeleteService
from tables.services.webhook_trigger_service import WebhookTriggerService

OLD_BOT_TOKEN = "111111111:AAOldBotTokenForBotChangeTests_xyz"
NEW_BOT_TOKEN = "222222222:AANewBotTokenForBotChangeTests_xyz"
THIRD_BOT_TOKEN = "333333333:AAThirdBotTokenForBotChangeTests_xyz"
SECRET_TOKEN = "TelegramWebhookSecretForBotChangeTests0001"
TUNNEL_URL = "https://tunnel.test"
CALLBACK_URL = f"{TUNNEL_URL}/webhooks/bot-change/"


class _FakeResponse:
    def __init__(self, body: dict, status_code: int = 200):
        self._body = body
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)

    def json(self) -> dict:
        return self._body


class FakeTelegram:
    """Telegram's webhook state: one URL (and secret) per bot token."""

    def __init__(self):
        self.webhooks: dict[str, dict] = {}
        # (bot token, endpoint) pairs Telegram answers with HTTP 500.
        self.failing_calls: set[tuple[str, str]] = set()

    def request(self, method, url, params=None, timeout=None):
        bot_token, endpoint = url.removeprefix("https://api.telegram.org/bot").split("/", 1)
        params = params or {}
        if (bot_token, endpoint) in self.failing_calls:
            return _FakeResponse({"ok": False, "error_code": 500}, status_code=500)
        if endpoint == "setWebhook":
            self.webhooks[bot_token] = {
                "url": params["url"],
                "secret_token": params.get("secret_token"),
            }
            return _FakeResponse({"ok": True, "result": True})
        if endpoint == "deleteWebhook":
            self.webhooks.pop(bot_token, None)
            return _FakeResponse({"ok": True, "result": True})
        if endpoint == "getWebhookInfo":
            webhook = self.webhooks.get(bot_token, {})
            return _FakeResponse(
                {"ok": True, "result": {"url": webhook.get("url", ""), "pending_update_count": 0}}
            )
        raise AssertionError(f"Unexpected Telegram endpoint {endpoint}")


@pytest.fixture
def fake_telegram(monkeypatch) -> FakeTelegram:
    telegram = FakeTelegram()
    monkeypatch.setattr(WebhookTriggerService, "register_webhooks", lambda self: True)
    monkeypatch.setattr(
        WebhookTriggerService,
        "wait_for_tunnel_url_for_trigger",
        lambda self, webhook_trigger: TUNNEL_URL,
    )
    monkeypatch.setattr(
        WebhookTriggerService,
        "get_tunnel_url_for_trigger",
        lambda self, webhook_trigger: TUNNEL_URL,
    )
    monkeypatch.setattr(telegram_trigger_module.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(telegram_trigger_module.requests, "request", telegram.request)
    return telegram


def _create_telegram_trigger(org, path: str) -> WebhookTrigger:
    trigger = WebhookTrigger.objects.create(path=path, provider_type=ProviderType.NGROK, org=org)
    NgrokWebhookConfig.objects.create(
        name=f"cfg-{path}",
        auth_token_secret=secret_service.create(
            text="ngrok-token", org=org, name=f"{path}-ngrok-secret"
        ),
        trigger=trigger,
    )
    WebhookTriggerService().set_trigger_auth_secret(
        trigger,
        secret=secret_service.create(text=SECRET_TOKEN, org=org, name=f"{path}-telegram-secret"),
        kind=WebhookTriggerAuthKind.TELEGRAM,
    )
    return trigger


def _create_node(graph, trigger, bot_secret, name: str) -> TelegramTriggerNode:
    return TelegramTriggerNode.objects.create(
        node_name=name,
        graph=graph,
        webhook_trigger=trigger,
        telegram_bot_api_key_secret=bot_secret,
    )


@pytest.fixture
def switch_bot(django_capture_on_commit_callbacks):
    """Repoint a node at another bot and commit, so the deferred retirement runs."""

    def switch(node: TelegramTriggerNode, bot_secret) -> None:
        with django_capture_on_commit_callbacks(execute=True):
            node.telegram_bot_api_key_secret = bot_secret
            node.save()

    return switch


@pytest.fixture
def bot_change_setup(default_org, fake_telegram):
    """A trigger with one node on the old bot, registered through the real post_save signal."""
    trigger = _create_telegram_trigger(default_org, "bot-change")
    graph = Graph.objects.create(name="g-bot-change", org=default_org)
    secrets = {
        token: secret_service.create(text=token, org=default_org, name=f"bot-{token[:9]}")
        for token in (OLD_BOT_TOKEN, NEW_BOT_TOKEN, THIRD_BOT_TOKEN)
    }
    node = _create_node(graph, trigger, secrets[OLD_BOT_TOKEN], "bot-change-node")
    assert fake_telegram.webhooks[OLD_BOT_TOKEN]["url"] == CALLBACK_URL
    yield trigger, graph, node, secrets


@pytest.mark.django_db
def test_changing_the_bot_key_removes_the_old_bots_webhook(bot_change_setup, fake_telegram, switch_bot):
    _trigger, _graph, node, secrets = bot_change_setup

    switch_bot(node, secrets[NEW_BOT_TOKEN])

    assert fake_telegram.webhooks[NEW_BOT_TOKEN]["url"] == CALLBACK_URL
    assert OLD_BOT_TOKEN not in fake_telegram.webhooks


@pytest.mark.django_db
def test_old_bot_webhook_held_by_another_url_is_kept(bot_change_setup, fake_telegram, switch_bot):
    _trigger, _graph, node, secrets = bot_change_setup
    other_url = "https://elsewhere.test/webhooks/other-trigger/"
    fake_telegram.webhooks[OLD_BOT_TOKEN]["url"] = other_url

    switch_bot(node, secrets[NEW_BOT_TOKEN])

    assert fake_telegram.webhooks[OLD_BOT_TOKEN]["url"] == other_url
    assert fake_telegram.webhooks[NEW_BOT_TOKEN]["url"] == CALLBACK_URL


@pytest.mark.django_db
def test_old_bot_still_used_by_another_node_on_the_trigger_keeps_its_webhook(
    bot_change_setup, fake_telegram, switch_bot
):
    trigger, graph, node, secrets = bot_change_setup
    _create_node(graph, trigger, secrets[OLD_BOT_TOKEN], "same-bot-node")

    switch_bot(node, secrets[NEW_BOT_TOKEN])

    assert fake_telegram.webhooks[OLD_BOT_TOKEN]["url"] == CALLBACK_URL
    assert fake_telegram.webhooks[NEW_BOT_TOKEN]["url"] == CALLBACK_URL


@pytest.mark.django_db
def test_saving_another_node_on_a_different_bot_keeps_the_first_nodes_webhook(
    bot_change_setup, fake_telegram, django_capture_on_commit_callbacks
):
    # The auth records one bot per trigger; a second node registering its own bot
    # must not be read as the first node's bot being replaced.
    trigger, graph, _node, secrets = bot_change_setup
    second_node = _create_node(graph, trigger, secrets[NEW_BOT_TOKEN], "second-bot-node")

    with django_capture_on_commit_callbacks(execute=True):
        second_node.node_name = "second-bot-node-renamed"
        second_node.save()

    assert fake_telegram.webhooks[OLD_BOT_TOKEN]["url"] == CALLBACK_URL
    assert fake_telegram.webhooks[NEW_BOT_TOKEN]["url"] == CALLBACK_URL


@pytest.mark.django_db
def test_changing_the_bot_twice_retires_each_replaced_bot(bot_change_setup, fake_telegram, switch_bot):
    _trigger, _graph, node, secrets = bot_change_setup

    switch_bot(node, secrets[NEW_BOT_TOKEN])
    switch_bot(node, secrets[THIRD_BOT_TOKEN])

    assert set(fake_telegram.webhooks) == {THIRD_BOT_TOKEN}
    assert fake_telegram.webhooks[THIRD_BOT_TOKEN]["url"] == CALLBACK_URL


@pytest.mark.django_db
def test_a_rolled_back_bot_change_keeps_the_old_bots_webhook(
    bot_change_setup, fake_telegram, django_capture_on_commit_callbacks
):
    # The node still uses the old bot after the rollback, so its webhook must survive.
    _trigger, _graph, node, secrets = bot_change_setup

    with django_capture_on_commit_callbacks(execute=True):
        with pytest.raises(RuntimeError), transaction.atomic():
            node.telegram_bot_api_key_secret = secrets[NEW_BOT_TOKEN]
            node.save()
            raise RuntimeError("a later write in the same save fails")

    node.refresh_from_db()
    assert node.telegram_bot_api_key_secret_id == secrets[OLD_BOT_TOKEN].pk
    assert fake_telegram.webhooks[OLD_BOT_TOKEN]["url"] == CALLBACK_URL


@pytest.mark.django_db
def test_switching_away_and_back_in_one_transaction_keeps_the_bots_webhook(
    bot_change_setup, fake_telegram, django_capture_on_commit_callbacks
):
    _trigger, _graph, node, secrets = bot_change_setup

    with django_capture_on_commit_callbacks(execute=True):
        node.telegram_bot_api_key_secret = secrets[NEW_BOT_TOKEN]
        node.save()
        node.telegram_bot_api_key_secret = secrets[OLD_BOT_TOKEN]
        node.save()

    assert fake_telegram.webhooks[OLD_BOT_TOKEN]["url"] == CALLBACK_URL
    assert NEW_BOT_TOKEN not in fake_telegram.webhooks


def _fail_get_webhook_info(fake_telegram, secrets):
    fake_telegram.failing_calls.add((OLD_BOT_TOKEN, "getWebhookInfo"))


def _fail_delete_webhook(fake_telegram, secrets):
    fake_telegram.failing_calls.add((OLD_BOT_TOKEN, "deleteWebhook"))


def _bin_old_bot_secret(fake_telegram, secrets):
    Secret.all_objects.filter(pk=secrets[OLD_BOT_TOKEN].pk).update(
        active=False, soft_deleted_at=timezone.now()
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "break_retirement",
    [_fail_get_webhook_info, _fail_delete_webhook, _bin_old_bot_secret],
    ids=["get-webhook-info-fails", "delete-webhook-fails", "old-bot-secret-binned"],
)
def test_failed_retirement_never_fails_the_save(bot_change_setup, fake_telegram, break_retirement, switch_bot):
    _trigger, _graph, node, secrets = bot_change_setup
    break_retirement(fake_telegram, secrets)

    switch_bot(node, secrets[NEW_BOT_TOKEN])

    node.refresh_from_db()
    assert node.telegram_bot_api_key_secret_id == secrets[NEW_BOT_TOKEN].pk
    assert fake_telegram.webhooks[NEW_BOT_TOKEN]["url"] == CALLBACK_URL
    assert fake_telegram.webhooks[OLD_BOT_TOKEN]["url"] == CALLBACK_URL


@pytest.mark.django_db
def test_moving_the_node_to_another_trigger_with_a_new_bot_retires_the_old_bot(
    default_org, bot_change_setup, fake_telegram, django_capture_on_commit_callbacks
):
    _trigger, _graph, node, secrets = bot_change_setup
    other_trigger = _create_telegram_trigger(default_org, "bot-change-other")

    with django_capture_on_commit_callbacks(execute=True):
        node.webhook_trigger = other_trigger
        node.telegram_bot_api_key_secret = secrets[NEW_BOT_TOKEN]
        node.save()

    assert OLD_BOT_TOKEN not in fake_telegram.webhooks
    assert (
        fake_telegram.webhooks[NEW_BOT_TOKEN]["url"] == f"{TUNNEL_URL}/webhooks/bot-change-other/"
    )


@pytest.mark.django_db
def test_binning_the_node_removes_its_bot_webhook(
    bot_change_setup, fake_telegram, django_capture_on_commit_callbacks
):
    _trigger, _graph, node, _secrets = bot_change_setup

    with django_capture_on_commit_callbacks(execute=True):
        DeleteService.delete(node)

    assert OLD_BOT_TOKEN not in fake_telegram.webhooks


@pytest.mark.django_db
def test_binning_the_node_keeps_a_webhook_another_node_on_the_trigger_uses(
    bot_change_setup, fake_telegram, django_capture_on_commit_callbacks
):
    trigger, graph, node, secrets = bot_change_setup
    _create_node(graph, trigger, secrets[OLD_BOT_TOKEN], "same-bot-node")

    with django_capture_on_commit_callbacks(execute=True):
        DeleteService.delete(node)

    assert fake_telegram.webhooks[OLD_BOT_TOKEN]["url"] == CALLBACK_URL


@pytest.mark.django_db
def test_binning_the_node_keeps_the_webhook_until_the_delete_commits(
    bot_change_setup, fake_telegram, django_capture_on_commit_callbacks
):
    _trigger, _graph, node, _secrets = bot_change_setup

    with django_capture_on_commit_callbacks(execute=False):
        DeleteService.delete(node)

    assert fake_telegram.webhooks[OLD_BOT_TOKEN]["url"] == CALLBACK_URL


@pytest.mark.django_db
def test_deleting_a_live_node_for_good_removes_its_bot_webhook(
    bot_change_setup, fake_telegram, django_capture_on_commit_callbacks
):
    _trigger, _graph, node, _secrets = bot_change_setup

    with django_capture_on_commit_callbacks(execute=True):
        node.delete()

    assert OLD_BOT_TOKEN not in fake_telegram.webhooks


@pytest.mark.django_db
def test_restoring_a_binned_flow_registers_its_bot_again(
    bot_change_setup, fake_telegram, django_capture_on_commit_callbacks
):
    _trigger, graph, _node, _secrets = bot_change_setup
    with django_capture_on_commit_callbacks(execute=True):
        graph.delete()
    assert OLD_BOT_TOKEN not in fake_telegram.webhooks

    with django_capture_on_commit_callbacks(execute=True):
        RestoreService.restore(Graph.all_objects.get(pk=graph.pk))

    assert fake_telegram.webhooks[OLD_BOT_TOKEN]["url"] == CALLBACK_URL
