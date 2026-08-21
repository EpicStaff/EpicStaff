from rest_framework import serializers

from tables.models.secret_models import Secret

from tables.serializers.model_serializers.python_serializers import PythonCodeSerializer
from tables.models.graph_models import (
    Graph,
    TelegramTriggerNode,
    TelegramTriggerNodeField,
    WebhookTriggerNode,
    ScheduleTriggerNode,
)

from tables.validators.schedule_trigger_validator import (
    ScheduleTriggerInputParser,
    ScheduleTriggerValidator,
)
from tables.models.webhook_models import (
    LOCAL_ONLY_PROVIDERS,
    WebhookTrigger,
    WebhookNodeAuth,
)
from tables.serializers.base_serializer import (
    BaseGraphEntityMixin,
    ContentHashWritableMixin,
)
from tables.serializers.base_serializers import WebhookTriggerNestedSerializer
from tables.serializers.utils.mixins import NestedPythonCodeMixin
from tables.serializers.org_scoped_fields import OrgScopedPrimaryKeyRelatedField
from tables.services.schedule_trigger_service import ScheduleTriggerService
# NOTE: WebhookTriggerService is imported lazily inside
# WebhookTriggerNodeSerializer.create() below, not here at module level.
# tables.services.webhook_trigger_service -> converter_service ->
# tables.serializers.model_serializers (this package, via
# node_serializers/__init__.py -> this module) forms a circular import if
# WebhookTriggerService is imported at module scope -- Django's app.ready()
# import chain then fails with "cannot import name 'ConverterService' from
# partially initialized module" before the app can even boot.


class WebhookNodeAuthSerializer(serializers.ModelSerializer):
    class Meta:
        model = WebhookNodeAuth
        fields = [
            "enabled",
            "scheme",
            "header_name",
            "timestamp_header_name",
            "tolerance_seconds",
            "signing_secret",
        ]


class WebhookNodeAuthInputSerializer(serializers.Serializer):
    """Minimal client-writable shape for `webhook_node_auth` on
    `WebhookTriggerNodeSerializer`. Only `enabled` is client-controllable --
    `scheme`/`header_name`/`signing_secret`/etc. stay server-generated (see
    `WebhookTriggerService.ensure_webhook_auth`). Any other sub-fields the
    client sends alongside `enabled` are ignored, not rejected.
    """

    enabled = serializers.BooleanField()


