import uuid
from typing import Protocol

from django.db import models
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.core.validators import RegexValidator
from django.contrib.auth.hashers import check_password

from tables.models.base_models import (
    DefaultBaseModel,
    SoftDeleteFields,
    soft_delete_consistency_constraint,
)
from tables.models.rbac_models.org_scoped import OrgScopedModel


class ProviderType(models.TextChoices):
    NGROK = "ngrok"
    LOCALHOST = "localhost"


# Providers that are only reachable locally and cannot be used by external
# services (e.g. Twilio) that call back into our webhooks. Single source of truth.
LOCAL_ONLY_PROVIDERS = {ProviderType.LOCALHOST}


class TunnelConfig(Protocol):
    def get_webhook_url(self) -> str | None: ...
    def get_redis_key(self) -> str: ...


class NgrokWebhookConfig(models.Model):
    class Region(models.TextChoices):
        US = ("us",)
        EU = ("eu",)
        AP = ("ap",)

    name = models.CharField(
        max_length=50,
    )

    auth_token_secret = models.ForeignKey(
        "Secret",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ngrok_webhook_configs",
    )

    domain = models.CharField(
        max_length=255, blank=True, null=True, help_text="Your domain"
    )

    region = models.CharField(max_length=2, choices=Region.choices, default=Region.EU)

    trigger = models.OneToOneField(
        "WebhookTrigger",
        related_name="ngrok",
        on_delete=models.CASCADE,
    )

    def get_webhook_url(self):
        if self.domain:
            return f"https://{self.domain}"
        return None

    def get_redis_key(self) -> str:
        return f"ngrok:{self.trigger.org_id}:{self.trigger.path}"


class LocalhostWebhookConfig(models.Model):
    name = models.CharField(max_length=50)
    domain = models.CharField(
        max_length=255, blank=True, null=True, help_text="Optional local domain or URL"
    )

    trigger = models.OneToOneField(
        "WebhookTrigger",
        related_name="localhost",
        on_delete=models.CASCADE,
    )

    def get_webhook_url(self):
        if self.domain:
            return f"http://{self.domain}"
        return None

    def get_redis_key(self) -> str:
        """Must stay byte-for-byte in sync with `BaseTunnelConfigData.unique_id`
        -- see `NgrokWebhookConfig.get_redis_key` docstring."""
        return f"localhost:{self.trigger.org_id}:{self.trigger.path}"

    def __str__(self):
        return self.name


class WebhookAuthScheme(models.TextChoices):
    STATIC_HEADER = "static_header"  # Telegram: literal header value compare
    HMAC_SHA256 = "hmac_sha256"  # Generic: signed body + one-sided timestamp
    # window + Redis-backed replay check (see `webhook_routes.handle_webhook`)


class WebhookNodeAuth(SoftDeleteFields):
    enabled = models.BooleanField(default=True)
    scheme = models.CharField(max_length=32, choices=WebhookAuthScheme.choices)

    header_name = models.CharField(max_length=128)
    timestamp_header_name = models.CharField(
        max_length=128, blank=True, default="X-Webhook-Timestamp"
    )

    tolerance_seconds = models.PositiveIntegerField(default=300)

    secret_hash = models.CharField(
        max_length=128,
        blank=True,
        null=True,
        help_text="One-way hash of the token. Never exposed.",
    )
    signing_secret = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Plaintext or symmetrically encrypted secret required to compute HMAC signatures.",
    )
    registered_webhook_url = models.CharField(
        max_length=500,
        null=True,
        blank=True,
        help_text=(
            "The full callback URL this credential's outbound setWebhook call "
            "(Telegram only) last targeted. Lets a resync detect a genuine "
            "tunnel URL change -- even one where the underlying WebhookTrigger "
            "row is unchanged (e.g. the tunnel's domain rotated) -- vs. an "
            "unrelated node resave, so ordinary resaves don't re-hit "
            "Telegram's setWebhook endpoint and rotate the secret needlessly."
        ),
    )
    registered_bot_api_key_secret_id = models.PositiveBigIntegerField(
        null=True,
        blank=True,
        help_text=(
            "The Secret id of the `telegram_bot_api_key` this credential's "
            "outbound setWebhook call (Telegram only) last targeted. Lets a "
            "resync detect the node being repointed at a different Telegram "
            "bot even when the URL/tunnel is unchanged, so the new bot still "
            "gets a real setWebhook call instead of being skipped as "
            "'already registered'."
        ),
    )

    telegram_trigger_node = models.OneToOneField(
        "TelegramTriggerNode",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="webhook_node_auth",
    )
    webhook_trigger_node = models.OneToOneField(
        "WebhookTriggerNode",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="webhook_node_auth",
    )

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "all_objects"
        constraints = [
            soft_delete_consistency_constraint(),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        telegram_trigger_node__isnull=False,
                        webhook_trigger_node__isnull=True,
                    )
                    | models.Q(
                        telegram_trigger_node__isnull=True,
                        webhook_trigger_node__isnull=False,
                    )
                ),
                name="webhook_node_auth_exactly_one_node",
            ),
        ]

    def verify_static_token(self, raw_token: str) -> bool:
        """Verifies an incoming token against the stored hash."""
        if not self.secret_hash:
            return False
        return check_password(raw_token, self.secret_hash)

    def __str__(self):
        node_id = self.telegram_trigger_node_id or self.webhook_trigger_node_id
        return f"WebhookNodeAuth({self.scheme}) for node {node_id}"


