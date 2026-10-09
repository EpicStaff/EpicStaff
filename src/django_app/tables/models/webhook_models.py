import uuid
from typing import ClassVar, Protocol

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.core.validators import RegexValidator
from django.db import models
from rbac.models.org_scoped import OrgScopedModel

from tables.models.base_models import (
    ActiveManager,
    DeletedManager,
    EnabledToggleFields,
    EnabledToggleManager,
    SoftDeleteFields,
    SoftDeleteMixin,
    soft_delete_consistency_constraint,
)


class ProviderType(models.TextChoices):
    NGROK = "ngrok"
    LOCALHOST = "localhost"


# Providers that are only reachable locally and cannot be used by external
# services (e.g. Twilio) that call back into our webhooks. Single source of truth.
LOCAL_ONLY_PROVIDERS = {ProviderType.LOCALHOST}


class TunnelConfig(Protocol):
    def get_webhook_url(self) -> str | None: ...
    def get_redis_key(self) -> str: ...


class NgrokWebhookConfig(SoftDeleteFields):
    """A trigger's ngrok tunnel. Binned with its trigger: register_webhooks() reads
    `objects`, so the tunnel closes while the trigger is in the recycle bin."""

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

    domain = models.CharField(max_length=255, blank=True, null=True, help_text="Your domain")

    region = models.CharField(max_length=2, choices=Region.choices, default=Region.EU)

    trigger = models.OneToOneField(
        "WebhookTrigger",
        related_name="ngrok",
        on_delete=models.CASCADE,
    )

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "all_objects"
        constraints = [soft_delete_consistency_constraint()]

    def get_webhook_url(self):
        if self.domain:
            return f"https://{self.domain}"
        return None

    def get_redis_key(self) -> str:
        return f"ngrok:{self.trigger.org_id}:{self.trigger.path}"


class LocalhostWebhookConfig(SoftDeleteFields):
    """A trigger's localhost tunnel; binned with its trigger, like NgrokWebhookConfig."""

    name = models.CharField(max_length=50)
    domain = models.CharField(
        max_length=255, blank=True, null=True, help_text="Optional local domain or URL"
    )

    trigger = models.OneToOneField(
        "WebhookTrigger",
        related_name="localhost",
        on_delete=models.CASCADE,
    )

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "all_objects"
        constraints = [soft_delete_consistency_constraint()]

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


class WebhookTriggerAuthKind(models.TextChoices):
    WEBHOOK = "webhook"  # EPICSTAFF_API_KEY header, user-settable secret
    TELEGRAM = "telegram"  # X-Telegram-Bot-Api-Secret-Token, user-settable secret
    TWILIO = "twilio"


class WebhookTriggerAuth(SoftDeleteFields):
    HEADER_NAMES = {
        WebhookTriggerAuthKind.WEBHOOK: "EPICSTAFF_API_KEY",
        WebhookTriggerAuthKind.TELEGRAM: "X-Telegram-Bot-Api-Secret-Token",
    }

    trigger = models.OneToOneField(
        "WebhookTrigger",
        on_delete=models.CASCADE,
        related_name="auth",
    )
    kind = models.CharField(max_length=16, choices=WebhookTriggerAuthKind.choices)
    secret = models.ForeignKey(
        "Secret",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="webhook_trigger_auths",
    )
    registered_webhook_url = models.CharField(max_length=500, null=True, blank=True)
    registered_bot_api_key_secret_id = models.PositiveBigIntegerField(null=True, blank=True)
    registered_secret_id = models.PositiveBigIntegerField(
        null=True,
        blank=True,
        help_text=(
            "The `secret_id` this credential's outbound setWebhook call "
            "(Telegram only) last targeted. The user can change `secret` at "
            "any time via the trigger API -- comparing against this lets a "
            "resync detect that change and re-push to Telegram, even when "
            "the URL and bot key are both unchanged."
        ),
    )

    @property
    def header_name(self) -> str | None:
        """`None` for `kind=twilio` -- that strategy has no `src/webhook`
        header check (see `WebhookTriggerAuthKind.TWILIO`)."""
        return self.HEADER_NAMES.get(self.kind)

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "all_objects"
        constraints = [soft_delete_consistency_constraint()]

    def __str__(self):
        return f"WebhookTriggerAuth({self.kind}) for trigger {self.trigger_id}"


