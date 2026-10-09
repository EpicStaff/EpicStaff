import json
from unittest.mock import patch

import pytest
import requests
from django.urls import reverse
from loguru import logger as loguru_logger
from rbac.models import OrganizationUser, Role, RolePermission
from rbac.models.enums import Permission, ResourceType
from tables.services.telegram_trigger_service import TelegramTriggerService
from tables.models import Secret
from tables.models.graph_models import Graph, TelegramTriggerNode
from tables.models.webhook_models import (
    NgrokWebhookConfig,
    ProviderType,
    WebhookTrigger,
    WebhookTriggerAuth,
    WebhookTriggerAuthKind,
)
from tables.services.secrets import secret_encryption, secret_service
from tables.services.webhook_trigger_service import WebhookTriggerService
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


@pytest.mark.django_db
class TestTelegramTriggerViewSet:
    def test_create_telegram_trigger_node(
        self, auth_client, graph, mock_telegram_service
    ):
        secret = secret_service.create(
            text="123456:ABC-DEF", org=graph.org, name="tg-create-key"
        )
        url = reverse("telegramtriggernode-list")
        data = {
            "node_name": "StartNode",
            "telegram_bot_api_key_secret_id": secret.id,
            "graph": graph.id,
            "fields": [
                {
                    "parent": "message",
                    "field_name": "user_id",
                    "variable_path": "from.id",
                }
            ],
        }

        response = auth_client.post(url, data, format="json")

        assert response.status_code == 201
        assert TelegramTriggerNode.objects.count() == 1
        assert TelegramTriggerNode.objects.first().fields.count() == 1
        # Verify signal triggered the service at least once
        assert mock_telegram_service.call_count >= 1

    def test_update_telegram_trigger_node(self, auth_client, graph, mocker):
        # 1. Mock the specific method on the Singleton class
        # This prevents the real network call during .create() and .put()
        mock_register = mocker.patch.object(
            TelegramTriggerService,
            "register_telegram_trigger",
            return_value={"ok": True},
        )

        # 2. Create the initial node (triggers signal -> uses mock)
        secret = Secret(org=graph.org, name="telegram-trigger-node-test-key")
        secret_encryption.encrypt(text="12345:fake_key").write_to(secret)
        secret.save()
        node = TelegramTriggerNode.objects.create(
            node_name="OldName",
            telegram_bot_api_key_secret=secret,
            graph=graph,
        )

        # 3. Update via API — swap to a different secret
        new_secret = secret_service.create(
            text="54321:new_fake_key", org=graph.org, name="tg-update-key"
        )
        url = reverse("telegramtriggernode-detail", args=[node.id])
        data = {
            "node_name": "NewName",
            "telegram_bot_api_key_secret_id": new_secret.id,
            "graph": graph.id,
            "fields": [
                {
                    "parent": "message",
                    "field_name": "text",
                    "variable_path": "message.text",
                }
            ],
        }

        response = auth_client.put(url, data, format="json")

        # Assertions
        assert response.status_code == 200
        node.refresh_from_db()
        assert node.node_name == "NewName"
        assert node.telegram_bot_api_key_secret_id == new_secret.id
        # The secret previously attached is untouched — swapping does not rotate.
        secret.refresh_from_db()
        assert secret_encryption.decrypt(encryptedtext=secret.value) == "12345:fake_key"

        # Verify the mock was called (once for create, once for update)
        assert mock_register.call_count == 2

    def test_create_telegram_trigger_node_with_webhook_trigger(
        self, auth_client, graph, mock_telegram_service, default_org
    ):
        """
        Inline trigger creation was removed — the
        telegram-trigger-nodes endpoint only accepts an *existing*
        WebhookTrigger id and links the node to it.
        """
        trigger = WebhookTrigger.objects.create(
            path="tgWebhook123", provider_type=None, org=default_org
        )
        secret = secret_service.create(
            text="123456:ABC-DEF", org=graph.org, name="tg-webhook-key"
        )

        url = reverse("telegramtriggernode-list")
        data = {
            "node_name": "TelegramWithWebhook",
            "telegram_bot_api_key_secret_id": secret.id,
            "graph": graph.id,
            "webhook_trigger": trigger.id,
            "fields": [
                {
                    "parent": "message",
                    "field_name": "text",
                    "variable_path": "variables.telegram_data.user_input",
                }
            ],
        }

        response = auth_client.post(url, data, format="json")

        assert response.status_code == 201, response.json()
        node = TelegramTriggerNode.objects.get(node_name="TelegramWithWebhook")
        assert node.webhook_trigger == trigger
        # Write side (POST response) still returns the plain id, unchanged.
        assert response.json()["webhook_trigger"] == trigger.id
        # service should still be called (signal)
        mock_telegram_service.assert_called()

    def test_create_telegram_trigger_node_rejects_localhost_provider(
        self, auth_client, graph, default_org
    ):
        """
        POST must 400 when the linked webhook_trigger uses the
        localhost provider — Telegram's setWebhook API requires a public
        HTTPS URL and can never reach a localhost tunnel. Mirrors
        TwilioChannelSerializer.validate() rejecting localhost for Twilio.
        """
        from tables.models.webhook_models import LocalhostWebhookConfig, ProviderType

        trigger = WebhookTrigger.objects.create(
            path="tg-create-localhost",
            provider_type=ProviderType.LOCALHOST,
            org=default_org,
        )
        LocalhostWebhookConfig.objects.create(
            trigger=trigger, name="tg-localhost", domain="localhost:8009"
        )

        url = reverse("telegramtriggernode-list")
        data = {
            "node_name": "TelegramLocalhostRejected",
            "telegram_bot_api_key": "123456:ABC-DEF",
            "graph": graph.id,
            "webhook_trigger": trigger.id,
            "fields": [],
        }

        response = auth_client.post(url, data, format="json")

        assert response.status_code == 400, response.json()
        assert "localhost" in str(response.json()).lower()
        assert not TelegramTriggerNode.objects.filter(
            node_name="TelegramLocalhostRejected"
        ).exists()

    def test_get_telegram_trigger_node_expands_nested_trigger_info(
        self, auth_client, graph, mock_telegram_service, default_org
    ):
        """
        GET on /api/telegram-trigger-nodes/{id}/ (and the list endpoint) must
        expand `webhook_trigger` to its full nested representation, not just
        the bare id — write side (POST/PATCH) is unaffected.

        Uses an ngrok-backed trigger (not localhost) — this rejects
        localhost trigger config on TelegramTriggerNode create/update, so a
        localhost trigger can no longer be used here; ngrok is a publicly
        reachable equivalent for exercising the nested-expansion behavior.
        """
        from tables.models.webhook_models import NgrokWebhookConfig, ProviderType

        trigger = WebhookTrigger.objects.create(
            path="tgWebhookForGet",
            provider_type=ProviderType.NGROK,
            org=default_org,
        )
        NgrokWebhookConfig.objects.create(
            trigger=trigger,
            name="tg-ngrok",
            auth_token_secret=secret_service.create(
                text="tok", org=default_org, name="tg-ngrok-secret"
            ),
        )

        url = reverse("telegramtriggernode-list")
        data = {
            "node_name": "TelegramGetNested",
            "telegram_bot_api_key": "123456:ABC-DEF",
            "graph": graph.id,
            "webhook_trigger": trigger.id,
            "fields": [],
        }
        create_response = auth_client.post(url, data, format="json")
        assert create_response.status_code == 201, create_response.json()
        assert create_response.json()["webhook_trigger"] == trigger.id
        node_id = create_response.json()["id"]

        detail = auth_client.get(
            reverse("telegramtriggernode-detail", args=[node_id])
        )
        assert detail.status_code == 200, detail.json()
        wt = detail.json()["webhook_trigger"]
        assert wt is not None
        assert wt["id"] == trigger.id
        assert wt["path"] == "tgWebhookForGet"
        assert wt["provider_type"] == "ngrok"
        assert wt["ngrok_config"]["name"] == "tg-ngrok"

        listing = auth_client.get(reverse("telegramtriggernode-list"))
        assert listing.status_code == 200
        listed = next(
            row for row in listing.json()["results"] if row["id"] == node_id
        )
        assert listed["webhook_trigger"]["path"] == "tgWebhookForGet"