class WebhookTriggerNodeSerializer(
    BaseGraphEntityMixin,
    NestedPythonCodeMixin,
    serializers.ModelSerializer,
):
    python_code = PythonCodeSerializer()
    webhook_trigger = OrgScopedPrimaryKeyRelatedField(
        queryset=WebhookTrigger.objects.all(), required=False, allow_null=True
    )
    graph = OrgScopedPrimaryKeyRelatedField(queryset=Graph.objects.all())

    # Declared read_only so ModelSerializer keeps rendering the full object
    # (enabled/scheme/header_name/.../signing_secret) on GET; the writable
    # `{"enabled": bool}` shape is carved out and validated separately in
    # `to_internal_value` below, then applied via `_sync_webhook_node_auth`.
    webhook_node_auth = WebhookNodeAuthSerializer(read_only=True)

    class Meta(BaseGraphEntityMixin.Meta):
        model = WebhookTriggerNode
        fields = [
            "id",
            "node_name",
            "graph",
            "python_code",
            "webhook_trigger",
            "webhook_node_auth",
        ] + BaseGraphEntityMixin.Meta.common_fields

    def to_internal_value(self, data):
        raw_auth = serializers.empty
        if isinstance(data, dict) and "webhook_node_auth" in data:
            data = dict(data)
            raw_auth = data.pop("webhook_node_auth")

        attrs = super().to_internal_value(data)

        if raw_auth is not serializers.empty:
            if raw_auth is None:
                raise serializers.ValidationError(
                    {
                        "webhook_node_auth": (
                            "Must be an object with an 'enabled' boolean, "
                            "e.g. {\"enabled\": false}."
                        )
                    }
                )
            auth_serializer = WebhookNodeAuthInputSerializer(data=raw_auth)
            if not auth_serializer.is_valid():
                raise serializers.ValidationError(
                    {"webhook_node_auth": auth_serializer.errors}
                )
            attrs["webhook_node_auth"] = auth_serializer.validated_data

        return attrs

    def _sync_webhook_node_auth(
        self, node: WebhookTriggerNode, auth_input: dict | None
    ) -> None:
        """Applies the client-controlled `{"enabled": bool}` request onto the
        node's `WebhookNodeAuth` row via the service layer. `auth_input` is
        `None` when the client omitted `webhook_node_auth` entirely -- a
        no-op here (default-enable-on-create is handled by the caller).
        """
        if auth_input is None:
            return

        from tables.services.webhook_trigger_service import WebhookTriggerService

        WebhookTriggerService().sync_webhook_auth(
            node, enabled=auth_input["enabled"]
        )

    def create(self, validated_data):
        from tables.services.webhook_trigger_service import WebhookTriggerService

        auth_input = validated_data.pop("webhook_node_auth", None)
        node = super().create(validated_data)

        # Create always ensures a row exists (unlike update, where disabling
        # a not-yet-existing row is legitimately a no-op) -- omitting
        # webhook_node_auth entirely defaults to enabled (default-safe,
        # preserves existing behavior); an explicit {"enabled": false}
        # creates the row already disabled.
        enabled = True if auth_input is None else auth_input["enabled"]
        WebhookTriggerService().ensure_webhook_auth(node, enabled=enabled)

        node.refresh_from_db()
        return node

    def update(self, instance, validated_data):
        auth_input = validated_data.pop("webhook_node_auth", None)
        instance = super().update(instance, validated_data)

        self._sync_webhook_node_auth(instance, auth_input)

        instance.refresh_from_db()
        return instance


class WebhookTriggerNodeReadSerializer(WebhookTriggerNodeSerializer):
    webhook_trigger = WebhookTriggerNestedSerializer(read_only=True)


class TelegramTriggerNodeFieldSerializer(
    ContentHashWritableMixin, serializers.ModelSerializer
):
    class Meta:
        model = TelegramTriggerNodeField
        fields = [
            "id",
            "parent",
            "field_name",
            "variable_path",
            "content_hash",
        ]


class TelegramTriggerNodeSerializer(
    ContentHashWritableMixin,
    serializers.ModelSerializer,
):
    telegram_bot_api_key_secret_id = OrgScopedPrimaryKeyRelatedField(
        queryset=Secret.objects.all(),
        source="telegram_bot_api_key_secret",
        required=False,
        allow_null=True,
    )
    webhook_trigger = OrgScopedPrimaryKeyRelatedField(
        queryset=WebhookTrigger.objects.all(), required=False, allow_null=True
    )
    fields = TelegramTriggerNodeFieldSerializer(many=True)
    graph = OrgScopedPrimaryKeyRelatedField(queryset=Graph.objects.all())

    class Meta(BaseGraphEntityMixin.Meta):
        model = TelegramTriggerNode
        fields = [
            "id",
            "node_name",
            "telegram_bot_api_key_secret_id",
            "graph",
            "fields",
            "webhook_trigger",
        ] + BaseGraphEntityMixin.Meta.common_fields

    def validate(self, attrs):
        wt = attrs.get("webhook_trigger")
        provider_type = wt.provider_type if wt else None

        if provider_type and provider_type in LOCAL_ONLY_PROVIDERS:
            raise serializers.ValidationError(
                {
                    "webhook_trigger": (
                        "Localhost webhook provider is not reachable by Telegram. "
                        "Use ngrok or a publicly accessible provider."
                    )
                }
            )

        return attrs

    def create(self, validated_data):
        fields_data = validated_data.pop("fields", [])
        node = TelegramTriggerNode.objects.create(**validated_data)
        for item in fields_data:
            TelegramTriggerNodeField.objects.create(telegram_trigger_node=node, **item)
        return node

    def update(self, instance, validated_data):
        fields_data = validated_data.pop("fields", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if fields_data is not None:
            instance.fields.all().delete()
            for item in fields_data:
                TelegramTriggerNodeField.objects.create(
                    telegram_trigger_node=instance, **item
                )

        return instance


class TelegramTriggerNodeReadSerializer(TelegramTriggerNodeSerializer):
    webhook_trigger = WebhookTriggerNestedSerializer(read_only=True)


class TelegramTriggerNodeDataFieldsSerializer(serializers.Serializer):
    data = serializers.JSONField()


class _ScheduleIntervalInputSerializer(serializers.Serializer):
    every = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    unit = serializers.ChoiceField(
        choices=ScheduleTriggerNode.TimeUnit.choices,
        required=False,
        allow_null=True,
    )
    weekdays = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_null=True,
        allow_empty=True,
    )


