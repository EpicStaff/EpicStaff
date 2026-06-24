import time

from loguru import logger

from django_app.settings import (
    REDIS_TUNNEL_CONFIG_CHANNEL,
    TUNNEL_URLS_HASH_KEY,
)
from tables.models.graph_models import GraphOrganization, WebhookTriggerNode
from tables.models.webhook_models import (
    LocalhostWebhookConfig,
    NgrokWebhookConfig,
    TunnelConfig,
    WebhookTrigger,
)
from src.shared.models import WebhookConfigData
from tables.services.converter_service import ConverterService
from tables.services.redis_service import RedisService
from tables.services.session_manager_service import SessionManagerService
from utils.graph_utils import generate_node_name
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

    def get_trigger_filters(self, path: str, config_id: str | None = None) -> dict:
        filters = {"webhook_trigger__path": path}

        if config_id:
            if ":" in config_id:
                provider, trigger_path = config_id.split(":", 1)
                if provider in ("ngrok", "localhost"):
                    filters["webhook_trigger__path"] = trigger_path
                    filters["webhook_trigger__provider_type"] = provider
                else:
                    logger.warning(
                        f"Unknown tunnel provider '{provider}' for config '{config_id}'"
                    )
            else:
                # No provider prefix — filter by path only, accept any provider
                filters["webhook_trigger__path"] = config_id

        return filters

    def handle_webhook_trigger(
        self, path: str, payload: dict, config_id: str | None = None
    ) -> None:
        filters = self.get_trigger_filters(path, config_id)

        webhook_trigger_node_list = WebhookTriggerNode.objects.filter(**filters)

        for webhook_trigger_node in webhook_trigger_node_list:
            graph_organization = GraphOrganization.objects.filter(
                graph=webhook_trigger_node.graph
            ).first()
            variables: dict = {"trigger_payload": payload}
            if graph_organization:
                variables.update(graph_organization.persistent_variables)

            self.session_manager_service.run_session(
                graph_id=webhook_trigger_node.graph.pk,
                variables=variables,
                entrypoint=generate_node_name(
                    webhook_trigger_node.id, webhook_trigger_node.node_name
                ),
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