@pytest.mark.django_db
class TestTelegramTriggerServiceLocalhostGuard:
    """TelegramTriggerService.register_telegram_trigger() must reject
    localhost-provider webhook triggers before ever calling Telegram's
    setWebhook API, mirroring TwilioChannel.validate_provider()."""

    def test_register_telegram_trigger_rejects_localhost_provider(self, default_org):
        from tables.exceptions import RegisterTelegramTriggerError
        from tables.models.webhook_models import LocalhostWebhookConfig, ProviderType

        trigger = WebhookTrigger.objects.create(
            path="tg-localhost-reject",
            provider_type=ProviderType.LOCALHOST,
            org=default_org,
        )
        LocalhostWebhookConfig.objects.create(
            trigger=trigger, name="tg-localhost", domain="localhost:8009"
        )
        secret = secret_service.create(
            text="123456:fake", org=default_org, name="tg-localhost-reject-key"
        )
        node = TelegramTriggerNode(
            node_name="LocalhostNode",
            telegram_bot_api_key_secret=secret,
            webhook_trigger=trigger,
        )

        with pytest.raises(RegisterTelegramTriggerError) as exc_info:
            TelegramTriggerService().register_telegram_trigger(node)

        assert "localhost" in str(exc_info.value).lower()

    def test_register_telegram_trigger_succeeds_with_ngrok_provider(
        self, default_org, mocker
    ):
        """Regression: an ngrok-backed trigger must still register normally
        after the localhost guard was added."""
        from tables.models.webhook_models import (
            NgrokWebhookConfig,
            ProviderType,
            WebhookTriggerAuthKind,
        )

        trigger = WebhookTrigger.objects.create(
            path="tg-ngrok-ok", provider_type=ProviderType.NGROK, org=default_org
        )
        NgrokWebhookConfig.objects.create(
            trigger=trigger,
            name="tg-ngrok",
            auth_token_secret=secret_service.create(
                text="tok", org=default_org, name="tg-ngrok-secret"
            ),
        )
        secret = secret_service.create(
            text="123456:fake", org=default_org, name="tg-ngrok-ok-key"
        )
        # The Telegram `secret_token` is now user-settable via
        # `WebhookTriggerAuth(kind=telegram)` -- registration fails loudly
        # without one, so it must be set here before the node is created.
        WebhookTriggerService().set_trigger_auth_secret(
            trigger,
            secret_service.create(
                text="tg-ngrok-ok-secret-token",
                org=default_org,
                name="tg-ngrok-ok-auth-secret",
            ),
            kind=WebhookTriggerAuthKind.TELEGRAM,
        )

        mocker.patch(
            "tables.services.webhook_trigger_service.WebhookTriggerService"
            ".get_tunnel_url_for_trigger",
            return_value="https://abcd1234.ngrok-free.app",
        )
        mock_call = mocker.patch.object(
            TelegramTriggerService, "_call_telegram_api", return_value={"ok": True}
        )
        # A real Redis publish in a unit test has 0 subscribers, so the
        # signal's own tunnel resync must be stubbed to report delivery.
        mocker.patch.object(WebhookTriggerService, "register_webhooks", return_value=True)

        # .objects.create() fires the real post_save registration, which is
        # the ONE real registration exercised by this test.
        node = TelegramTriggerNode.objects.create(
            node_name="NgrokNode",
            graph=Graph.objects.create(name="tg-ngrok-ok-graph", org=default_org),
            telegram_bot_api_key_secret=secret,
            webhook_trigger=trigger,
        )

        mock_call.assert_called_once()
        _, kwargs = mock_call.call_args
        assert kwargs["params"]["url"] == (
            "https://abcd1234.ngrok-free.app/webhooks/tg-ngrok-ok/"
        )

        # C4: a resync of the SAME node/trigger (e.g. another
        # unrelated resave) must not rotate the secret or re-hit Telegram's
        # setWebhook endpoint once Telegram confirms it still holds the URL.
        webhook_info_request = mocker.patch(
            "tables.services.telegram_trigger_service.requests.request",
            return_value=_telegram_response(
                "https://api.telegram.org",
                body=_webhook_info_body("https://abcd1234.ngrok-free.app/webhooks/tg-ngrok-ok/"),
            ),
        )
        mock_call.reset_mock()
        result = TelegramTriggerService().register_telegram_trigger(node)
        assert result is None
        mock_call.assert_not_called()
        assert webhook_info_request.call_args.args[1].endswith("/getWebhookInfo")

        # The explicit "(re)register" action (force=True) still works.
        result = TelegramTriggerService().register_telegram_trigger(node, force=True)
        assert result == {"ok": True}
        mock_call.assert_called_once()


