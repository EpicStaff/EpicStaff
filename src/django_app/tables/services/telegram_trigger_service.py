import requests
from loguru import logger
from requests.exceptions import ConnectionError, Timeout
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from tables.exceptions import RegisterTelegramTriggerError
from tables.models.graph_models import TelegramTriggerNode
from tables.models.webhook_models import WebhookTrigger
from tables.services.session_manager_service import SessionManagerService
from tables.services.webhook_trigger_service import WebhookTriggerService
from utils.graph_utils import generate_node_name
from utils.singleton_meta import SingletonMeta


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

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((ConnectionError, Timeout)),
        reraise=True,
    )
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

    def register_telegram_trigger(self, telegram_trigger_instance: TelegramTriggerNode):
        # TODO: update this to extend to other tunnels
        webhook_trigger: WebhookTrigger = telegram_trigger_instance.webhook_trigger
        if webhook_trigger.ngrok_webhook_config is None:
            raise RegisterTelegramTriggerError(
                f"Webhook trigger does not set", status_code=400
            )
        try:
            webhook_tunnel_url = self.webhook_trigger_service.get_tunnel_url(
                ngrok_webhook_config=webhook_trigger.ngrok_webhook_config
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

        telegram_webhook_url = (
            f"{webhook_tunnel_url}/webhooks/telegram-trigger/{webhook_trigger.path}/"
        )

        try:
            return self._call_telegram_api(
                method="POST",
                api_key=telegram_trigger_instance.telegram_bot_api_key,
                endpoint="setWebhook",
                params={"url": telegram_webhook_url},
            )
        except Exception as e:
            raise RegisterTelegramTriggerError(
                f"Failed to register Telegram webhook after retries: {str(e)}"
            )

    def unregister_telegram_trigger(self, telegram_bot_api_key: str):
        try:
            return self._call_telegram_api(
                method="POST", api_key=telegram_bot_api_key, endpoint="deleteWebhook"
            )
        except Exception:
            return {"ok": False, "description": "Unregistration failed"}

    def handle_telegram_trigger(
        self, url_path: str, payload: dict, config_id: str | None = None
    ) -> None:
        filters = self.webhook_trigger_service.get_trigger_filters(
            path=url_path, config_id=config_id
        )

        telegram_trigger_node_list = TelegramTriggerNode.objects.filter(**filters)

        for telegram_trigger_node in telegram_trigger_node_list:
            self.session_manager_service.run_session(
                graph_id=telegram_trigger_node.graph.pk,
                variables={"telegram_payload": payload},
                entrypoint=generate_node_name(
                    telegram_trigger_node.id, telegram_trigger_node.node_name
                ),
            )

    def get_trigger_info(self, telegram_bot_api_key: str):
        try:
            return self._call_telegram_api(
                method="GET", api_key=telegram_bot_api_key, endpoint="getWebhookInfo"
            )
        except Exception:
            return None