class WebhookTrigger(OrgScopedModel, SoftDeleteMixin, models.Model):
    """A public webhook endpoint. `path` is the routing key, unique among live
    triggers across all organizations. In the recycle bin its tunnel and auth are
    binned with it, and flow nodes and Twilio channels keep their link to it
    (soft_delete_keeps_references) so a restore reconnects them.
    """

    soft_delete_keeps_references: ClassVar[bool] = True

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
        default_manager_name = "objects"
        base_manager_name = "all_objects"
        constraints = [
            soft_delete_consistency_constraint(),
            models.UniqueConstraint(
                fields=["path"], condition=models.Q(active=True), name="unique_live_webhook_path"
            ),
        ]

    def get_active_config(self) -> "TunnelConfig | None":
        # The reverse one-to-one accessors read binned configs too.
        if not self.active:
            return None
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


class RealtimeChannel(OrgScopedModel, EnabledToggleFields, SoftDeleteMixin, models.Model):
    """
    A named, typed communication channel linked to a RealtimeAgent.

    The `token` (UUID) uniquely identifies this channel and is used in
    webhook URLs (e.g. /voice/{token}/) so that incoming calls can be
    routed to the correct agent without enumeration risk.

    Designed to be extensible: add a new ChannelType and a corresponding
    detail model (e.g. WhatsAppChannel, TelegramChannel) following the
    same OneToOneField pattern as TwilioChannel.

    `is_enabled` (and the `objects`/`enabled_objects` manager split) comes
    from EnabledToggleFields -- see its docstring for why this is not
    SoftDeleteFields.

    It's also a recycle-bin root, with its Twilio settings binned alongside.
    `objects` hides channels in the bin but keeps disabled ones, so an
    operator still sees and re-enables them; `enabled_objects` hides both.
    Rows that use the channel keep their link while it's binned
    (soft_delete_keeps_references).
    """

    soft_delete_keeps_references: ClassVar[bool] = True

    objects = ActiveManager()
    deleted_objects = DeletedManager()
    all_objects = models.Manager()
    enabled_objects = EnabledToggleManager()

    class ChannelType(models.TextChoices):
        TWILIO = "twilio", "Twilio"
        # future: WHATSAPP = "whatsapp", "WhatsApp"
        # future: TELEGRAM = "telegram", "Telegram"

    class Meta(OrgScopedModel.Meta):
        abstract = False
        db_table = "realtime_channel"
        default_manager_name = "objects"
        base_manager_name = "all_objects"
        constraints = [soft_delete_consistency_constraint()]

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

    def clean(self):
        # A channel answers to exactly one destination — either a staff
        # RealtimeAgent or a RealtimeAgentDefinition — never both.
        if self.realtime_agent_id is not None and self.realtime_agent_definition_id is not None:
            raise ValidationError(
                "A RealtimeChannel may have at most one destination set "
                "(realtime_agent or realtime_agent_definition)."
            )

    def __str__(self):
        return f"{self.name} ({self.channel_type})"

    @property
    def webhook_token(self) -> str:
        return str(self.token)


class TwilioChannel(SoftDeleteFields):
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

    Binned and restored with its channel. The phone number is unique among
    live rows only, so a restore can find it taken (see restore_hooks).
    """

    class Meta:
        db_table = "twilio_channel"
        default_manager_name = "objects"
        base_manager_name = "all_objects"
        constraints = [
            soft_delete_consistency_constraint(),
            models.UniqueConstraint(
                fields=["phone_number"],
                condition=models.Q(active=True),
                name="unique_live_twilio_phone_number",
            ),
        ]

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
        # A forward FK reads binned rows too: a trigger in the recycle bin counts as none.
        if not webhook_trigger or not webhook_trigger.active or not webhook_trigger.provider_type:
            return "No webhook trigger configured for this channel"
        if webhook_trigger.provider_type in LOCAL_ONLY_PROVIDERS:
            return (
                "Localhost webhook provider is not reachable by Twilio. "
                "Use ngrok or a publicly accessible provider."
            )
        return None