BOT_TOKEN = "987654321:AAH-webhook-info-SECRET-bot-token"
TUNNEL_URL = "https://abcd1234.ngrok-free.app"
TELEGRAM_SECRET_TOKEN = "WebhookInfoSecret123-xxxxxxxxxxx"
BOT_KEY_REJECTED_BODY = {
    "status_code": 422,
    "code": "telegram_bot_key_rejected",
    "message": "Telegram rejected this bot key. Check the secret selected as the bot key on this node.",
}


def _telegram_response(url, *, status_code=200, body=None):
    """A real `requests.Response`, so `raise_for_status()` and `.json()` behave as in production."""
    response = requests.models.Response()
    response.status_code = status_code
    response.url = url
    response._content = json.dumps(body if body is not None else {}).encode()
    return response


def _webhook_info_body(url, **extra):
    return {"ok": True, "result": {"url": url, "pending_update_count": 0, **extra}}


def _webhook_info_url(node_id):
    return reverse("telegramtriggernode-webhook-info", args=[node_id])


@pytest.fixture
def tunnel_url(mocker):
    return mocker.patch.object(
        WebhookTriggerService, "get_tunnel_url_for_trigger", return_value=TUNNEL_URL
    )


@pytest.fixture
def telegram_api(mocker):
    """Patch only the outbound HTTP call; each test sets its return value or side effect."""
    return mocker.patch("tables.services.telegram_trigger_service.requests.request")


@pytest.fixture
def captured_logs():
    messages = []
    sink_id = loguru_logger.add(lambda message: messages.append(str(message)), level="DEBUG")
    yield messages
    loguru_logger.remove(sink_id)


def _make_node(
    org,
    *,
    path="tg-info-path",
    with_bot_key=True,
    provider_type=ProviderType.NGROK,
    with_webhook_trigger=True,
    telegram_secret_token=TELEGRAM_SECRET_TOKEN,
):
    trigger = None
    if with_webhook_trigger:
        trigger = WebhookTrigger.objects.create(
            path=path, provider_type=provider_type, org=org
        )
        if provider_type == ProviderType.NGROK:
            NgrokWebhookConfig.objects.create(
                trigger=trigger,
                name=f"cfg-{path}",
                auth_token_secret=secret_service.create(
                    text="ngrok-token", org=org, name=f"{path}-ngrok-secret"
                ),
            )
        if telegram_secret_token is not None:
            WebhookTriggerService().set_trigger_auth_secret(
                trigger,
                secret_service.create(
                    text=telegram_secret_token, org=org, name=f"{path}-tg-secret"
                ),
                kind=WebhookTriggerAuthKind.TELEGRAM,
            )
    return TelegramTriggerNode.objects.create(
        node_name=f"node-{path}",
        graph=Graph.objects.create(name=f"graph-{path}", org=org),
        webhook_trigger=trigger,
        telegram_bot_api_key_secret=(
            secret_service.create(text=BOT_TOKEN, org=org, name=f"{path}-bot-key")
            if with_bot_key
            else None
        ),
    )


