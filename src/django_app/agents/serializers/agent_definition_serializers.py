from __future__ import annotations

from django.db import IntegrityError
from rbac.scoping.fields import (
    OrganizationScopedPrimaryKeyRelatedField,
    OrgScopedPrimaryKeyRelatedField,
)
from rest_framework import serializers
from tables.models.llm_models import LLMConfig

from agents.exceptions import AgentDefinitionConflictError
from agents.models.agent_models import (
    AgentDefaultSurface,
    AgentDefinition,
    SurfacePlace,
)
from agents.models.surface_models import Surface
from agents.services.surface_service import AgentDefinitionSurfaceService
from agents.validators.surface_validator import SurfaceValidator


class AgentDefaultSurfaceReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentDefaultSurface
        fields = ["surface", "place"]


class AgentDefaultSurfaceWriteSerializer(serializers.Serializer):
    surface = OrganizationScopedPrimaryKeyRelatedField(queryset=Surface.objects.all())
    place = serializers.ChoiceField(choices=SurfacePlace.choices)


class InstructionSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, trim_whitespace=True)
    content = serializers.CharField(allow_blank=True, trim_whitespace=False)

    def to_internal_value(self, data):
        if isinstance(data, dict):
            unknown_keys = set(data) - set(self.fields)
            if unknown_keys:
                raise serializers.ValidationError(
                    {key: "Unknown field." for key in sorted(unknown_keys)}
                )
        return super().to_internal_value(data)


class InstructionListField(serializers.ListField):
    """Ordered list of named instructions; names must be unique case-insensitively."""

    child = InstructionSerializer()

    def to_internal_value(self, data):
        instruction_list = super().to_internal_value(data)
        seen_names = set()
        for instruction in instruction_list:
            normalized_name = instruction["name"].casefold()
            if normalized_name in seen_names:
                raise serializers.ValidationError(
                    "An instruction with that name already exists. Please enter a unique name."
                )
            seen_names.add(normalized_name)
        return [dict(instruction) for instruction in instruction_list]


class AgentDefinitionReadSerializer(serializers.ModelSerializer):
    default_surfaces = serializers.SerializerMethodField()
    instructions = serializers.CharField(read_only=True)
    agent_definition_realtime_config_id = serializers.SerializerMethodField()
    has_realtime_definition = serializers.SerializerMethodField()

    def get_default_surfaces(self, obj):
        return AgentDefinitionSurfaceService.get_default_surfaces(obj)

    def _get_realtime_agent(self, obj):
        try:
            return obj.realtime_agent
        except AgentDefinition.realtime_agent.RelatedObjectDoesNotExist:
            return None

    def get_agent_definition_realtime_config_id(self, obj):
        realtime_agent = self._get_realtime_agent(obj)
        if realtime_agent is None:
            return None

        # `realtime_agent` is a `RealtimeAgentDefinition`; it may have at most
        # one of openai_config/elevenlabs_config/gemini_config set (its
        # `clean()` enforces that) — return whichever one is active. This
        # used to be the old `realtime_config_id` FK id; the exposed field
        # name (`agent_definition_realtime_config_id`) is unchanged, only the
        # underlying provider-config model it points at has changed.
        return realtime_agent.active_provider_config_id

    def get_has_realtime_definition(self, obj):
        return self._get_realtime_agent(obj) is not None

    class Meta:
        model = AgentDefinition
        fields = [
            "id",
            "organization",
            "name",
            "description",
            "instruction_list",
            "instructions",
            "llm_config",
            "fcm_llm_config",
            "max_iter",
            "max_rpm",
            "max_execution_time",
            "cache",
            "max_retry_limit",
            "default_temperature",
            "max_tool_calls",
            "tool_timeout",
            "max_consecutive_failures",
            "schema_max_retries",
            "metadata",
            "default_surfaces",
            "agent_definition_realtime_config_id",
            "has_realtime_definition",
        ]
        read_only_fields = fields


class AgentDefinitionWriteSerializer(serializers.ModelSerializer):
    llm_config = OrgScopedPrimaryKeyRelatedField(
        queryset=LLMConfig.objects.all(),
        required=False,
        allow_null=True,
    )
    fcm_llm_config = OrgScopedPrimaryKeyRelatedField(
        queryset=LLMConfig.objects.all(),
        required=False,
        allow_null=True,
    )
    default_surfaces = AgentDefaultSurfaceWriteSerializer(many=True, required=False)
    instruction_list = InstructionListField(required=False)
    max_tool_calls = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    tool_timeout = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    max_consecutive_failures = serializers.IntegerField(
        required=False, allow_null=True, min_value=1
    )
    schema_max_retries = serializers.IntegerField(required=False, allow_null=True, min_value=0)

    class Meta:
        model = AgentDefinition
        fields = [
            "name",
            "description",
            "instruction_list",
            "llm_config",
            "fcm_llm_config",
            "max_iter",
            "max_rpm",
            "max_execution_time",
            "cache",
            "max_retry_limit",
            "default_temperature",
            "max_tool_calls",
            "tool_timeout",
            "max_consecutive_failures",
            "schema_max_retries",
            "metadata",
            "default_surfaces",
        ]

    def validate(self, attrs):
        # Released clients still send the old single `instructions` text; refuse it loudly
        # instead of saving the agent without them.
        if "instructions" in self.initial_data:
            raise serializers.ValidationError(
                {"instructions": "This field is read-only. Send instruction_list instead."}
            )

        default_surfaces_data = attrs.get("default_surfaces")

        if default_surfaces_data is not None:
            SurfaceValidator.validate_agent_default_surfaces(
                items=default_surfaces_data,
                agent_definition=self.instance,
            )

        return attrs

    def create(self, validated_data):
        default_surfaces_data = validated_data.pop("default_surfaces", [])

        try:
            instance = super().create(validated_data)
        except IntegrityError as exc:
            raise AgentDefinitionConflictError() from exc

        AgentDefinitionSurfaceService.set_default_surfaces(
            agent_definition=instance,
            items=default_surfaces_data,
        )
        return instance

    def update(self, instance, validated_data):
        default_surfaces_data = validated_data.pop("default_surfaces", None)

        try:
            instance = super().update(instance, validated_data)
        except IntegrityError as exc:
            raise AgentDefinitionConflictError() from exc

        if default_surfaces_data is not None:
            AgentDefinitionSurfaceService.set_default_surfaces(
                agent_definition=instance,
                items=default_surfaces_data,
            )

        return instance