class _ScheduleEndInputSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=ScheduleTriggerNode.EndType.choices)
    date_time = serializers.CharField(required=False, allow_null=True)
    max_runs = serializers.IntegerField(required=False, allow_null=True, min_value=1)


class _ScheduleConfigInputSerializer(serializers.Serializer):
    """Wire-shape DTO for the nested `schedule` block. Primitive shape only.

    Used both as the OpenAPI schema for the `schedule` field on
    ScheduleTriggerNodeSerializer and as the shape validator inside
    ScheduleTriggerInputParser. Domain rules and wire↔model translation live
    in tables.validators.schedule_trigger_validator.
    """

    run_mode = serializers.ChoiceField(
        choices=ScheduleTriggerNode.RunMode.choices,
        required=False,
        allow_null=True,
    )
    timezone = serializers.CharField(required=False, allow_null=True)
    start_date_time = serializers.CharField(required=False, allow_null=True)
    interval = _ScheduleIntervalInputSerializer(required=False, allow_null=True)
    end = _ScheduleEndInputSerializer(required=False, allow_null=True)


class ScheduleTriggerNodeSerializer(serializers.Serializer):
    """Shape/type validation only. Domain rules → ScheduleTriggerValidator.
    Persistence → ScheduleTriggerService.

    Translates the nested `schedule` block to/from the model's flat columns and
    converts naive ISO datetimes between the user's tz and UTC at the boundary.
    """

    id = serializers.IntegerField(read_only=True)
    graph = OrgScopedPrimaryKeyRelatedField(queryset=Graph.objects.all())
    node_name = serializers.CharField(max_length=255)
    is_active = serializers.BooleanField(required=False)
    metadata = serializers.JSONField(required=False)
    content_hash = serializers.CharField(required=False, allow_null=True)
    schedule = _ScheduleConfigInputSerializer(
        required=False, allow_null=True, write_only=True
    )
    current_runs = serializers.IntegerField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            return super().to_internal_value(data)
        data = dict(data)
        raw_schedule = data.pop("schedule", serializers.empty)
        attrs = super().to_internal_value(data)
        if raw_schedule is not serializers.empty:
            attrs.update(
                ScheduleTriggerInputParser().parse_to_internal_value(
                    raw_schedule, self.instance
                )
            )
        return attrs

    def validate(self, attrs):
        state = ScheduleTriggerValidator.compose_state(
            self.instance, attrs, self.initial_data
        )
        ScheduleTriggerValidator().validate(state)
        return attrs

    def to_representation(self, instance):
        rep = super().to_representation(instance)
        rep["schedule"] = ScheduleTriggerInputParser.render_to_representation(instance)
        return rep

    def create(self, validated_data):
        return ScheduleTriggerService().create_node(validated_data)

    def update(self, instance, validated_data):
        return ScheduleTriggerService().update_node(instance, validated_data)