@pytest.mark.django_db
class TestTelegramTriggerNodeWebhookInfo:
    @pytest.fixture(autouse=True)
    def _stub_signal_side_effects(self, mocker, mock_telegram_service):
        # Node saves resync tunnels over Redis and call setWebhook; neither is under test here.
        mocker.patch.object(WebhookTriggerService, "register_webhooks", return_value=True)

    @pytest.mark.parametrize(
        "registered_url",
        [f"{TUNNEL_URL}/webhooks/tg-info-path/", f"{TUNNEL_URL}/webhooks/tg-info-path"],
    )
    def test_registered_url_equal_to_own_callback_is_a_match(
        self, auth_client, default_org, tunnel_url, telegram_api, registered_url
    ):
        node = _make_node(default_org)
        telegram_api.return_value = _telegram_response(
            "https://api.telegram.org", body=_webhook_info_body(registered_url)
        )

        response = auth_client.get(_webhook_info_url(node.id))

        assert response.status_code == 200, response.content
        assert response.json() == {
            "registered_url": registered_url,
            "expected_url": f"{TUNNEL_URL}/webhooks/tg-info-path/",
            "is_match": True,
            "pending_update_count": 0,
            "last_error_message": None,
            "last_error_date": None,
            "registration_blocker": None,
        }
        method, url = telegram_api.call_args.args
        assert method == "GET"
        assert url == f"https://api.telegram.org/bot{BOT_TOKEN}/getWebhookInfo"
        assert BOT_TOKEN not in response.content.decode()

    def test_url_registered_by_another_node_sharing_the_key_is_a_mismatch(
        self, auth_client, default_org, tunnel_url, telegram_api
    ):
        node = _make_node(default_org)
        other_url = f"{TUNNEL_URL}/webhooks/other-node-path/"
        telegram_api.return_value = _telegram_response(
            "https://api.telegram.org",
            body=_webhook_info_body(
                other_url,
                pending_update_count=3,
                last_error_date=1700000000,
                last_error_message="Wrong response from the webhook: 404 Not Found",
            ),
        )

        response = auth_client.get(_webhook_info_url(node.id))

        assert response.status_code == 200, response.content
        body = response.json()
        assert body["registered_url"] == other_url
        assert body["expected_url"] == f"{TUNNEL_URL}/webhooks/tg-info-path/"
        assert body["is_match"] is False
        assert body["pending_update_count"] == 3
        assert body["last_error_message"] == "Wrong response from the webhook: 404 Not Found"
        assert body["last_error_date"] == "2023-11-14T22:13:20Z"

    def test_no_webhook_registered_returns_null_url_and_no_match(
        self, auth_client, default_org, tunnel_url, telegram_api
    ):
        node = _make_node(default_org)
        telegram_api.return_value = _telegram_response(
            "https://api.telegram.org", body=_webhook_info_body("")
        )

        response = auth_client.get(_webhook_info_url(node.id))

        assert response.status_code == 200, response.content
        assert response.json()["registered_url"] is None
        assert response.json()["expected_url"] == f"{TUNNEL_URL}/webhooks/tg-info-path/"
        assert response.json()["is_match"] is False

    def test_unavailable_tunnel_returns_null_expected_url_but_still_the_registered_url(
        self, auth_client, default_org, telegram_api, mocker
    ):
        mocker.patch.object(WebhookTriggerService, "get_tunnel_url_for_trigger", return_value=None)
        node = _make_node(default_org)
        registered_url = f"{TUNNEL_URL}/webhooks/tg-info-path/"
        telegram_api.return_value = _telegram_response(
            "https://api.telegram.org", body=_webhook_info_body(registered_url)
        )

        response = auth_client.get(_webhook_info_url(node.id))

        assert response.status_code == 200, response.content
        assert response.json()["registered_url"] == registered_url
        assert response.json()["expected_url"] is None
        assert response.json()["is_match"] is None

    def test_trigger_without_tunnel_provider_has_no_expected_url(
        self, auth_client, default_org, telegram_api
    ):
        # The real tunnel lookup runs: with no provider it resolves no config before touching Redis.
        node = _make_node(default_org, provider_type=None)
        telegram_api.return_value = _telegram_response(
            "https://api.telegram.org", body=_webhook_info_body("")
        )

        response = auth_client.get(_webhook_info_url(node.id))

        assert response.status_code == 200, response.content
        assert response.json()["expected_url"] is None
        # Neither URL is known: whether this node would match cannot be determined.
        assert response.json()["registered_url"] is None
        assert response.json()["is_match"] is None

    def test_localhost_trigger_has_no_expected_url_even_with_a_tunnel(
        self, auth_client, default_org, tunnel_url, telegram_api
    ):
        node = _make_node(
            default_org, provider_type=ProviderType.LOCALHOST, telegram_secret_token=None
        )
        registered_url = f"{TUNNEL_URL}/webhooks/tg-info-path/"
        telegram_api.return_value = _telegram_response(
            "https://api.telegram.org", body=_webhook_info_body(registered_url)
        )

        response = auth_client.get(_webhook_info_url(node.id))

        assert response.status_code == 200, response.content
        assert response.json()["expected_url"] is None
        assert response.json()["is_match"] is None
        tunnel_url.assert_not_called()

    def test_trigger_without_telegram_secret_reports_the_blocker_next_to_live_info(
        self, auth_client, default_org, tunnel_url, telegram_api
    ):
        # The developer's case: the last node on a trigger was deleted, which removed
        # the trigger's Telegram auth, so a new node on it can never register.
        node = _make_node(default_org, telegram_secret_token=None)
        registered_url = f"{TUNNEL_URL}/webhooks/other-node-path/"
        telegram_api.return_value = _telegram_response(
            "https://api.telegram.org", body=_webhook_info_body(registered_url)
        )

        response = auth_client.get(_webhook_info_url(node.id))

        assert response.status_code == 200, response.content
        body = response.json()
        assert body["registration_blocker"] == {
            "code": "no_telegram_secret",
            "message": (
                "No Telegram secret configured for this webhook trigger. Set one via the "
                "trigger's `auth_secret_id` before registering."
            ),
        }
        # The bot key is fine, so Telegram's live state is still reported.
        assert body["registered_url"] == registered_url
        assert body["expected_url"] == f"{TUNNEL_URL}/webhooks/tg-info-path/"
        assert body["is_match"] is False
        # The blocker itself costs no Telegram call: only the one getWebhookInfo.
        assert telegram_api.call_count == 1
        assert telegram_api.call_args.args[1].endswith("/getWebhookInfo")

    @pytest.mark.parametrize(
        ("blocker_code", "node_options"),
        [
            ("no_webhook_trigger", {"with_webhook_trigger": False}),
            ("no_tunnel_provider", {"provider_type": None}),
            # Telegram auth cannot be set on a localhost trigger at all.
            (
                "localhost_provider",
                {"provider_type": ProviderType.LOCALHOST, "telegram_secret_token": None},
            ),
        ],
    )
    def test_trigger_configuration_blocker_is_reported(
        self, auth_client, default_org, tunnel_url, telegram_api, blocker_code, node_options
    ):
        node = _make_node(default_org, **node_options)
        telegram_api.return_value = _telegram_response(
            "https://api.telegram.org", body=_webhook_info_body("")
        )

        response = auth_client.get(_webhook_info_url(node.id))

        assert response.status_code == 200, response.content
        assert response.json()["registration_blocker"]["code"] == blocker_code
        assert response.json()["registration_blocker"]["message"]
        assert telegram_api.call_count == 1

    def test_trigger_auth_of_another_kind_is_reported_as_a_conflict(
        self, auth_client, default_org, tunnel_url, telegram_api
    ):
        node = _make_node(default_org, telegram_secret_token=None)
        WebhookTriggerAuth.objects.create(
            trigger=node.webhook_trigger,
            kind=WebhookTriggerAuthKind.WEBHOOK,
            secret=secret_service.create(
                text="webhook-trigger-key-xxxxxxxxxxxxxxxx", org=default_org, name="wh-key"
            ),
        )
        telegram_api.return_value = _telegram_response(
            "https://api.telegram.org", body=_webhook_info_body("")
        )

        response = auth_client.get(_webhook_info_url(node.id))

        assert response.status_code == 200, response.content
        assert response.json()["registration_blocker"]["code"] == "auth_kind_conflict"

    def test_invalid_telegram_secret_is_reported_without_leaking_it(
        self, auth_client, default_org, tunnel_url, telegram_api
    ):
        node = _make_node(default_org)
        invalid_secret = "has spaces SECRET-value!"
        secret = Secret.objects.get(pk=node.webhook_trigger.auth.secret_id)
        secret_encryption.encrypt(text=invalid_secret).write_to(secret)
        secret.save()
        telegram_api.return_value = _telegram_response(
            "https://api.telegram.org", body=_webhook_info_body("")
        )

        response = auth_client.get(_webhook_info_url(node.id))

        assert response.status_code == 200, response.content
        assert response.json()["registration_blocker"]["code"] == "invalid_telegram_secret"
        assert invalid_secret not in response.content.decode()

    def test_unreadable_telegram_secret_is_reported_instead_of_a_500(
        self, auth_client, default_org, tunnel_url, telegram_api
    ):
        node = _make_node(default_org)
        Secret.objects.filter(pk=node.webhook_trigger.auth.secret_id).update(
            value="not-a-fernet-token"
        )
        telegram_api.return_value = _telegram_response(
            "https://api.telegram.org", body=_webhook_info_body("")
        )

        response = auth_client.get(_webhook_info_url(node.id))

        assert response.status_code == 200, response.content
        assert (
            response.json()["registration_blocker"]["code"] == "unresolvable_telegram_secret"
        )

    def test_blocker_is_not_reported_when_telegram_is_unavailable(
        self, auth_client, default_org, tunnel_url, telegram_api
    ):
        node = _make_node(default_org, telegram_secret_token=None)
        telegram_api.side_effect = requests.exceptions.ConnectionError("unreachable")

        response = auth_client.get(_webhook_info_url(node.id))

        # The 502 contract is unchanged; the blocker rides only on the 200 body.
        assert response.status_code == 502, response.content
        assert response.json()["code"] == "telegram_webhook_info_unavailable"

    def test_node_without_bot_key_returns_400_without_calling_telegram(
        self, auth_client, default_org, tunnel_url, telegram_api
    ):
        node = _make_node(default_org, with_bot_key=False)

        response = auth_client.get(_webhook_info_url(node.id))

        assert response.status_code == 400, response.content
        assert response.json()["message"] == "This Telegram trigger node has no bot key configured."
        telegram_api.assert_not_called()

    def test_undecryptable_bot_key_returns_500_without_calling_telegram(
        self, auth_client, default_org, tunnel_url, telegram_api
    ):
        node = _make_node(default_org)
        Secret.objects.filter(pk=node.telegram_bot_api_key_secret_id).update(
            value="not-a-fernet-token"
        )

        response = auth_client.get(_webhook_info_url(node.id))

        assert response.status_code == 500, response.content
        assert response.json()["code"] == "secret_resolution_error"
        assert BOT_TOKEN not in response.content.decode()
        telegram_api.assert_not_called()

    @pytest.mark.parametrize("failure", ["connection_error", "timeout", "http_500", "ok_false"])
    def test_telegram_failure_returns_502_after_one_attempt_without_leaking_the_token(
        self, auth_client, default_org, tunnel_url, telegram_api, captured_logs, failure
    ):
        node = _make_node(default_org)

        def _fail(method, url, **kwargs):
            if failure == "connection_error":
                raise requests.exceptions.ConnectionError(f"Max retries exceeded with url: {url}")
            if failure == "timeout":
                raise requests.exceptions.Timeout(f"Read timed out: {url}")
            if failure == "http_500":
                return _telegram_response(
                    url, status_code=500, body={"ok": False, "description": "Internal"}
                )
            return _telegram_response(url, body={"ok": False, "description": f"bad {url}"})

        telegram_api.side_effect = _fail

        response = auth_client.get(_webhook_info_url(node.id))

        assert response.status_code == 502, response.content
        assert response.json()["message"] == "Could not fetch webhook info from Telegram."
        assert BOT_TOKEN not in response.content.decode()
        assert telegram_api.call_count == 1
        assert telegram_api.call_args.kwargs["timeout"] == (3, 5)
        assert any("getWebhookInfo failed" in message for message in captured_logs)
        assert not any(BOT_TOKEN in message for message in captured_logs)

    @pytest.mark.parametrize("telegram_status", [401, 404])
    def test_bot_key_rejected_by_telegram_returns_422_without_leaking_the_token(
        self, auth_client, default_org, tunnel_url, telegram_api, captured_logs, telegram_status
    ):
        node = _make_node(default_org)
        telegram_api.side_effect = lambda method, url, **kwargs: _telegram_response(
            url,
            status_code=telegram_status,
            body={"ok": False, "error_code": telegram_status, "description": "Not Found"},
        )

        response = auth_client.get(_webhook_info_url(node.id))

        assert response.status_code == 422, response.content
        assert response.json() == BOT_KEY_REJECTED_BODY
        assert telegram_api.call_count == 1
        body = response.content.decode()
        assert BOT_TOKEN not in body
        assert TELEGRAM_SECRET_TOKEN not in body
        assert any(
            "getWebhookInfo failed" in message and str(telegram_status) in message
            for message in captured_logs
        )
        assert not any(BOT_TOKEN in message for message in captured_logs)
        assert not any(TELEGRAM_SECRET_TOKEN in message for message in captured_logs)

    def test_node_in_another_org_returns_404(
        self, client_as, admin_acme, acme, beta, tunnel_url, telegram_api
    ):
        own_node = _make_node(acme, path="acme-tg-path")
        foreign_node = _make_node(beta, path="beta-tg-path")
        telegram_api.return_value = _telegram_response(
            "https://api.telegram.org", body=_webhook_info_body("")
        )
        acme_client = client_as(admin_acme)
        acme_client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

        own_response = acme_client.get(_webhook_info_url(own_node.id))
        foreign_response = acme_client.get(_webhook_info_url(foreign_node.id))

        # Positive control: the same caller reads its own org's node, so the 404 is the org filter.
        assert own_response.status_code == 200, own_response.content
        assert foreign_response.status_code == 404, foreign_response.content
        assert "registered_url" not in foreign_response.json()
        assert telegram_api.call_count == 1

    def test_role_without_flows_read_gets_403(
        self, django_user_model, client_as, acme, tunnel_url, telegram_api
    ):
        node = _make_node(acme)
        role = Role.objects.create(name="role-no-flows-tg", org=acme, is_built_in=False)
        RolePermission.objects.create(
            role=role, resource_type=ResourceType.SECRETS.value, permissions=int(Permission.READ)
        )
        user = django_user_model.objects.create_user(
            email="no-flows-tg@example.com", password="StrongPass123!"
        )
        OrganizationUser.objects.create(user=user, org=acme, role=role)
        client = client_as(user)
        client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

        response = client.get(_webhook_info_url(node.id))

        assert response.status_code == 403, response.content
        telegram_api.assert_not_called()

    def test_viewer_with_flows_read_gets_200(
        self, django_user_model, client_as, acme, role_viewer, tunnel_url, telegram_api
    ):
        node = _make_node(acme)
        user = django_user_model.objects.create_user(
            email="viewer-tg@example.com", password="StrongPass123!"
        )
        OrganizationUser.objects.create(user=user, org=acme, role=role_viewer)
        client = client_as(user)
        client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
        telegram_api.return_value = _telegram_response(
            "https://api.telegram.org", body=_webhook_info_body("")
        )

        response = client.get(_webhook_info_url(node.id))

        assert response.status_code == 200, response.content


