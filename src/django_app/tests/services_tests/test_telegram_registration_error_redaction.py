"""Telegram registration failures must never expose the bot token or the
webhook `secret_token`.

Both travel in the Telegram request URL
(`https://api.telegram.org/bot<token>/setWebhook?url=...&secret_token=...`),
and `requests` copies that URL into the text of its exceptions. These tests
drive real `requests` exceptions and responses (only the outbound HTTP call is
faked) through the service, the post_save signal and the webhook-trigger API,
and check every place the failure surfaces: the raised error, the API response
and the loguru log.
"""

from dataclasses import dataclass
from typing import Callable
from unittest.mock import patch
from urllib.parse import urlencode

import pytest
import requests
from django.urls import reverse
from loguru import logger
from requests.exceptions import ConnectionError, ReadTimeout, RequestException

from tables.exceptions import RegisterTelegramTriggerError
from tables.models import Secret
from tables.models.graph_models import Graph, TelegramTriggerNode
from tables.models.webhook_models import (
    NgrokWebhookConfig,
    ProviderType,
    WebhookTrigger,
    WebhookTriggerAuth,
    WebhookTriggerAuthKind,
)
from tables.services import telegram_trigger_service as telegram_trigger_module
from tables.services.secrets import secret_service
from tables.services.secrets.exceptions import SecretResolutionError
from tables.services.telegram_trigger_service import TelegramTriggerService
from tables.services.webhook_trigger_service import WebhookTriggerService

BOT_TOKEN = "123456789:AAHfakeBotTokenForRedactionTests_xyz"
SECRET_TOKEN = "TelegramWebhookSecretForRedactionTests0001"
ROTATED_SECRET_TOKEN = "TelegramWebhookSecretForRedactionTests0002"
SENSITIVE_VALUES = (BOT_TOKEN, SECRET_TOKEN, ROTATED_SECRET_TOKEN)


def _full_url(url: str, params: dict | None) -> str:
    return f"{url}?{urlencode(params or {})}"


def _http_response(url: str, params: dict | None, status_code: int, body: str):
    response = requests.Response()
    response.status_code = status_code
    response.reason = "Telegram Test Reason"
    response.url = _full_url(url, params)
    response._content = body.encode()
    response.request = requests.Request("POST", response.url).prepare()
    return response


def _connection_error(method, url, params=None, timeout=None):
    raise ConnectionError(
        "HTTPSConnectionPool(host='api.telegram.org', port=443): Max retries "
        f"exceeded with url: {_full_url(url, params)}"
    )


def _timeout(method, url, params=None, timeout=None):
    raise ReadTimeout(
        "HTTPSConnectionPool(host='api.telegram.org', port=443): Read timed "
        f"out. (read timeout=10) url: {_full_url(url, params)}"
    )


def _http_401(method, url, params=None, timeout=None):
    return _http_response(
        url,
        params,
        401,
        f'{{"ok": false, "error_code": 401, "description": "Unauthorized {BOT_TOKEN}"}}',
    )


def _http_500(method, url, params=None, timeout=None):
    return _http_response(url, params, 500, f"<html>{_full_url(url, params)}</html>")


def _non_json_body(method, url, params=None, timeout=None):
    return _http_response(url, params, 200, f"<html>{_full_url(url, params)}</html>")


def _ok_false_body(method, url, params=None, timeout=None):
    return _http_response(
        url,
        params,
        200,
        '{"ok": false, "error_code": 400, "description": '
        f'"Bad Request: bad webhook {_full_url(url, params)}"}}',
    )


@dataclass(frozen=True)
class FailureScenario:
    name: str
    fake_request: Callable
    expected_message: str


FAILURE_SCENARIOS = [
    FailureScenario("connection_error", _connection_error, "Telegram API is unreachable"),
    FailureScenario("timeout", _timeout, "Telegram API timed out"),
    FailureScenario(
        "http_401", _http_401, "Telegram rejected the bot API key (HTTP 401)"
    ),
    FailureScenario("http_500", _http_500, "Telegram API returned HTTP 500"),
    FailureScenario(
        "non_json_body",
        _non_json_body,
        "Telegram API returned a response that is not valid JSON",
    ),
    FailureScenario(
        "ok_false_body",
        _ok_false_body,
        "Telegram API rejected the request (error_code 400)",
    ),
]
SCENARIO_IDS = [scenario.name for scenario in FAILURE_SCENARIOS]


