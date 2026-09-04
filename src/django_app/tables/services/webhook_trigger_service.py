import time

from loguru import logger

from django_app.settings import (
    REDIS_TUNNEL_CONFIG_CHANNEL,
    TUNNEL_URLS_HASH_KEY,
)
from tables.models.graph_models import WebhookTriggerNode
from tables.models.secret_models import Secret
from tables.models.webhook_models import (
    LOCAL_ONLY_PROVIDERS,
    LocalhostWebhookConfig,
    NgrokWebhookConfig,
    ProviderType,
    TunnelConfig,
    WebhookTrigger,
    WebhookTriggerAuth,
    WebhookTriggerAuthKind,
)
from src.shared.models import WebhookConfigData
from tables.services.converter_service import ConverterService
from tables.services.redis_service import RedisService
from tables.services.secrets import secret_resolver, SecretResolutionError
from tables.services.session_manager_service import SessionManagerService
from tables.services.trigger_spec import TriggerSpec
from tables.validators.telegram_secret_token_validator import (
    validate_telegram_secret_token,
)
from utils.singleton_meta import SingletonMeta

USER_SETTABLE_AUTH_KINDS = (
    WebhookTriggerAuthKind.WEBHOOK,
    WebhookTriggerAuthKind.TELEGRAM,
    WebhookTriggerAuthKind.TWILIO,
)

AUTH_SECRET_MIN_LENGTH = 32


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
        ngrok_configs, localhost_configs = [], []
        for config in NgrokWebhookConfig.objects.select_related(
            "trigger", "trigger__auth", "trigger__auth__secret"
        ).all():
            try:
                ngrok_configs.append(
                    self.converter_service.convert_ngrok_webhook_config_to_pydantic(
                        config
                    )
                )
            except SecretResolutionError as e:
                logger.error(f"Error converting Ngrok webhook config: {e}")

        for config in LocalhostWebhookConfig.objects.select_related(
            "trigger", "trigger__auth", "trigger__auth__secret"
        ).all():
            try:
                localhost_configs.append(
                    self.converter_service.convert_localhost_webhook_config_to_pydantic(
                        config
                    )
                )
            except SecretResolutionError as e:
                logger.error(f"Error converting Localhost webhook config: {e}")
            
        data = WebhookConfigData(
            ngrok_configs=ngrok_configs,
            localhost_configs=localhost_configs,
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

    def set_trigger_auth_secret(
        self,
        trigger: WebhookTrigger,
        secret: Secret | None,
        kind: str = WebhookTriggerAuthKind.WEBHOOK,
    ) -> WebhookTriggerAuth:
        """Create/update this trigger's user-settable auth strategy --
        `kind=webhook` (`EPICSTAFF_API_KEY`), `kind=telegram`
        (`X-Telegram-Bot-Api-Secret-Token`), or `kind=twilio`.
        """
        if kind not in USER_SETTABLE_AUTH_KINDS:
            raise ValueError(
                f"kind='{kind}' auth is not user-settable via this endpoint."
            )

        if (
            kind in (WebhookTriggerAuthKind.TELEGRAM, WebhookTriggerAuthKind.TWILIO)
            and trigger.provider_type in LOCAL_ONLY_PROVIDERS
        ):
            provider_name = (
                "Telegram" if kind == WebhookTriggerAuthKind.TELEGRAM else "Twilio"
            )
            raise ValueError(
                f"Localhost webhook provider is not reachable by {provider_name}. "
                "Use ngrok or a publicly accessible provider."
            )

        if (
            kind == WebhookTriggerAuthKind.WEBHOOK
            and trigger.telegram_trigger_nodes.exists()
        ):
            raise ValueError(
                "This trigger is attached to a Telegram trigger node and "
                "cannot use kind='webhook' auth; use kind='telegram' instead."
            )
        if (
            kind == WebhookTriggerAuthKind.TELEGRAM
            and trigger.webhook_trigger_nodes.exists()
        ):
            raise ValueError(
                "This trigger is attached to a webhook trigger node and "
                "cannot use kind='telegram' auth; use kind='webhook' instead."
            )
        if kind == WebhookTriggerAuthKind.TWILIO and (
            trigger.webhook_trigger_nodes.exists()
            or trigger.telegram_trigger_nodes.exists()
        ):
            raise ValueError(
                "This trigger already has a webhook or Telegram trigger node "
                "attached and cannot be reserved for kind='twilio' auth."
            )
        if kind == WebhookTriggerAuthKind.TWILIO and secret is not None:
            raise ValueError(
                "kind='twilio' is a bare reservation and does not accept a "
                "secret directly; it is filled in once a TwilioChannel "
                "claims this trigger."
            )

        existing = getattr(trigger, "auth", None)
        if existing is not None and existing.kind != kind:
            raise ValueError(
                "This webhook trigger's auth is already configured for "
                f"kind='{existing.kind}' and cannot be overwritten with a "
                f"kind='{kind}' secret."
            )

        if secret is not None:
            plaintext = secret_resolver.resolve(
                secret_id=secret.pk,
                org_id=trigger.org_id,
                context="Plaintext secret for webhook trigger auth",
            )
            if len(plaintext) < AUTH_SECRET_MIN_LENGTH:
                raise ValueError(
                    f"The provided secret must be at least {AUTH_SECRET_MIN_LENGTH} characters long."
                )

            if kind == WebhookTriggerAuthKind.TELEGRAM:
                validate_telegram_secret_token(plaintext)

        auth, _ = WebhookTriggerAuth.objects.update_or_create(
            trigger=trigger,
            defaults={
                "kind": kind,
                "secret": secret,
            },
        )
        trigger._state.fields_cache.pop("auth", None)
        return auth