def _register_webhook_url(node_id):
    return reverse("telegramtriggernode-register-webhook", args=[node_id])


class _StatefulTelegramApi:
    """Fake Telegram HTTP API that remembers the webhook `setWebhook` last set.

    `set_webhook_failure(url)` may raise or return an error response, to
    simulate a failed registration; the request URL embeds the bot token, as
    in production.
    """

    def __init__(self, registered_url=""):
        self.registered_url = registered_url
        self.endpoints = []
        self.set_webhook_failure = None

    def __call__(self, method, url, params=None, **kwargs):
        endpoint = url.rsplit("/", 1)[-1]
        self.endpoints.append(endpoint)
        if endpoint == "setWebhook":
            if self.set_webhook_failure is not None:
                return self.set_webhook_failure(url)
            self.registered_url = params["url"]
            return _telegram_response(url, body={"ok": True, "result": True})
        return _telegram_response(url, body=_webhook_info_body(self.registered_url))


@pytest.mark.django_db
class TestTelegramTriggerNodeRegisterWebhook:
    EXPECTED_URL = f"{TUNNEL_URL}/webhooks/tg-info-path/"

    @pytest.fixture(autouse=True)
    def _stub_tunnel_resync(self, mocker):
        mocker.patch.object(WebhookTriggerService, "register_webhooks", return_value=True)
        mocker.patch("tables.services.telegram_trigger_service.time.sleep")

    @pytest.fixture
    def telegram(self, mocker):
        fake_api = _StatefulTelegramApi()
        mocker.patch("tables.services.telegram_trigger_service.requests.request", fake_api)
        return fake_api

    def _create_node(self, org, **options):
        # Only creation skips the save signal's registration; the endpoint's registration is real.
        with patch.object(
            TelegramTriggerService,
            "register_telegram_trigger",
            lambda self, telegram_trigger_instance=None, **kwargs: None,
        ):
            return _make_node(org, **options)

    def test_registers_with_one_setwebhook_and_returns_fresh_webhook_info(
        self, auth_client, default_org, tunnel_url, telegram
    ):
        node = self._create_node(default_org)

        response = auth_client.post(_register_webhook_url(node.id))

        assert response.status_code == 200, response.content
        assert response.json() == {
            "registered_url": self.EXPECTED_URL,
            "expected_url": self.EXPECTED_URL,
            "is_match": True,
            "pending_update_count": 0,
            "last_error_message": None,
            "last_error_date": None,
            "registration_blocker": None,
        }
        assert telegram.endpoints == ["setWebhook", "getWebhookInfo"]
        node.webhook_trigger.auth.refresh_from_db()
        assert node.webhook_trigger.auth.registered_webhook_url == self.EXPECTED_URL
        assert BOT_TOKEN not in response.content.decode()

    def test_takes_the_bot_key_over_from_another_trigger(
        self, auth_client, default_org, tunnel_url, telegram
    ):
        node = self._create_node(default_org)
        telegram.registered_url = f"{TUNNEL_URL}/webhooks/other-node-path/"

        response = auth_client.post(_register_webhook_url(node.id))

        assert response.status_code == 200, response.content
        assert response.json()["registered_url"] == self.EXPECTED_URL
        assert response.json()["is_match"] is True
        assert telegram.endpoints.count("setWebhook") == 1

    def test_blocked_configuration_returns_409_with_the_blocker_and_no_telegram_call(
        self, auth_client, default_org, tunnel_url, telegram
    ):
        node = self._create_node(default_org, telegram_secret_token=None)

        response = auth_client.post(_register_webhook_url(node.id))

        assert response.status_code == 409, response.content
        assert response.json() == {
            "status_code": 409,
            "code": "telegram_registration_blocked",
            "message": "This node's configuration does not allow registering its webhook.",
            "registration_blocker": {
                "code": "no_telegram_secret",
                "message": (
                    "No Telegram secret configured for this webhook trigger. Set one via the "
                    "trigger's `auth_secret_id` before registering."
                ),
            },
        }
        assert telegram.endpoints == []

    def test_node_without_bot_key_returns_400(self, auth_client, default_org, tunnel_url, telegram):
        node = self._create_node(default_org, with_bot_key=False)

        response = auth_client.post(_register_webhook_url(node.id))

        assert response.status_code == 400, response.content
        assert response.json()["code"] == "telegram_bot_key_not_configured"
        assert telegram.endpoints == []

    def test_undecryptable_bot_key_returns_500_without_calling_telegram(
        self, auth_client, default_org, tunnel_url, telegram
    ):
        node = self._create_node(default_org)
        Secret.objects.filter(pk=node.telegram_bot_api_key_secret_id).update(
            value="not-a-fernet-token"
        )

        response = auth_client.post(_register_webhook_url(node.id))

        assert response.status_code == 500, response.content
        assert response.json()["code"] == "secret_resolution_error"
        assert telegram.endpoints == []

    @pytest.mark.parametrize(
        # A single attempt even on a connection error: the user can click again.
        ("failure", "expected_attempts"),
        [("connection_error", 1), ("http_500", 1)],
    )
    def test_telegram_failure_returns_502_without_leaking_the_token_or_secret(
        self,
        auth_client,
        default_org,
        tunnel_url,
        telegram,
        captured_logs,
        failure,
        expected_attempts,
    ):
        node = self._create_node(default_org)

        def _fail(url):
            if failure == "connection_error":
                raise requests.exceptions.ConnectionError(f"Max retries exceeded with url: {url}")
            return _telegram_response(
                url, status_code=500, body={"ok": False, "description": "Internal"}
            )

        telegram.set_webhook_failure = _fail

        response = auth_client.post(_register_webhook_url(node.id))

        assert response.status_code == 502, response.content
        assert response.json() == {
            "status_code": 502,
            "code": "telegram_registration_failed",
            "message": (
                "Telegram could not register the webhook. Check the panel status and try again."
            ),
        }
        assert telegram.endpoints == ["setWebhook"] * expected_attempts
        body = response.content.decode()
        assert BOT_TOKEN not in body
        assert TELEGRAM_SECRET_TOKEN not in body
        assert any("Explicit webhook registration failed" in message for message in captured_logs)
        assert not any(BOT_TOKEN in message for message in captured_logs)
        assert not any(TELEGRAM_SECRET_TOKEN in message for message in captured_logs)

    @pytest.mark.parametrize("telegram_status", [401, 404])
    def test_bot_key_rejected_on_setwebhook_returns_422_without_leaking_secrets(
        self, auth_client, default_org, tunnel_url, telegram, captured_logs, telegram_status
    ):
        node = self._create_node(default_org)
        # requests puts the full URL, query string included, into an HTTPError's message.
        telegram.set_webhook_failure = lambda url: _telegram_response(
            f"{url}?url=x&secret_token={TELEGRAM_SECRET_TOKEN}",
            status_code=telegram_status,
            body={"ok": False, "error_code": telegram_status, "description": "Unauthorized"},
        )

        response = auth_client.post(_register_webhook_url(node.id))

        assert response.status_code == 422, response.content
        assert response.json() == BOT_KEY_REJECTED_BODY
        assert telegram.endpoints == ["setWebhook"]
        body = response.content.decode()
        assert BOT_TOKEN not in body
        assert TELEGRAM_SECRET_TOKEN not in body
        assert any(
            f"Telegram HTTP status {telegram_status}" in message for message in captured_logs
        )
        assert not any(BOT_TOKEN in message for message in captured_logs)
        assert not any(TELEGRAM_SECRET_TOKEN in message for message in captured_logs)

    def test_unavailable_tunnel_returns_503_without_calling_telegram(
        self, auth_client, default_org, telegram, mocker
    ):
        node = self._create_node(default_org)
        mocker.patch.object(
            WebhookTriggerService, "wait_for_tunnel_url_for_trigger", return_value=None
        )

        response = auth_client.post(_register_webhook_url(node.id))

        assert response.status_code == 503, response.content
        assert response.json() == {
            "status_code": 503,
            "code": "telegram_tunnel_unavailable",
            "message": (
                "The webhook tunnel is not available yet. Check the trigger's tunnel and "
                "try again."
            ),
        }
        assert telegram.endpoints == []

    def test_failed_follow_up_read_still_returns_200_from_the_confirmed_registration(
        self, auth_client, default_org, tunnel_url, telegram, captured_logs
    ):
        node = self._create_node(default_org)
        set_webhook = telegram.__call__

        def _webhook_info_unreachable(method, url, params=None, **kwargs):
            if url.endswith("/getWebhookInfo"):
                telegram.endpoints.append("getWebhookInfo")
                raise requests.exceptions.Timeout(f"Read timed out: {url}")
            return set_webhook(method, url, params=params, **kwargs)

        with patch(
            "tables.services.telegram_trigger_service.requests.request",
            _webhook_info_unreachable,
        ):
            response = auth_client.post(_register_webhook_url(node.id))

        assert response.status_code == 200, response.content
        assert response.json() == {
            "registered_url": self.EXPECTED_URL,
            "expected_url": self.EXPECTED_URL,
            "is_match": True,
            "pending_update_count": None,
            "last_error_message": None,
            "last_error_date": None,
            "registration_blocker": None,
        }
        assert telegram.endpoints == ["setWebhook", "getWebhookInfo"]
        assert any("follow-up read failed" in message for message in captured_logs)
        assert not any(BOT_TOKEN in message for message in captured_logs)

    def test_unexpected_error_is_a_500_logged_by_type_only(
        self, auth_client, default_org, tunnel_url, telegram, captured_logs, mocker
    ):
        node = self._create_node(default_org)
        mocker.patch(
            "tables.services.telegram_trigger_service.build_telegram_callback_url",
            side_effect=RuntimeError(f"bug near {BOT_TOKEN}"),
        )
        auth_client.raise_request_exception = False

        response = auth_client.post(_register_webhook_url(node.id))

        assert response.status_code == 500
        assert BOT_TOKEN not in response.content.decode()
        assert telegram.endpoints == []
        assert any(
            "Unexpected error registering" in message and "RuntimeError" in message
            for message in captured_logs
        )
        assert not any(BOT_TOKEN in message for message in captured_logs)
        assert not any("Traceback" in message for message in captured_logs)

    def test_node_in_another_org_returns_404(
        self, client_as, admin_acme, acme, beta, tunnel_url, telegram
    ):
        own_node = self._create_node(acme, path="acme-register-path")
        foreign_node = self._create_node(beta, path="beta-register-path")
        client = client_as(admin_acme)
        client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

        own_response = client.post(_register_webhook_url(own_node.id))
        foreign_response = client.post(_register_webhook_url(foreign_node.id))

        # Positive control: the same caller registers its own org's node, so the 404 is the org filter.
        assert own_response.status_code == 200, own_response.content
        assert foreign_response.status_code == 404, foreign_response.content
        assert telegram.endpoints == ["setWebhook", "getWebhookInfo"]

    def test_viewer_without_flows_update_gets_403(
        self, django_user_model, client_as, acme, role_viewer, tunnel_url, telegram
    ):
        node = self._create_node(acme)
        user = django_user_model.objects.create_user(
            email="viewer-register-tg@example.com", password="StrongPass123!"
        )
        OrganizationUser.objects.create(user=user, org=acme, role=role_viewer)
        client = client_as(user)
        client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

        response = client.post(_register_webhook_url(node.id))

        assert response.status_code == 403, response.content
        assert telegram.endpoints == []

    def test_unauthenticated_caller_is_rejected(self, api_client, default_org, tunnel_url, telegram):
        node = self._create_node(default_org)
        api_client.credentials(HTTP_X_ORGANIZATION_ID=str(default_org.id))

        response = api_client.post(_register_webhook_url(node.id))

        assert response.status_code == 401, response.content
        assert telegram.endpoints == []
