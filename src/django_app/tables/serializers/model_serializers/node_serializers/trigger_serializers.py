from rest_framework import serializers

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
from tables.services.schedule_trigger_service import ScheduleTriggerService
from tables.models.webhook_models import WebhookTrigger, ProviderType
from tables.serializers.base_serializer import (
    BaseGraphEntityMixin,
    ContentHashWritableMixin,
)
from tables.serializers.utils.mixins import (
    NestedPythonCodeMixin,
    WebhookCreationMixin,
    WebhookTriggerIntRefMixin,
)
from tables.serializers.base_serializers import (
    WebhookTriggerNestedSerializer,
)


class WebhookTriggerNodeSerializer(
    BaseGraphEntityMixin,
    NestedPythonCodeMixin,
    WebhookTriggerIntRefMixin,
    WebhookCreationMixin,
    serializers.ModelSerializer,
):
    python_code = PythonCodeSerializer()

    webhook_trigger = WebhookTriggerNestedSerializer(required=False, allow_null=True)

    class Meta(BaseGraphEntityMixin.Meta):
        model = WebhookTriggerNode
        fields = [
            "id",
            "node_name",
            "graph",
            "python_code",
            "webhook_trigger",
        ] + BaseGraphEntityMixin.Meta.common_fields

    def _wait_for_tunnel_url(self, webhook_trigger):
        from tables.services.webhook_trigger_service import WebhookTriggerService

        if webhook_trigger is None:
            return
        service = WebhookTriggerService()
        if webhook_trigger.provider_type == ProviderType.NGROK:
            service.wait_for_tunnel_url(webhook_trigger)
        elif webhook_trigger.provider_type == ProviderType.LOCALHOST:
            service.wait_for_localhost_tunnel_url(webhook_trigger)

    def create(self, validated_data):
        webhook_trigger_data = validated_data.pop("webhook_trigger", None)
        if not self._apply_webhook_trigger_fk_to_create(validated_data):
            if webhook_trigger_data:
                trigger, _ = self._get_or_create_webhook_trigger(webhook_trigger_data)
                validated_data["webhook_trigger"] = trigger
                self._wait_for_tunnel_url(trigger)

        return self._create_with_python_code(WebhookTriggerNode, validated_data)

    def update(self, instance, validated_data):
        if not self._apply_webhook_trigger_fk_to_update(instance, validated_data):
            if "webhook_trigger" in validated_data:
                webhook_trigger_data = validated_data.pop("webhook_trigger")
                if webhook_trigger_data:
                    trigger, _ = self._get_or_create_webhook_trigger(
                        webhook_trigger_data
                    )
                    instance.webhook_trigger = trigger
                    self._wait_for_tunnel_url(trigger)
                else:
                    instance.webhook_trigger = None

        return super().update(instance, validated_data)


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
    WebhookTriggerIntRefMixin,
    WebhookCreationMixin,
    serializers.ModelSerializer,
):
    webhook_trigger = WebhookTriggerNestedSerializer(required=False, allow_null=True)
    fields = TelegramTriggerNodeFieldSerializer(many=True)

    class Meta(BaseGraphEntityMixin.Meta):
        model = TelegramTriggerNode
        fields = [
            "id",
            "node_name",
            "telegram_bot_api_key",
            "graph",
            "fields",
            "webhook_trigger",
        ] + BaseGraphEntityMixin.Meta.common_fields

    def create(self, validated_data):
        fields_data = validated_data.pop("fields", [])
        webhook_trigger_data = validated_data.pop("webhook_trigger", None)
        if not self._apply_webhook_trigger_fk_to_create(validated_data):
            if webhook_trigger_data:
                trigger, _ = self._get_or_create_webhook_trigger(webhook_trigger_data)
                validated_data["webhook_trigger"] = trigger

        node = TelegramTriggerNode.objects.create(**validated_data)
        for item in fields_data:
            TelegramTriggerNodeField.objects.create(telegram_trigger_node=node, **item)

        return node

    def update(self, instance, validated_data):
        fields_data = validated_data.pop("fields", None)
        if not self._apply_webhook_trigger_fk_to_update(instance, validated_data):
            if "webhook_trigger" in validated_data:
                webhook_trigger_data = validated_data.pop("webhook_trigger")
                webhook_trigger_instance = None
                if webhook_trigger_data:
                    webhook_trigger_instance, _ = self._get_or_create_webhook_trigger(
                        webhook_trigger_data
                    )
                instance.webhook_trigger = webhook_trigger_instance

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
    graph = serializers.PrimaryKeyRelatedField(queryset=Graph.objects.all())
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
