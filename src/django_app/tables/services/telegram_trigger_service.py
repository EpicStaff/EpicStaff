import functools
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import requests
from loguru import logger
from requests.exceptions import (
    ConnectionError,
    HTTPError,
    JSONDecodeError,
    RequestException,
    Timeout,
)
from tables.exceptions import (
    RegisterTelegramTriggerError,
    TelegramApiError,
    TelegramBotKeyNotConfiguredError,
    TelegramWebhookInfoUnavailableError,
)
from tables.models.graph_models import TelegramTriggerNode
from tables.models.webhook_models import (
    LOCAL_ONLY_PROVIDERS,
    WebhookTrigger,
    WebhookTriggerAuth,
    WebhookTriggerAuthKind,
)
from tables.services.secrets import secret_resolver
from tables.services.session_manager_service import SessionManagerService
from tables.services.trigger_spec import TriggerSpec
from tables.services.webhook_trigger_service import WebhookTriggerService
from tables.validators.telegram_secret_token_validator import (
    validate_telegram_secret_token,
)
from utils.singleton_meta import SingletonMeta

TELEGRAM_WEBHOOK_HEADER = WebhookTriggerAuth.HEADER_NAMES[WebhookTriggerAuthKind.TELEGRAM]

TELEGRAM_API_TIMEOUT_SECONDS = 10
# A single short attempt: this backs a panel read, so the retrying
# `_call_telegram_api` (up to ~34 s) would leave the UI hanging. `requests`
# applies a (connect, read) pair separately, so the worst case is their sum
# (~8 s); the read limit is per socket read, not a total-response deadline.
WEBHOOK_INFO_CONNECT_READ_TIMEOUT_SECONDS = (3, 5)


def build_telegram_callback_url(tunnel_url: str, webhook_trigger_path: str) -> str:
    """Return the URL Telegram must call for a trigger path: `<tunnel>/webhooks/<path>/`."""
    return f"{tunnel_url}/webhooks/{webhook_trigger_path}/"


@dataclass(frozen=True)
class TelegramWebhookStatus:
    """What Telegram has registered for a node's bot key, next to what this node expects.

    Telegram keeps one webhook per bot key, so `registered_url` can belong to a
    different trigger node that shares the key; `is_match` flags that case.
    `expected_url` is None when this node has no reachable callback URL right now.
    `is_match` is False when Telegram has no webhook set (this node cannot be
    receiving messages), and None only when `expected_url` is unknown.
    """

    registered_url: str | None
    expected_url: str | None
    is_match: bool | None
    pending_update_count: int | None
    last_error_message: str | None
    last_error_date: datetime | None


def _retry_on_connection_errors(func):
    """Retry up to 3 attempts on ConnectionError/Timeout, exponential backoff (2s, 2s), then reraise."""
    max_attempts = 3

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        for attempt in range(1, max_attempts + 1):
            try:
                return func(*args, **kwargs)
            except (ConnectionError, Timeout):
                if attempt == max_attempts:
                    raise
                wait_seconds = min(max(1 * (2 ** (attempt - 1)), 2), 10)
                time.sleep(wait_seconds)

    return wrapper


def _describe_request_failure(error: RequestException) -> str:
    """Summarise a failed Telegram request without using the exception's text.

    `requests` puts the full request URL -- which embeds the bot token and the
    `secret_token` query parameter -- into the message of `HTTPError` and of
    most connection errors, so only the exception type and HTTP status are used.
    """
    if isinstance(error, Timeout):
        return "Telegram API timed out"
    if isinstance(error, ConnectionError):
        return "Telegram API is unreachable"
    if isinstance(error, JSONDecodeError):
        return "Telegram API returned a response that is not valid JSON"
    if isinstance(error, HTTPError) and error.response is not None:
        status_code = error.response.status_code
        # Telegram answers 401 for an unknown bot token and 404 for a malformed one.
        if status_code in (401, 404):
            return f"Telegram rejected the bot API key (HTTP {status_code})"
        return f"Telegram API returned HTTP {status_code}"
    return f"Telegram API request failed ({type(error).__name__})"