def _assert_contains_no_secret(text: str) -> None:
    for sensitive_value in SENSITIVE_VALUES:
        assert sensitive_value not in text


def _raw_failure_text(fake_request: Callable) -> str:
    """Run a fake through the same `requests` calls the service makes and
    return everything the raw exception exposes."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"
    params = {"url": "https://tunnel.test/webhooks/x/", "secret_token": SECRET_TOKEN}
    try:
        response = fake_request("POST", url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
    except RequestException as error:
        return f"{error} {getattr(error, 'doc', '')}"
    return str(data)


@pytest.fixture
def captured_logs():
    messages: list[str] = []
    sink_id = logger.add(
        messages.append,
        level="DEBUG",
        format="{message}",
        backtrace=True,
        diagnose=True,
    )
    yield messages
    logger.remove(sink_id)


@pytest.fixture
def telegram_environment(monkeypatch):
    """Stub the tunnel side (Redis) and the retry back-off; the Telegram HTTP
    call itself is faked per test through `requests.request`."""
    monkeypatch.setattr(WebhookTriggerService, "register_webhooks", lambda self: True)
    monkeypatch.setattr(
        WebhookTriggerService,
        "wait_for_tunnel_url_for_trigger",
        lambda self, webhook_trigger: "https://tunnel.test",
    )
    monkeypatch.setattr(telegram_trigger_module.time, "sleep", lambda seconds: None)


def _fake_telegram(monkeypatch, fake_request: Callable) -> list[str]:
    requested_urls: list[str] = []

    def _recording_request(method, url, params=None, timeout=None):
        requested_urls.append(url)
        return fake_request(method, url, params=params, timeout=timeout)

    monkeypatch.setattr(telegram_trigger_module.requests, "request", _recording_request)
    return requested_urls


def _create_telegram_trigger(org, path: str) -> WebhookTrigger:
    trigger = WebhookTrigger.objects.create(
        path=path, provider_type=ProviderType.NGROK, org=org
    )
    NgrokWebhookConfig.objects.create(
        name=f"cfg-{path}",
        auth_token_secret=secret_service.create(
            text="ngrok-token", org=org, name=f"{path}-ngrok-secret"
        ),
        trigger=trigger,
    )
    WebhookTriggerService().set_trigger_auth_secret(
        trigger,
        secret=secret_service.create(
            text=SECRET_TOKEN, org=org, name=f"{path}-telegram-secret"
        ),
        kind=WebhookTriggerAuthKind.TELEGRAM,
    )
    return trigger


def _create_node(org, trigger: WebhookTrigger) -> TelegramTriggerNode:
    return TelegramTriggerNode.objects.create(
        node_name=f"node-{trigger.path}",
        graph=Graph.objects.create(name=f"g-{trigger.path}", org=org),
        webhook_trigger=trigger,
        telegram_bot_api_key_secret=secret_service.create(
            text=BOT_TOKEN, org=org, name=f"{trigger.path}-bot-secret"
        ),
    )


def _corrupt_secret(secret_id: int) -> None:
    # Not a valid Fernet token, so decryption fails. It embeds the bot token so
    # a traceback that prints the stored value (loguru `diagnose`) would show up.
    Secret.objects.filter(pk=secret_id).update(value=f"not-a-fernet-token-{BOT_TOKEN}")


def _create_node_without_registering(org, trigger: WebhookTrigger) -> TelegramTriggerNode:
    with patch.object(
        TelegramTriggerService,
        "register_telegram_trigger",
        lambda self, telegram_trigger_instance=None, **kwargs: None,
    ):
        return _create_node(org, trigger)


@pytest.mark.parametrize("scenario", FAILURE_SCENARIOS, ids=SCENARIO_IDS)
def test_raw_requests_failure_really_carries_a_secret(scenario):
    """Guards the other tests against passing vacuously: the faked failures
    expose the bot token or secret_token exactly as real `requests` errors do."""
    raw_text = _raw_failure_text(scenario.fake_request)

    assert BOT_TOKEN in raw_text or SECRET_TOKEN in raw_text


@pytest.mark.django_db
class TestServiceRegistrationError:
    @pytest.mark.parametrize("scenario", FAILURE_SCENARIOS, ids=SCENARIO_IDS)
    def test_registration_error_carries_no_secret_and_stays_informative(
        self, default_org, telegram_environment, monkeypatch, captured_logs, scenario
    ):
        trigger = _create_telegram_trigger(default_org, f"redact-svc-{scenario.name}")
        node = _create_node_without_registering(default_org, trigger)
        _fake_telegram(monkeypatch, scenario.fake_request)

        with pytest.raises(RegisterTelegramTriggerError) as exc_info:
            TelegramTriggerService().register_telegram_trigger(
                telegram_trigger_instance=node
            )

        error = exc_info.value
        assert str(error.detail) == (
            f"Failed to register Telegram webhook: {scenario.expected_message}"
        )
        _assert_contains_no_secret(repr(error))
        assert error.__cause__ is None
        assert error.__context__ is None
        _assert_contains_no_secret("\n".join(captured_logs))

    @pytest.mark.parametrize(
        "fake_request", [_connection_error, _timeout], ids=["connection_error", "timeout"]
    )
    def test_connection_errors_and_timeouts_are_still_retried_three_times(
        self, default_org, telegram_environment, monkeypatch, fake_request
    ):
        trigger = _create_telegram_trigger(
            default_org, f"redact-svc-retry-{fake_request.__name__.strip('_')}"
        )
        node = _create_node_without_registering(default_org, trigger)
        requested_urls = _fake_telegram(monkeypatch, fake_request)

        with pytest.raises(RegisterTelegramTriggerError):
            TelegramTriggerService().register_telegram_trigger(
                telegram_trigger_instance=node
            )

        assert len(requested_urls) == 3

    def test_unexpected_exception_is_reported_by_type_only(
        self, default_org, telegram_environment, monkeypatch, captured_logs
    ):
        def _unexpected(method, url, params=None, timeout=None):
            raise ValueError(f"cannot handle {_full_url(url, params)}")

        trigger = _create_telegram_trigger(default_org, "redact-svc-unexpected")
        node = _create_node_without_registering(default_org, trigger)
        _fake_telegram(monkeypatch, _unexpected)

        with pytest.raises(RegisterTelegramTriggerError) as exc_info:
            TelegramTriggerService().register_telegram_trigger(
                telegram_trigger_instance=node
            )

        assert str(exc_info.value.detail) == (
            "Failed to register Telegram webhook: unexpected ValueError"
        )
        assert exc_info.value.__context__ is None
        log_text = "\n".join(captured_logs)
        assert (
            f"[TelegramTrigger] Registration for node {node.pk}: unexpected ValueError"
        ) in log_text
        assert "Traceback" not in log_text
        _assert_contains_no_secret(log_text)

    def test_undecryptable_bot_key_raises_resolution_error_without_secret(
        self, default_org, telegram_environment, monkeypatch, captured_logs
    ):
        trigger = _create_telegram_trigger(default_org, "redact-svc-corrupt-key")
        node = _create_node_without_registering(default_org, trigger)
        _corrupt_secret(node.telegram_bot_api_key_secret_id)
        requested_urls = _fake_telegram(monkeypatch, _connection_error)

        with pytest.raises(SecretResolutionError) as exc_info:
            TelegramTriggerService().register_telegram_trigger(
                telegram_trigger_instance=node
            )

        assert str(exc_info.value.detail) == (
            f"Secret id={node.telegram_bot_api_key_secret_id} for "
            "TelegramTriggerNode.telegram_bot_api_key could not be resolved: "
            "value not decryptable."
        )
        _assert_contains_no_secret(repr(exc_info.value))
        _assert_contains_no_secret("\n".join(captured_logs))
        assert requested_urls == []

    def test_successful_registration_returns_telegram_payload(
        self, default_org, telegram_environment, monkeypatch
    ):
        def _ok(method, url, params=None, timeout=None):
            return _http_response(url, params, 200, '{"ok": true, "result": true}')

        trigger = _create_telegram_trigger(default_org, "redact-svc-ok")
        node = _create_node_without_registering(default_org, trigger)
        requested_urls = _fake_telegram(monkeypatch, _ok)

        result = TelegramTriggerService().register_telegram_trigger(
            telegram_trigger_instance=node
        )

        assert result == {"ok": True, "result": True}
        assert requested_urls == [f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"]
        auth = WebhookTriggerAuth.objects.get(trigger=trigger)
        assert auth.registered_webhook_url == "https://tunnel.test/webhooks/redact-svc-ok/"


@pytest.mark.django_db
class TestPostSaveSignalLog:
    @pytest.mark.parametrize("scenario", FAILURE_SCENARIOS, ids=SCENARIO_IDS)
    def test_signal_logs_failure_without_secret(
        self, default_org, telegram_environment, monkeypatch, captured_logs, scenario
    ):
        trigger = _create_telegram_trigger(default_org, f"redact-sig-{scenario.name}")
        _fake_telegram(monkeypatch, scenario.fake_request)

        node = _create_node(default_org, trigger)

        log_text = "\n".join(captured_logs)
        _assert_contains_no_secret(log_text)
        assert (
            f"Error registering telegram bot {node.pk}: Failed to register "
            f"Telegram webhook: {scenario.expected_message}"
        ) in log_text

    def test_signal_logs_undecryptable_bot_key_without_traceback_or_secret(
        self, default_org, telegram_environment, monkeypatch, captured_logs
    ):
        trigger = _create_telegram_trigger(default_org, "redact-sig-corrupt-key")
        bot_key_secret = secret_service.create(
            text=BOT_TOKEN, org=default_org, name="redact-sig-corrupt-key-bot-secret"
        )
        _corrupt_secret(bot_key_secret.id)
        requested_urls = _fake_telegram(monkeypatch, _connection_error)

        node = TelegramTriggerNode.objects.create(
            node_name="node-redact-sig-corrupt-key",
            graph=Graph.objects.create(name="g-redact-sig-corrupt-key", org=default_org),
            webhook_trigger=trigger,
            telegram_bot_api_key_secret=bot_key_secret,
        )

        log_text = "\n".join(captured_logs)
        _assert_contains_no_secret(log_text)
        assert "Traceback" not in log_text
        assert (
            f"Error registering telegram bot {node.pk}: Secret id={bot_key_secret.id} "
            "for TelegramTriggerNode.telegram_bot_api_key could not be resolved: "
            "value not decryptable."
        ) in log_text
        assert requested_urls == []


@pytest.mark.django_db
class TestWebhookTriggerApiWarning:
    @pytest.mark.parametrize("scenario", FAILURE_SCENARIOS, ids=SCENARIO_IDS)
    def test_secret_update_warning_carries_no_secret(
        self,
        auth_client,
        default_org,
        telegram_environment,
        monkeypatch,
        captured_logs,
        scenario,
    ):
        trigger = _create_telegram_trigger(default_org, f"redact-api-{scenario.name}")
        node = _create_node_without_registering(default_org, trigger)
        rotated_secret = secret_service.create(
            text=ROTATED_SECRET_TOKEN,
            org=default_org,
            name=f"redact-api-{scenario.name}-rotated",
        )
        _fake_telegram(monkeypatch, scenario.fake_request)

        response = auth_client.patch(
            reverse("webhooktrigger-detail", args=[trigger.id]),
            {"auth_secret_id": rotated_secret.id},
            format="json",
        )

        assert response.status_code == 200, response.json()
        _assert_contains_no_secret(response.content.decode())
        warning = response.json()["telegram_registration_warning"]
        assert (
            f"node {node.pk}: Failed to register Telegram webhook: "
            f"{scenario.expected_message}"
        ) in warning
        _assert_contains_no_secret("\n".join(captured_logs))

    def test_secret_update_warning_for_undecryptable_bot_key_carries_no_secret(
        self, auth_client, default_org, telegram_environment, monkeypatch, captured_logs
    ):
        trigger = _create_telegram_trigger(default_org, "redact-api-corrupt-key")
        node = _create_node_without_registering(default_org, trigger)
        _corrupt_secret(node.telegram_bot_api_key_secret_id)
        rotated_secret = secret_service.create(
            text=ROTATED_SECRET_TOKEN,
            org=default_org,
            name="redact-api-corrupt-key-rotated",
        )
        _fake_telegram(monkeypatch, _connection_error)

        response = auth_client.patch(
            reverse("webhooktrigger-detail", args=[trigger.id]),
            {"auth_secret_id": rotated_secret.id},
            format="json",
        )

        assert response.status_code == 200, response.json()
        _assert_contains_no_secret(response.content.decode())
        assert (
            f"node {node.pk}: Secret id={node.telegram_bot_api_key_secret_id} for "
            "TelegramTriggerNode.telegram_bot_api_key could not be resolved: "
            "value not decryptable."
        ) in response.json()["telegram_registration_warning"]
        _assert_contains_no_secret("\n".join(captured_logs))
