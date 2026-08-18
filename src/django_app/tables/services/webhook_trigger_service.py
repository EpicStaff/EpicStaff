import time

from loguru import logger

from django_app.settings import (
    REDIS_TUNNEL_CONFIG_CHANNEL,
    TUNNEL_URLS_HASH_KEY,
)
from tables.models.graph_models import WebhookTriggerNode
from tables.models.webhook_models import (
    LocalhostWebhookConfig,
    NgrokWebhookConfig,
    ProviderType,
    TunnelConfig,
    WebhookTrigger,
)
from src.shared.models import WebhookConfigData
from tables.services.converter_service import ConverterService
from tables.services.redis_service import RedisService
from tables.services.session_manager_service import SessionManagerService
from tables.services.trigger_spec import TriggerSpec
from utils.singleton_meta import SingletonMeta


class WebhookTriggerService(metaclass=SingletonMeta):
    def __init__(
        self,
        session_manager_service: SessionManagerService,
        redis_service: RedisService,
        converter_service: ConverterService,
    ):
        self.converter_service = converter_service
        self.redis_service = redis_service
        self.session_manager_service = session_manager_service

    def get_trigger_filters(self, path: str, config_id: str | None = None) -> dict | None:
        """Build ORM filter kwargs for `WebhookTriggerNode`.

        `config_id` is resolved by the `webhook` service from the request's
        actual Host/domain and has the shape `"<provider>:<registered_path>"`. 
        The segment after the provider is NOT an arbitrary config-name 
        label — it is the `path` of the `WebhookTrigger` that was registered 
        for that specific domain/tunnel at connect time.
        Returns `None` when `config_id` identifies a specific tunnel/domain
        whose registered path does NOT match the requested `path`.
        """
        filters = {"webhook_trigger__path": path}

        if not config_id or ":" not in config_id:
            return filters

        provider, registered_path = config_id.split(":", 1)
        if provider not in (ProviderType.NGROK, ProviderType.LOCALHOST):
            logger.warning(
                f"Unknown tunnel provider '{provider}' for config '{config_id}'"
            )
            return filters

        if registered_path != path:
            return None

        filters["webhook_trigger__provider_type"] = provider

        return filters

    def handle_webhook_trigger(
        self, path: str, payload: dict, config_id: str | None = None
    ) -> None:
        filters = self.get_trigger_filters(path, config_id)
        if filters is None:
            return

        webhook_trigger_node_list = WebhookTriggerNode.objects.filter(**filters)

        for webhook_trigger_node in webhook_trigger_node_list:
            # Persistent-variable merging is owned by run_session.
            self.session_manager_service.run_session(
                graph_id=webhook_trigger_node.graph.pk,
                variables={"trigger_payload": payload},
                trigger=TriggerSpec.webhook(webhook_trigger_node, path, config_id),
            )

    def register_webhooks(self) -> bool:
        data = WebhookConfigData(
            ngrok_configs=[
                self.converter_service.convert_ngrok_webhook_config_to_pydantic(config)
                for config in NgrokWebhookConfig.objects.select_related("trigger").all()
            ],
            localhost_configs=[
                self.converter_service.convert_localhost_webhook_config_to_pydantic(
                    config
                )
                for config in LocalhostWebhookConfig.objects.select_related(
                    "trigger"
                ).all()
            ],
        )

        redis_client = self.redis_service.redis_client
        delivered_n = redis_client.publish(
            channel=REDIS_TUNNEL_CONFIG_CHANNEL, message=data.model_dump_json()
        )
        return delivered_n > 0

    def _get_tunnel_url(self, config: "TunnelConfig") -> str | None:
        """Read the tunnel URL written by the webhook service directly from Redis."""
        unique_id = config.get_redis_key()
        url = self.redis_service.redis_client.hget(TUNNEL_URLS_HASH_KEY, unique_id)
        if isinstance(url, bytes):
            url = url.decode("utf-8")
        return url

    def get_tunnel_url(self, webhook_trigger: "WebhookTrigger") -> str | None:
        return self._get_tunnel_url(webhook_trigger.ngrok)

    def get_localhost_tunnel_url(self, webhook_trigger: "WebhookTrigger") -> str | None:
        return self._get_tunnel_url(webhook_trigger.localhost)

    def get_tunnel_url_for_trigger(
        self, webhook_trigger: "WebhookTrigger"
    ) -> str | None:
        """Provider-agnostic: resolves the active config via get_active_config()."""
        config = webhook_trigger.get_active_config()
        if config is None:
            return None
        return self._get_tunnel_url(config)

    def wait_for_tunnel_url(
        self,
        webhook_trigger: "WebhookTrigger",
        timeout: float = 10.0,
        interval: float = 0.1,
    ) -> str | None:
        """Poll Redis until the ngrok tunnel URL is available or timeout is reached."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            url = self.get_tunnel_url(webhook_trigger)
            if url:
                return url
            time.sleep(interval)
        return None

    def wait_for_localhost_tunnel_url(
        self,
        webhook_trigger: "WebhookTrigger",
        timeout: float = 3.0,
        interval: float = 0.1,
    ) -> str | None:
        """Poll Redis until the localhost tunnel URL is available or timeout is reached."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            url = self.get_localhost_tunnel_url(webhook_trigger)
            if url:
                return url
            time.sleep(interval)
        return None

    def wait_for_tunnel_url_for_trigger(
        self,
        webhook_trigger: "WebhookTrigger",
        timeout: float = 10.0,
        interval: float = 0.1,
    ) -> str | None:
        """Provider-agnostic polling counterpart to `get_tunnel_url_for_trigger`.

        Attaching/detaching a `TelegramTriggerNode` triggers a tunnel-config
        resync (`telegram_signals._resync_tunnel_registration`), which forces
        the `webhook` service to reconnect and re-publish its URL to Redis --
        not instantaneous. `TelegramTriggerService.register_telegram_trigger`
        uses this instead of a single `get_tunnel_url_for_trigger` read so it
        doesn't race that resync.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            url = self.get_tunnel_url_for_trigger(webhook_trigger)
            if url:
                return url
            time.sleep(interval)
        return None