def _describe_rejection(data: object) -> str:
    # Telegram's free-text `description` is deliberately left out: it is
    # third-party text we cannot prove never echoes the request back.
    error_code = data.get("error_code") if isinstance(data, dict) else None
    if isinstance(error_code, int):
        return f"Telegram API rejected the request (error_code {error_code})"
    return "Telegram API rejected the request"


class TelegramTriggerService(metaclass=SingletonMeta):
    def __init__(
        self,
        session_manager_service: SessionManagerService,
        webhook_trigger_service: WebhookTriggerService,
    ):
        self.webhook_trigger_service = webhook_trigger_service
        self.session_manager_service = session_manager_service or SessionManagerService()

    def _send_telegram_request(
        self,
        method: str,
        api_key: str,
        endpoint: str,
        params: dict | None = None,
        timeout: float | tuple[float, float] = TELEGRAM_API_TIMEOUT_SECONDS,
    ) -> dict:
        """Make one Telegram Bot API call and return its decoded body.

        The request URL embeds the bot token, so the `requests` exceptions
        raised here carry it in their message: callers must never surface
        `str(error)` to a client or a log line.

        Raises:
            requests.RequestException: Network failure, timeout, non-2xx, or a
                body that is not JSON.
            TelegramApiError: Telegram answered `ok: false`. Its message never
                contains the request URL, the bot token or any parameter.
        """
        url = f"https://api.telegram.org/bot{api_key}/{endpoint}"
        response = requests.request(method, url, params=params, timeout=timeout)

        response.raise_for_status()
        data = response.json()

        if not isinstance(data, dict) or not data.get("ok"):
            raise TelegramApiError(_describe_rejection(data))

        return data

    @_retry_on_connection_errors
    def _send_telegram_request_with_retries(
        self, method: str, api_key: str, endpoint: str, params: dict | None = None
    ) -> dict:
        """`_send_telegram_request`, retried on connection errors and timeouts."""
        return self._send_telegram_request(method, api_key, endpoint, params=params)

    def _call_telegram_api(
        self, method: str, api_key: str, endpoint: str, params: dict | None = None
    ) -> dict:
        """Call the Telegram Bot API, retrying connection errors and timeouts.

        Raises:
            TelegramApiError: The call failed. Its message never contains the
                request URL, the bot token or any request parameter.
        """
        try:
            return self._send_telegram_request_with_retries(method, api_key, endpoint, params)
        except RequestException as error:
            failure = _describe_request_failure(error)
        # Raised outside the `except` block so the `requests` exception, whose
        # message and `.request.url` carry the bot token, is not kept as
        # `__context__` for a traceback formatter to print.
        raise TelegramApiError(failure)

    def register_telegram_trigger(
        self, telegram_trigger_instance: TelegramTriggerNode, force: bool = False
    ) -> dict | None:
        """Register (or resync) this node's Telegram webhook.

        `force=False` skips the outbound `setWebhook` call when a valid
        registration already exists for the SAME resolved callback URL, the
        SAME bot API key, AND the SAME secret -- compared by their actual
        values, not by `webhook_trigger` id, since the same `WebhookTrigger`
        row can resolve to a different tunnel URL over time (e.g. its domain
        changes), the same node can be repointed at a different Telegram
        bot while the trigger/tunnel stays put, and the user can edit the
        trigger's secret at any time via the API. Any of these changes must
        still trigger a real resync.
        """
        if telegram_trigger_instance.telegram_bot_api_key_secret_id is None:
            logger.warning(
                f"[TelegramTrigger] Skipping registration for node {telegram_trigger_instance.pk}: no bot API key secret set."
            )
            return

        webhook_trigger: WebhookTrigger = telegram_trigger_instance.webhook_trigger
        if webhook_trigger is None:
            logger.warning(
                f"[TelegramTrigger] Skipping registration for node {telegram_trigger_instance.pk}: no webhook_trigger configured."
            )
            return
        if webhook_trigger.provider_type is None:
            logger.warning(
                f"[TelegramTrigger] Skipping registration for node {telegram_trigger_instance.pk}: webhook_trigger has no tunnel config."
            )
            return
        if webhook_trigger.provider_type in LOCAL_ONLY_PROVIDERS:
            raise RegisterTelegramTriggerError(
                "Localhost webhook provider is not reachable by Telegram. "
                "Use ngrok or a publicly accessible provider."
            )
        try:
            webhook_tunnel_url = self.webhook_trigger_service.wait_for_tunnel_url_for_trigger(
                webhook_trigger
            )
        except Exception as e:
            raise RegisterTelegramTriggerError(
                f"Failed to fetch tunnel URL: {e!s}", status_code=503
            ) from e

        if not webhook_tunnel_url:
            raise RegisterTelegramTriggerError(
                "Tunnel URL is not yet available, try again once the tunnel is established.",
                status_code=503,
            )

        telegram_webhook_url = build_telegram_callback_url(webhook_tunnel_url, webhook_trigger.path)

        trigger_auth: WebhookTriggerAuth | None = getattr(webhook_trigger, "auth", None)
        if trigger_auth is not None and trigger_auth.kind != WebhookTriggerAuthKind.TELEGRAM:
            raise RegisterTelegramTriggerError(
                "This webhook trigger's auth is already configured for a "
                "different kind (e.g. a user-set webhook-trigger secret) and "
                "cannot also be used for Telegram."
            )

        if trigger_auth is None or trigger_auth.secret_id is None:
            raise RegisterTelegramTriggerError(
                "No Telegram secret configured for this webhook trigger. Set "
                "one via the trigger's `auth_secret_id` before registering.",
                status_code=400,
            )

        secret_token = secret_resolver.resolve(
            secret_id=trigger_auth.secret_id,
            org_id=webhook_trigger.org_id,
            context="WebhookTriggerAuth.secret (telegram)",
        )
        try:
            validate_telegram_secret_token(secret_token)
        except ValueError as e:
            raise RegisterTelegramTriggerError(str(e), status_code=400) from e

        already_registered = (
            not force
            and trigger_auth.registered_webhook_url == telegram_webhook_url
            and trigger_auth.registered_bot_api_key_secret_id
            == telegram_trigger_instance.telegram_bot_api_key_secret_id
            and trigger_auth.registered_secret_id == trigger_auth.secret_id
        )
        if already_registered:
            logger.info(
                f"[TelegramTrigger] Skipping resync for node {telegram_trigger_instance.pk}: "
                "already registered for this webhook_trigger, no change needed."
            )
            return None

        bot_api_key = secret_resolver.resolve(
            # webhook_trigger is confirmed non-None above (return-early
            # guard); it carries the same org as the node's graph and is
            # available here without requiring a saved/loaded graph.
            secret_id=telegram_trigger_instance.telegram_bot_api_key_secret_id,
            org_id=webhook_trigger.org_id,
            context="TelegramTriggerNode.telegram_bot_api_key",
        )
        failure = None
        try:
            result = self._call_telegram_api(
                method="POST",
                api_key=bot_api_key,
                endpoint="setWebhook",
                params={
                    "url": telegram_webhook_url,
                    "secret_token": secret_token,
                },
            )
        except TelegramApiError as error:
            failure = str(error)
        except Exception as error:
            # Anything else escaping the HTTP call may still reference the
            # request, so only its type is reported.
            failure = f"unexpected {type(error).__name__}"
            # Only a breadcrumb, no exc_info: the traceback would print the
            # bot token held in this frame's and the request's locals.
            logger.error(
                "[TelegramTrigger] Registration for node {}: unexpected {}",
                telegram_trigger_instance.pk,
                type(error).__name__,
            )
        if failure is not None:
            # Raised outside the `except` block for the same reason as in
            # `_call_telegram_api`: no exception chain back to the request.
            raise RegisterTelegramTriggerError(f"Failed to register Telegram webhook: {failure}")

        trigger_auth.registered_webhook_url = telegram_webhook_url
        trigger_auth.registered_bot_api_key_secret_id = (
            telegram_trigger_instance.telegram_bot_api_key_secret_id
        )
        trigger_auth.registered_secret_id = trigger_auth.secret_id
        trigger_auth.save(
            update_fields=[
                "registered_webhook_url",
                "registered_bot_api_key_secret_id",
                "registered_secret_id",
            ]
        )

        return result

    def unregister_telegram_trigger(self, telegram_bot_api_key: str):
        try:
            return self._call_telegram_api(
                method="POST", api_key=telegram_bot_api_key, endpoint="deleteWebhook"
            )
        except Exception:
            return {"ok": False, "description": "Unregistration failed"}

    def handle_telegram_trigger(
        self,
        path: str,
        payload: dict,
        config_id: str | None = None,
    ) -> None:
        filters = self.webhook_trigger_service.get_trigger_filters(path=path, config_id=config_id)
        if filters is None:
            return

        telegram_trigger_node_list = TelegramTriggerNode.objects.filter(**filters)

        for telegram_trigger_node in telegram_trigger_node_list:
            # Persistent-variable merging is owned by run_session.
            self.session_manager_service.run_session(
                graph_id=telegram_trigger_node.graph.pk,
                variables={"telegram_payload": payload},
                trigger=TriggerSpec.telegram(telegram_trigger_node, payload),
            )

    def get_webhook_status(
        self, telegram_trigger_node: TelegramTriggerNode
    ) -> TelegramWebhookStatus:
        """Ask Telegram which webhook URL is registered for this node's bot key.

        Reads Telegram's `getWebhookInfo` (the source of truth) rather than the
        stored `WebhookTriggerAuth.registered_webhook_url`, which is kept per
        trigger and goes stale as soon as another node sharing the bot key
        registers its own URL. Makes one attempt with a short timeout.

        Args:
            telegram_trigger_node: A saved node; its graph's org scopes the
                bot-key lookup, so the caller must have org-scoped it already.

        Raises:
            TelegramBotKeyNotConfiguredError: The node has no bot key secret.
            TelegramWebhookInfoUnavailableError: Telegram was unreachable, answered
                non-2xx, or answered `ok: false`.
        """
        if telegram_trigger_node.telegram_bot_api_key_secret_id is None:
            raise TelegramBotKeyNotConfiguredError()

        bot_api_key = secret_resolver.resolve(
            secret_id=telegram_trigger_node.telegram_bot_api_key_secret_id,
            org_id=telegram_trigger_node.graph.org_id,
            context="TelegramTriggerNode.telegram_bot_api_key",
        )
        try:
            webhook_info = self._send_telegram_request(
                method="GET",
                api_key=bot_api_key,
                endpoint="getWebhookInfo",
                timeout=WEBHOOK_INFO_CONNECT_READ_TIMEOUT_SECONDS,
            )["result"]
        except (requests.RequestException, TelegramApiError) as error:
            # Never log `error` itself: its message carries the bot-token URL.
            response = getattr(error, "response", None)
            logger.warning(
                "[TelegramTrigger] getWebhookInfo failed for node {node_id}: {error_type} (HTTP status {status})",
                node_id=telegram_trigger_node.pk,
                error_type=type(error).__name__,
                status=response.status_code if response is not None else None,
            )
            raise TelegramWebhookInfoUnavailableError() from None

        registered_url = webhook_info.get("url") or None
        expected_url = self._get_expected_callback_url(telegram_trigger_node)
        is_match = None
        if expected_url is not None:
            is_match = registered_url is not None and (
                registered_url.rstrip("/") == expected_url.rstrip("/")
            )

        last_error_timestamp = webhook_info.get("last_error_date")
        return TelegramWebhookStatus(
            registered_url=registered_url,
            expected_url=expected_url,
            is_match=is_match,
            pending_update_count=webhook_info.get("pending_update_count"),
            last_error_message=webhook_info.get("last_error_message"),
            last_error_date=(
                datetime.fromtimestamp(last_error_timestamp, tz=UTC)
                if last_error_timestamp
                else None
            ),
        )

    def _get_expected_callback_url(self, telegram_trigger_node: TelegramTriggerNode) -> str | None:
        webhook_trigger = telegram_trigger_node.webhook_trigger
        if webhook_trigger is None or webhook_trigger.provider_type in LOCAL_ONLY_PROVIDERS:
            return None
        tunnel_url = self.webhook_trigger_service.get_tunnel_url_for_trigger(webhook_trigger)
        if not tunnel_url:
            return None
        return build_telegram_callback_url(tunnel_url, webhook_trigger.path)
