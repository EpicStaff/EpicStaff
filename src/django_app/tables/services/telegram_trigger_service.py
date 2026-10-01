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
from tables.constants.telegram_constants import TelegramRegistrationBlockerCode
from tables.exceptions import (
    RegisterTelegramTriggerError,
    TelegramApiError,
    TelegramBotKeyNotConfiguredError,
    TelegramBotKeyRejectedError,
    TelegramRegistrationBlockedError,
    TelegramRegistrationFailedError,
    TelegramRegistrationPreconditionError,
    TelegramTunnelUnavailableError,
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
from tables.services.secrets.exceptions import SecretResolutionError
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


def _is_same_callback_url(registered_url: str, expected_url: str) -> bool:
    return registered_url.rstrip("/") == expected_url.rstrip("/")


# Registration logs these and returns quietly instead of raising: a node saved
# half-configured in the editor is normal, not an error.
_SILENT_REGISTRATION_BLOCKERS = frozenset(
    {
        TelegramRegistrationBlockerCode.NO_BOT_KEY,
        TelegramRegistrationBlockerCode.NO_WEBHOOK_TRIGGER,
        TelegramRegistrationBlockerCode.NO_TUNNEL_PROVIDER,
    }
)


@dataclass(frozen=True)
class TelegramRegistrationBlocker:
    """A configuration problem that makes `setWebhook` for a node impossible.

    `message` is user-facing and never contains a secret value.
    """

    code: TelegramRegistrationBlockerCode
    message: str


@dataclass(frozen=True)
class TelegramWebhookStatus:
    """What Telegram has registered for a node's bot key, next to what this node expects.

    Telegram keeps one webhook per bot key, so `registered_url` can belong to a
    different trigger node that shares the key; `is_match` flags that case.
    `expected_url` is None when this node has no reachable callback URL right now.
    `is_match` is False when Telegram has no webhook set (this node cannot be
    receiving messages), and None only when `expected_url` is unknown.
    `registration_blocker` is None when nothing in the configuration stops
    this node from registering.
    """

    registered_url: str | None
    expected_url: str | None
    is_match: bool | None
    pending_update_count: int | None
    last_error_message: str | None
    last_error_date: datetime | None
    registration_blocker: TelegramRegistrationBlocker | None


def _resolve_registration_secret_or_blocker(
    telegram_trigger_node: TelegramTriggerNode,
) -> tuple[TelegramRegistrationBlocker | None, str | None]:
    """Return the first configuration blocker, else the resolved Telegram secret token.

    The single definition of "can this node register?", shared by registration
    and the webhook-info panel so the two cannot drift. Reads the DB only;
    never calls Telegram.

    Raises:
        SecretResolutionError: The trigger's Telegram secret cannot be read.
    """
    if telegram_trigger_node.telegram_bot_api_key_secret_id is None:
        return TelegramRegistrationBlocker(
            TelegramRegistrationBlockerCode.NO_BOT_KEY,
            "This Telegram trigger node has no bot key configured.",
        ), None

    webhook_trigger: WebhookTrigger | None = telegram_trigger_node.webhook_trigger
    if webhook_trigger is None:
        return TelegramRegistrationBlocker(
            TelegramRegistrationBlockerCode.NO_WEBHOOK_TRIGGER,
            "This Telegram trigger node has no webhook trigger configured.",
        ), None
    if webhook_trigger.provider_type is None:
        return TelegramRegistrationBlocker(
            TelegramRegistrationBlockerCode.NO_TUNNEL_PROVIDER,
            "This node's webhook trigger has no tunnel provider configured.",
        ), None
    if webhook_trigger.provider_type in LOCAL_ONLY_PROVIDERS:
        return TelegramRegistrationBlocker(
            TelegramRegistrationBlockerCode.LOCALHOST_PROVIDER,
            "Localhost webhook provider is not reachable by Telegram. "
            "Use ngrok or a publicly accessible provider.",
        ), None

    trigger_auth: WebhookTriggerAuth | None = getattr(webhook_trigger, "auth", None)
    if trigger_auth is not None and trigger_auth.kind != WebhookTriggerAuthKind.TELEGRAM:
        return TelegramRegistrationBlocker(
            TelegramRegistrationBlockerCode.AUTH_KIND_CONFLICT,
            "This webhook trigger's auth is already configured for a "
            "different kind (e.g. a user-set webhook-trigger secret) and "
            "cannot also be used for Telegram.",
        ), None
    if trigger_auth is None or trigger_auth.secret_id is None:
        return TelegramRegistrationBlocker(
            TelegramRegistrationBlockerCode.NO_TELEGRAM_SECRET,
            "No Telegram secret configured for this webhook trigger. Set "
            "one via the trigger's `auth_secret_id` before registering.",
        ), None

    secret_token = secret_resolver.resolve(
        secret_id=trigger_auth.secret_id,
        org_id=webhook_trigger.org_id,
        context="WebhookTriggerAuth.secret (telegram)",
    )
    try:
        validate_telegram_secret_token(secret_token)
    except ValueError as error:
        # The validator's message describes the allowed format, never the value.
        return TelegramRegistrationBlocker(
            TelegramRegistrationBlockerCode.INVALID_TELEGRAM_SECRET, str(error)
        ), None
    return None, secret_token


def _get_registration_blocker(
    telegram_trigger_node: TelegramTriggerNode,
) -> TelegramRegistrationBlocker | None:
    try:
        blocker, _secret_token = _resolve_registration_secret_or_blocker(telegram_trigger_node)
    except SecretResolutionError:
        return TelegramRegistrationBlocker(
            TelegramRegistrationBlockerCode.UNRESOLVABLE_TELEGRAM_SECRET,
            "This webhook trigger's Telegram secret could not be read. Set it "
            "again via the trigger's `auth_secret_id`.",
        )
    return blocker


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


# Telegram answers 401 for an unknown or revoked bot token and 404 for a malformed one.
BOT_KEY_REJECTED_HTTP_STATUSES = frozenset({401, 404})


def _http_status_of(error: RequestException) -> int | None:
    response = error.response if isinstance(error, HTTPError) else None
    return response.status_code if response is not None else None


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
        if status_code in BOT_KEY_REJECTED_HTTP_STATUSES:
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
        self,
        method: str,
        api_key: str,
        endpoint: str,
        params: dict | None = None,
        single_attempt: bool = False,
    ) -> dict:
        """Call the Telegram Bot API, retrying connection errors and timeouts.

        Args:
            single_attempt: Make one attempt without retries, for a caller that
                answers a user who can simply try again.

        Raises:
            TelegramApiError: The call failed. Its message never contains the
                request URL, the bot token or any request parameter.
        """
        try:
            send = (
                self._send_telegram_request
                if single_attempt
                else self._send_telegram_request_with_retries
            )
            return send(method, api_key, endpoint, params)
        except RequestException as error:
            failure = _describe_request_failure(error)
            http_status = _http_status_of(error)
        # Raised outside the `except` block so the `requests` exception, whose
        # message and `.request.url` carry the bot token, is not kept as
        # `__context__` for a traceback formatter to print.
        raise TelegramApiError(failure, http_status=http_status)

    def register_telegram_trigger(
        self,
        telegram_trigger_instance: TelegramTriggerNode,
        force: bool = False,
        single_attempt: bool = False,
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

        When that stored record says nothing changed, the save costs one
        single-attempt `getWebhookInfo` call. It re-registers only when Telegram
        confirms the bot key has no webhook (e.g. deleted outside EpicStaff). It
        never overrides a different URL, which means another trigger shares the
        bot key; the webhook-info panel reports that conflict. A failed lookup
        keeps the skip. `force=True` always sends `setWebhook`, with no lookup.

        Static configuration problems and the bot key are checked first,
        before waiting for the tunnel, by the same rules the webhook-info
        panel reports.

        Args:
            single_attempt: Send `setWebhook` once instead of retrying
                connection errors, for a caller that answers a user who can
                simply retry.

        Raises:
            TelegramRegistrationPreconditionError: A configuration blocker
                other than a missing bot key, webhook trigger or tunnel
                provider (400). Its message is safe to log.
            SecretResolutionError: The bot key secret cannot be read.
            RegisterTelegramTriggerError: The tunnel URL is unavailable (503),
                or `setWebhook` failed. A failed `setWebhook`'s detail can
                contain the bot token: never log or return it.
        """
        blocker, secret_token = _resolve_registration_secret_or_blocker(telegram_trigger_instance)
        if blocker is not None:
            if blocker.code in _SILENT_REGISTRATION_BLOCKERS:
                logger.warning(
                    "[TelegramTrigger] Skipping registration for node {node_id}: {code}.",
                    node_id=telegram_trigger_instance.pk,
                    code=blocker.code.value,
                )
                return None
            raise TelegramRegistrationPreconditionError(blocker.message, status_code=400)

        webhook_trigger: WebhookTrigger = telegram_trigger_instance.webhook_trigger
        # Never None here: the blocker check above returned a secret, so the trigger has Telegram auth.
        trigger_auth: WebhookTriggerAuth = webhook_trigger.auth
        # Resolved before the tunnel wait so an unreadable key fails without waiting.
        bot_api_key = secret_resolver.resolve(
            # webhook_trigger carries the same org as the node's graph and is
            # available here without requiring a saved/loaded graph.
            secret_id=telegram_trigger_instance.telegram_bot_api_key_secret_id,
            org_id=webhook_trigger.org_id,
            context="TelegramTriggerNode.telegram_bot_api_key",
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

        recorded_as_registered = (
            not force
            and trigger_auth.registered_webhook_url == telegram_webhook_url
            and trigger_auth.registered_bot_api_key_secret_id
            == telegram_trigger_instance.telegram_bot_api_key_secret_id
            and trigger_auth.registered_secret_id == trigger_auth.secret_id
        )
        # The recorded columns are only what we last pushed; a manual
        # deleteWebhook changes Telegram's state behind them, so check before trusting them.
        if recorded_as_registered and self._should_keep_recorded_registration(
            bot_api_key, telegram_trigger_instance.pk, telegram_webhook_url
        ):
            logger.info(
                "[TelegramTrigger] Skipping resync for node {node_id}: "
                "already registered, no change needed.",
                node_id=telegram_trigger_instance.pk,
            )
            return None

        failure = None
        telegram_http_status = None
        try:
            result = self._call_telegram_api(
                method="POST",
                api_key=bot_api_key,
                endpoint="setWebhook",
                params={
                    "url": telegram_webhook_url,
                    "secret_token": secret_token,
                },
                single_attempt=single_attempt,
            )
        except TelegramApiError as error:
            failure = str(error)
            telegram_http_status = error.http_status
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
            registration_error = RegisterTelegramTriggerError(
                f"Failed to register Telegram webhook: {failure}"
            )
            registration_error.telegram_http_status = telegram_http_status
            raise registration_error

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

        `registration_blocker` comes from the DB alone, by the same rules
        `register_telegram_trigger` applies, and explains why registering this
        node cannot work even when Telegram's own state looks fine.

        Args:
            telegram_trigger_node: A saved node; its graph's org scopes the
                bot-key lookup, so the caller must have org-scoped it already.

        Raises:
            TelegramBotKeyNotConfiguredError: The node has no bot key secret.
            TelegramBotKeyRejectedError: Telegram answered 401/404 for the bot key.
            TelegramWebhookInfoUnavailableError: Telegram was unreachable, answered
                another non-2xx, or answered `ok: false`.
        """
        if telegram_trigger_node.telegram_bot_api_key_secret_id is None:
            raise TelegramBotKeyNotConfiguredError()

        registration_blocker = _get_registration_blocker(telegram_trigger_node)
        bot_api_key = secret_resolver.resolve(
            secret_id=telegram_trigger_node.telegram_bot_api_key_secret_id,
            org_id=telegram_trigger_node.graph.org_id,
            context="TelegramTriggerNode.telegram_bot_api_key",
        )
        webhook_info = self._fetch_webhook_info(bot_api_key, telegram_trigger_node.pk)

        registered_url = webhook_info.get("url") or None
        expected_url = self._get_expected_callback_url(telegram_trigger_node)
        is_match = None
        if expected_url is not None:
            is_match = registered_url is not None and _is_same_callback_url(
                registered_url, expected_url
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
            registration_blocker=registration_blocker,
        )

    def register_webhook_explicitly(
        self, telegram_trigger_node: TelegramTriggerNode
    ) -> TelegramWebhookStatus:
        """Push this node's webhook to Telegram now, then return Telegram's fresh state.

        Backs the panel's register button: a flow save only re-saves changed
        nodes, so an unchanged node never re-registers on its own. Always sends
        `setWebhook` (`force=True`), taking the bot key over from any other
        trigger that holds it, in a single attempt: the user can click again.

        When the follow-up `getWebhookInfo` read fails, the status is built
        from what `setWebhook` just confirmed instead of failing a request
        whose registration succeeded.

        Args:
            telegram_trigger_node: A saved node the caller has already org-scoped.

        Raises:
            TelegramBotKeyNotConfiguredError: The node has no bot key secret.
            TelegramRegistrationBlockedError: The node's configuration makes
                registration impossible; carries the blocker.
            SecretResolutionError: The bot key secret cannot be read.
            TelegramTunnelUnavailableError: The trigger's tunnel URL is unavailable.
            TelegramBotKeyRejectedError: Telegram answered 401/404 for the bot key.
            TelegramRegistrationFailedError: Telegram failed the registration.
                The cause is logged by type only, never its text.
        """
        if telegram_trigger_node.telegram_bot_api_key_secret_id is None:
            raise TelegramBotKeyNotConfiguredError()
        blocker = _get_registration_blocker(telegram_trigger_node)
        if blocker is not None:
            raise TelegramRegistrationBlockedError(blocker.code.value, blocker.message)

        try:
            self.register_telegram_trigger(telegram_trigger_node, force=True, single_attempt=True)
        except TelegramRegistrationPreconditionError:
            # Configuration changed since the blocker check; its message is safe to return.
            raise
        except RegisterTelegramTriggerError as error:
            # Only the type and the two status ints are logged, never the error's text.
            logger.warning(
                "[TelegramTrigger] Explicit webhook registration failed for node {node_id}: "
                "{error_type} (status {status}, Telegram HTTP status {http_status})",
                node_id=telegram_trigger_node.pk,
                error_type=type(error).__name__,
                status=error.status_code,
                http_status=error.telegram_http_status,
            )
            if error.telegram_http_status in BOT_KEY_REJECTED_HTTP_STATUSES:
                raise TelegramBotKeyRejectedError() from None
            if error.status_code == TelegramTunnelUnavailableError.status_code:
                raise TelegramTunnelUnavailableError() from None
            raise TelegramRegistrationFailedError() from None
        except SecretResolutionError:
            raise
        except Exception as error:
            # A bug, not a Telegram failure: let it surface as a 500. Logged by
            # type only, because a traceback with loguru's `diagnose` would
            # print the resolved bot token held in local variables.
            logger.error(
                "[TelegramTrigger] Unexpected error registering node {node_id}'s webhook: {error_type}",
                node_id=telegram_trigger_node.pk,
                error_type=type(error).__name__,
            )
            raise

        try:
            return self.get_webhook_status(telegram_trigger_node)
        except TelegramWebhookInfoUnavailableError:
            # `_fetch_webhook_info` already logged the error type and HTTP status.
            logger.info(
                "[TelegramTrigger] Node {node_id} registered; reporting setWebhook's "
                "confirmation because the follow-up read failed.",
                node_id=telegram_trigger_node.pk,
            )
            registered_url = telegram_trigger_node.webhook_trigger.auth.registered_webhook_url
            return TelegramWebhookStatus(
                registered_url=registered_url,
                expected_url=registered_url,
                is_match=True,
                pending_update_count=None,
                last_error_message=None,
                last_error_date=None,
                registration_blocker=None,
            )

    def _fetch_webhook_info(self, bot_api_key: str, node_id: int) -> dict:
        """Return Telegram's `getWebhookInfo` result after one short attempt.

        Raises:
            TelegramBotKeyRejectedError: Telegram answered 401 or 404 for the bot key.
            TelegramWebhookInfoUnavailableError: Telegram was unreachable, answered
                another non-2xx, or answered `ok: false`.
        """
        try:
            return self._send_telegram_request(
                method="GET",
                api_key=bot_api_key,
                endpoint="getWebhookInfo",
                timeout=WEBHOOK_INFO_CONNECT_READ_TIMEOUT_SECONDS,
            )["result"]
        except (requests.RequestException, TelegramApiError) as error:
            # Never log `error` itself: its message carries the bot-token URL.
            response = getattr(error, "response", None)
            status = response.status_code if response is not None else None
            logger.warning(
                "[TelegramTrigger] getWebhookInfo failed for node {node_id}: {error_type} (HTTP status {status})",
                node_id=node_id,
                error_type=type(error).__name__,
                status=status,
            )
            bot_key_rejected = (
                isinstance(error, HTTPError) and status in BOT_KEY_REJECTED_HTTP_STATUSES
            )
        if bot_key_rejected:
            raise TelegramBotKeyRejectedError() from None
        raise TelegramWebhookInfoUnavailableError() from None

    def _should_keep_recorded_registration(
        self, bot_api_key: str, node_id: int, webhook_url: str
    ) -> bool:
        """Return False only when Telegram confirms the bot key has no webhook at all.

        A different URL keeps the record: another trigger sharing the bot key
        holds it, and silently taking it back on every save would make the two
        nodes steal it from each other. The panel reports that conflict and
        `force=True` resolves it. A failed lookup also keeps it: when Telegram
        is unreachable, the retrying `setWebhook` would only add ~34 s to the
        save and then fail too.
        """
        try:
            webhook_info = self._fetch_webhook_info(bot_api_key, node_id)
        except (TelegramWebhookInfoUnavailableError, TelegramBotKeyRejectedError):
            # `_fetch_webhook_info` already logged the error type and HTTP status.
            logger.info(
                "[TelegramTrigger] Could not confirm node {node_id}'s webhook with "
                "Telegram; keeping the recorded registration.",
                node_id=node_id,
            )
            return True

        registered_url = webhook_info.get("url") or ""
        if not registered_url:
            logger.info(
                "[TelegramTrigger] Telegram has no webhook for node {node_id}'s bot key; "
                "re-registering.",
                node_id=node_id,
            )
            return False
        if not _is_same_callback_url(registered_url, webhook_url):
            logger.info(
                "[TelegramTrigger] Telegram holds a different webhook for node {node_id}'s "
                "bot key; keeping it, see panel.",
                node_id=node_id,
            )
        return True

    def _get_expected_callback_url(self, telegram_trigger_node: TelegramTriggerNode) -> str | None:
        webhook_trigger = telegram_trigger_node.webhook_trigger
        if webhook_trigger is None or webhook_trigger.provider_type in LOCAL_ONLY_PROVIDERS:
            return None
        tunnel_url = self.webhook_trigger_service.get_tunnel_url_for_trigger(webhook_trigger)
        if not tunnel_url:
            return None
        return build_telegram_callback_url(tunnel_url, webhook_trigger.path)
