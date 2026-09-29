from django.db.models import Q
from rest_framework import serializers


class TimestampMixin(serializers.Serializer):
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)

    class Meta:
        common_fields = ["created_at", "updated_at"]


class ContentHashMixin(serializers.Serializer):
    content_hash = serializers.CharField(required=False, allow_null=True)

    class Meta:
        common_fields = ["content_hash"]


class ContentHashWritableMixin:
    """Adds content_hash as an optional writable field.

    content_hash is a computed property on the model (not a DB column), so
    ModelSerializer won't include it automatically. get_fields() injects it
    so Swagger shows it and clients can pass it. validate() removes it from
    validated_data — the view-level ContentHashPreconditionMixin is
    responsible for setting instance._expected_hash before save().
    """

    def get_fields(self):
        fields = super().get_fields()
        fields["content_hash"] = serializers.CharField(required=False, allow_null=True)
        return fields


class MetadataMixin(serializers.Serializer):
    metadata = serializers.JSONField()

    class Meta:
        common_fields = ["metadata"]


class BaseGraphEntityMixin(TimestampMixin, ContentHashMixin, MetadataMixin):
    class Meta:
        common_fields = (
            TimestampMixin.Meta.common_fields
            + ContentHashMixin.Meta.common_fields
            + MetadataMixin.Meta.common_fields
        )


class OpenAIRealtimeModelNameValidationMixin(serializers.Serializer):
    """Mixin with shared `validate_model_name` for serializers backed by `OpenAIRealtimeConfig`.

    On UPDATE: skips validation if the value is unchanged from the instance's
    current model_name (the frontend resends the full form on PUT, so an
    already-stale model_name must not block edits to unrelated fields).
    On CREATE: always validates against the org's OpenAI realtime registry.
    """

    def validate_model_name(self, value):
        if self.instance is not None and value == self.instance.model_name:
            return value

        if self.instance is not None:
            org_id = self.instance.org_id
        else:
            from rbac.scoping.fields import resolve_active_org_id

            request = self.context.get("request")
            if request is None:
                # Shouldn't happen in normal API flow, but allow validation to
                # pass if request is missing (e.g., in shell/management commands)
                return value
            org_id = resolve_active_org_id(request)

        self._validate_openai_realtime_model_name(value, org_id)
        return value

    def _validate_openai_realtime_model_name(self, model_name: str, org_id: int) -> None:
        """Validate that model_name exists in the RealtimeModel registry for OpenAI.

        Checks both builtin models (is_custom=False, org__isnull=True) and
        org-scoped custom models (is_custom=True, org=org_id).

        Raises ValidationError if no matching RealtimeModel is found.
        """
        from tables.models import Provider, RealtimeModel

        try:
            openai_provider = Provider.objects.get(name="openai")
        except Provider.DoesNotExist:
            raise serializers.ValidationError(
                "OpenAI provider is not registered in the system."
            ) from None

        # Filter: builtin models OR org's custom models
        scoped_filter = Q(is_custom=False, org__isnull=True) | Q(is_custom=True, org_id=org_id)

        model_exists = (
            RealtimeModel.objects.filter(
                provider=openai_provider,
                name=model_name,
            )
            .filter(scoped_filter)
            .exists()
        )

        if not model_exists:
            raise serializers.ValidationError(
                f"Model '{model_name}' is not available in the OpenAI realtime registry "
                f"for your organization."
            )
