import time

from loguru import logger

from django_app.settings import (
    REDIS_TUNNEL_CONFIG_CHANNEL,
    TUNNEL_URLS_HASH_KEY,
)
from tables.models.graph_models import GraphOrganization, WebhookTriggerNode
from tables.models.webhook_models import NgrokWebhookConfig, WebhookTrigger
from src.shared.models import WebhookConfigData
from tables.services.converter_service import ConverterService
from tables.services.redis_service import RedisService
from tables.services.session_manager_service import SessionManagerService
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
                provider, config_name = config_id.split(":", 1)
            else:
                provider, config_name = "ngrok", config_id

            if provider == "ngrok":
                filters["webhook_trigger__ngrok_webhook_config__name"] = config_name
            else:
                logger.warning(
                    f"Unknown tunnel provider '{provider}' for config '{config_name}'"
                )

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
                entrypoint=webhook_trigger_node.node_name,
            )

    def register_webhooks(self) -> bool:
        data = WebhookConfigData(
            ngrok_configs=[
                self.converter_service.convert_ngrok_webhook_config_to_pydantic(config)
                for config in NgrokWebhookConfig.objects.all()
            ]
        )

        redis_client = self.redis_service.redis_client
        delivered_n = redis_client.publish(
            channel=REDIS_TUNNEL_CONFIG_CHANNEL, message=data.model_dump_json()
        )
        return delivered_n > 0

    def get_tunnel_url(self, ngrok_webhook_config: NgrokWebhookConfig) -> str | None:
        """Read the tunnel URL written by the webhook service directly from Redis.

        Returns None if the tunnel has not established a connection yet.
        """
        unique_id = f"ngrok:{ngrok_webhook_config.name}"
        url = self.redis_service.redis_client.hget(TUNNEL_URLS_HASH_KEY, unique_id)
        if isinstance(url, bytes):
            url = url.decode("utf-8")
        return url

    def wait_for_tunnel_url(
        self,
        ngrok_webhook_config: NgrokWebhookConfig,
        timeout: float = 10.0,
        interval: float = 0.1,
    ) -> str | None:
        """Poll Redis until the tunnel URL is available or timeout is reached."""

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            url = self.get_tunnel_url(ngrok_webhook_config)
            if url:
                return url
            time.sleep(interval)
        return None
