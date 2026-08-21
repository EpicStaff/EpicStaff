import time
import secrets

from django.db.models import Q
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
    WebhookNodeAuth,
    WebhookAuthScheme,
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

    def get_trigger_filters(
        self, path: str, config_id: str | None = None
    ) -> dict | None:
        """Build ORM filter kwargs for `WebhookTriggerNode`.

        `config_id` is resolved by the `webhook` service purely from the
        request's path (`TunnelRegistry.resolve_by_path`) -- the Host header
        is no longer used for routing anywhere in this flow, since it is
        spoofable. `config_id` has the shape
        `"<provider>:<org_id>:<registered_path>"` (== `BaseTunnelConfigData.
        unique_id`, src/shared/models/ai_providers.py); the segment after the
        provider is the numeric id of the org that owns the `WebhookTrigger`
        the tunnel was registered for, and the final segment is that
        trigger's `path` — NOT an arbitrary config-name label.

        Returns `None` (no dispatch) when:
          - `config_id` identifies a specific tunnel whose registered path
            does NOT match the requested `path`, or
          - `config_id` carries a colon (i.e. it claims to identify a
            specific resolved tunnel, as opposed to being entirely absent)
            but its provider segment is unrecognized, missing the org
            segment (stale/malformed 2-part shape), or has an org segment
            that isn't a parseable int. This fails CLOSED rather than
            falling back to an org-unscoped filter: an org-collision on
            `path` must never resolve into an unrestricted, cross-org
            fan-out -- including for a provider this code doesn't yet know
            about, which is exactly the kind of value that must never be
            trusted to skip org scoping.

        The one case that intentionally stays org-unscoped is `config_id`
        being falsy or containing no colon at all -- the documented legacy
        backward-compat shape meaning "no tunnel has been resolved for this
        request" (see `handle_webhook_trigger`/`handle_telegram_trigger`
        docstrings: `None` preserves today's unrestricted fan-out).
        """
        filters = {"webhook_trigger__path": path}

        if not config_id or ":" not in config_id:
            return filters

        parts = config_id.split(":", 2)
        provider = parts[0]
        if provider not in (ProviderType.NGROK, ProviderType.LOCALHOST):
            logger.error(
                f"Unknown tunnel provider '{provider}' for config '{config_id}' "
                "-- rejecting for org-scoping safety rather than falling back "
                "to an unscoped path-only match."
            )
            return None

        if len(parts) != 3:
            logger.error(
                f"config_id '{config_id}' is missing the org segment "
                "(expected '<provider>:<org_id>:<path>') -- rejecting for "
                "org-scoping safety."
            )
            return None

        _, org_id_str, registered_path = parts
        if registered_path != path:
            return None

        try:
            org_id = int(org_id_str)
        except ValueError:
            logger.error(
                f"Unparseable org segment in config_id '{config_id}' -- rejecting."
            )
            return None

        filters["webhook_trigger__provider_type"] = provider
        filters["webhook_trigger__org_id"] = org_id

        return filters

    def handle_webhook_trigger(
        self,
        path: str,
        payload: dict,
        config_id: str | None = None,
        node_id: int | None = None,
        unauthenticated_only: bool = False,
    ) -> None:
        """`node_id`, when set, restricts dispatch to that single node --
        used by `RedisPubSub.webhook_events_handler` when the inbound
        request matched a credential scoped to one specific node (see
        `WebhookEventData.auth_principal`). 
        """
        filters = self.get_trigger_filters(path, config_id)
        if filters is None:
            return
        if node_id is not None:
            filters["id"] = node_id

        webhook_trigger_node_list = WebhookTriggerNode.objects.filter(**filters)
        if unauthenticated_only:
            webhook_trigger_node_list = webhook_trigger_node_list.filter(
                Q(webhook_node_auth__isnull=True)
                | Q(webhook_node_auth__enabled=False)
            )

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
                for config in NgrokWebhookConfig.objects.select_related("trigger")
                .prefetch_related(
                    "trigger__telegram_trigger_nodes__webhook_node_auth",
                    "trigger__webhook_trigger_nodes__webhook_node_auth",
                )
                .all()
            ],
            localhost_configs=[
                self.converter_service.convert_localhost_webhook_config_to_pydantic(
                    config
                )
                for config in LocalhostWebhookConfig.objects.select_related("trigger")
                .prefetch_related(
                    "trigger__telegram_trigger_nodes__webhook_node_auth",
                    "trigger__webhook_trigger_nodes__webhook_node_auth",
                )
                .all()
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

    def ensure_webhook_auth(
        self, webhook_trigger_node: WebhookTriggerNode, enabled: bool = True
    ) -> WebhookNodeAuth:
        """Idempotently ensures a `WebhookNodeAuth` row exists for this node.

        - Row missing: created with the given `enabled` state and a fresh
          `signing_secret`.
        - Row exists: the `signing_secret` is preserved (only backfilled if
          somehow empty); `enabled` is only ever flipped True->stays/False->True
          here -- this method never disables an existing row (that's
          `disable_webhook_auth`'s job) so re-enabling never rotates the
          secret an external caller may already have configured.
        """
        raw_secret = secrets.token_hex(32)

        node_auth, created = WebhookNodeAuth.objects.get_or_create(
            webhook_trigger_node=webhook_trigger_node,
            defaults={
                "enabled": enabled,
                "scheme": WebhookAuthScheme.HMAC_SHA256,
                "header_name": "X-Webhook-Signature",
                "timestamp_header_name": "X-Webhook-Timestamp",
                "signing_secret": raw_secret,
            },
        )

        update_fields = []
        if not created and not node_auth.signing_secret:
            node_auth.signing_secret = raw_secret
            update_fields.append("signing_secret")
        if not created and enabled and not node_auth.enabled:
            node_auth.enabled = True
            update_fields.append("enabled")
        if update_fields:
            node_auth.save(update_fields=update_fields)

        return node_auth

    def disable_webhook_auth(
        self, webhook_trigger_node: WebhookTriggerNode
    ) -> WebhookNodeAuth | None:
        """Soft-disable: flips `enabled=False` on the existing row without
        deleting it, so a later re-enable (`ensure_webhook_auth`) reuses the
        same `signing_secret` instead of forcing external callers to
        reconfigure their signature verification. Returns `None` when no row
        exists yet -- nothing to disable.
        """
        node_auth = WebhookNodeAuth.objects.filter(
            webhook_trigger_node=webhook_trigger_node
        ).first()
        if node_auth is None:
            return None
        if node_auth.enabled:
            node_auth.enabled = False
            node_auth.save(update_fields=["enabled"])
        return node_auth

    def sync_webhook_auth(
        self, webhook_trigger_node: WebhookTriggerNode, enabled: bool
    ) -> WebhookNodeAuth | None:
        """Single entry point for the client-controlled `{"enabled": bool}`
        toggle on `WebhookTriggerNodeSerializer.webhook_node_auth`."""
        if enabled:
            return self.ensure_webhook_auth(webhook_trigger_node, enabled=True)
        return self.disable_webhook_auth(webhook_trigger_node)
