import functools
import time

import requests
from loguru import logger
from requests.exceptions import ConnectionError, Timeout

from tables.exceptions import RegisterTelegramTriggerError
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


TELEGRAM_WEBHOOK_HEADER = WebhookTriggerAuth.HEADER_NAMES[
    WebhookTriggerAuthKind.TELEGRAM
]


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


class TelegramTriggerService(metaclass=SingletonMeta):
    def __init__(
        self,
        session_manager_service: SessionManagerService,
        webhook_trigger_service: WebhookTriggerService,
    ):
        self.webhook_trigger_service = webhook_trigger_service
        self.session_manager_service = (
            session_manager_service or SessionManagerService()
        )

    @_retry_on_connection_errors
    def _call_telegram_api(
        self, method: str, api_key: str, endpoint: str, params: dict = None
    ):
        """Handle Telegram API calls with retries."""
        url = f"https://api.telegram.org/bot{api_key}/{endpoint}"
        response = requests.request(method, url, params=params, timeout=10)

        response.raise_for_status()
        data = response.json()

        if not data.get("ok"):
            raise ValueError(f"Telegram API error: {data.get('description')}")

        return data

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
            webhook_tunnel_url = (
                self.webhook_trigger_service.wait_for_tunnel_url_for_trigger(
                    webhook_trigger
                )
            )
        except Exception as e:
            raise RegisterTelegramTriggerError(
                f"Failed to fetch tunnel URL: {str(e)}", status_code=503
            )

        if not webhook_tunnel_url:
            raise RegisterTelegramTriggerError(
                "Tunnel URL is not yet available, try again once the tunnel is established.",
                status_code=503,
            )

        telegram_webhook_url = f"{webhook_tunnel_url}/webhooks/{webhook_trigger.path}/"

        trigger_auth: WebhookTriggerAuth | None = getattr(webhook_trigger, "auth", None)
        if (
            trigger_auth is not None
            and trigger_auth.kind != WebhookTriggerAuthKind.TELEGRAM
        ):
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
            raise RegisterTelegramTriggerError(str(e), status_code=400)

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

        try:
            result = self._call_telegram_api(
                method="POST",
                api_key=secret_resolver.resolve(
                    # webhook_trigger is confirmed non-None above (return-early
                    # guard); it carries the same org as the node's graph and is
                    # available here without requiring a saved/loaded graph.
                    secret_id=telegram_trigger_instance.telegram_bot_api_key_secret_id,
                    org_id=webhook_trigger.org_id,
                    context="TelegramTriggerNode.telegram_bot_api_key",
                ),
                endpoint="setWebhook",
                params={
                    "url": telegram_webhook_url,
                    "secret_token": secret_token,
                },
            )
        except Exception as e:
            raise RegisterTelegramTriggerError(
                f"Failed to register Telegram webhook after retries: {str(e)}"
            )

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
        filters = self.webhook_trigger_service.get_trigger_filters(
            path=path, config_id=config_id
        )
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

    def get_trigger_info(self, telegram_bot_api_key: str):
        try:
            return self._call_telegram_api(
                method="GET", api_key=telegram_bot_api_key, endpoint="getWebhookInfo"
            )
        except Exception:
            return None