class WebhookTrigger(OrgScopedModel, models.Model):
    path = models.CharField(
        max_length=255,
        validators=[
            RegexValidator(
                regex=r"^[a-zA-Z0-9]{1}[a-zA-Z0-9-_]*$",
                message="Path may only contain letters, numbers, hyphens, and underscores, and must start with a letter or number.",
            )
        ],
    )
    provider_type = models.CharField(
        max_length=20,
        choices=ProviderType.choices,
        null=True,
        blank=True,
    )

    class Meta(OrgScopedModel.Meta):
        abstract = False
        unique_together = [
            ("org", "path", "provider_type"),
        ]

    def get_active_config(self) -> "TunnelConfig | None":
        if self.provider_type == ProviderType.NGROK:
            try:
                return self.ngrok
            except ObjectDoesNotExist:
                return None
        if self.provider_type == ProviderType.LOCALHOST:
            try:
                return self.localhost
            except ObjectDoesNotExist:
                return None
        return None

    def __str__(self):
        return self.path


# ---------------------------------------------------------------------------
# Generic communication channel models
# ---------------------------------------------------------------------------


class RealtimeChannel(OrgScopedModel, models.Model):
    """
    A named, typed communication channel linked to a RealtimeAgent.

    The `token` (UUID) uniquely identifies this channel and is used in
    webhook URLs (e.g. /voice/{token}/) so that incoming calls can be
    routed to the correct agent without enumeration risk.

    Designed to be extensible: add a new ChannelType and a corresponding
    detail model (e.g. WhatsAppChannel, TelegramChannel) following the
    same OneToOneField pattern as TwilioChannel.
    """

    class ChannelType(models.TextChoices):
        TWILIO = "twilio", "Twilio"
        # future: WHATSAPP = "whatsapp", "WhatsApp"
        # future: TELEGRAM = "telegram", "Telegram"

    class Meta(OrgScopedModel.Meta):
        abstract = False
        db_table = "realtime_channel"

    name = models.CharField(max_length=250)
    channel_type = models.CharField(
        max_length=50, choices=ChannelType.choices, default=ChannelType.TWILIO
    )
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    realtime_agent = models.ForeignKey(
        "RealtimeAgent",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="channels",
    )
    realtime_agent_definition = models.ForeignKey(
        "RealtimeAgentDefinition",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="channels",
    )
    is_active = models.BooleanField(default=True)

    def clean(self):
        # A channel answers to exactly one destination — either a staff
        # RealtimeAgent or a RealtimeAgentDefinition — never both.
        if (
            self.realtime_agent_id is not None
            and self.realtime_agent_definition_id is not None
        ):
            raise ValidationError(
                "A RealtimeChannel may have at most one destination set "
                "(realtime_agent or realtime_agent_definition)."
            )

    def __str__(self):
        return f"{self.name} ({self.channel_type})"

    @property
    def webhook_token(self) -> str:
        return str(self.token)


class TwilioChannel(models.Model):
    """
    Twilio-specific settings for a RealtimeChannel.

    One TwilioChannel per RealtimeChannel (OneToOneField).
    The Twilio webhook URL should be configured as:
        POST  /voice/{channel.token}/
        WS    /voice/{channel.token}/stream

    Org scoping lives on the parent `RealtimeChannel` (`channel`), not here
    — `channel` is a mandatory, non-nullable OneToOneField (it IS this
    model's PK), so org visibility is always reachable transitively via
    `channel__org_id` with no risk of hiding rows behind a missing detail
    row (unlike the reverse direction, RealtimeChannel -> TwilioChannel).
    """

    class Meta:
        db_table = "twilio_channel"

    channel = models.OneToOneField(
        RealtimeChannel,
        on_delete=models.CASCADE,
        related_name="twilio",
        primary_key=True,
    )
    account_sid = models.CharField(max_length=255)
    auth_token_secret = models.ForeignKey(
        "Secret",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="twilio_channels",
    )
    phone_number = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        unique=True,
        help_text="E.164 format, e.g. +15551234567",
    )
    webhook_trigger = models.ForeignKey(
        "WebhookTrigger",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="twilio_channels",
    )

    def __str__(self):
        return f"Twilio/{self.phone_number or self.account_sid}"

    def validate_provider(self) -> str | None:
        """Validate that the configured webhook provider is reachable by Twilio.

        Returns an error message string if the provider is not usable, or None
        if the configuration is valid.
        """
        webhook_trigger = self.webhook_trigger
        if not webhook_trigger or not webhook_trigger.provider_type:
            return "No webhook trigger configured for this channel"
        if webhook_trigger.provider_type in LOCAL_ONLY_PROVIDERS:
            return (
                "Localhost webhook provider is not reachable by Twilio. "
                "Use ngrok or a publicly accessible provider."
            )
        return None
