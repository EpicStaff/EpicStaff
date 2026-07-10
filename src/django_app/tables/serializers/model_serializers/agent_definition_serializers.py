from __future__ import annotations

from django.db import IntegrityError
from rest_framework import serializers

from tables.exceptions import AgentDefinitionConflictError
from tables.models.agent_models.agent_models import (
    AgentDefaultSurface,
    AgentDefinition,
    SurfacePlace,
)
from tables.models.agent_models.surface_models import Surface
from tables.models.llm_models import LLMConfig
from tables.services.surface_service import AgentDefinitionSurfaceService
from tables.validators.surface_validator import SurfaceValidator


class AgentDefaultSurfaceReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentDefaultSurface
        fields = ["surface", "place"]


class AgentDefaultSurfaceWriteSerializer(serializers.Serializer):
    surface = serializers.PrimaryKeyRelatedField(queryset=Surface.objects.all())
    place = serializers.ChoiceField(choices=SurfacePlace.choices)


class AgentDefinitionReadSerializer(serializers.ModelSerializer):
    default_surfaces = serializers.SerializerMethodField()

    def get_default_surfaces(self, obj):
        return AgentDefinitionSurfaceService.get_default_surfaces(obj)

    class Meta:
        model = AgentDefinition
        fields = [
            "id",
            "organization",
            "name",
            "description",
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
        ]
        read_only_fields = fields


class AgentDefinitionWriteSerializer(serializers.ModelSerializer):
    llm_config = serializers.PrimaryKeyRelatedField(
        queryset=LLMConfig.objects.all(),
        required=False,
        allow_null=True,
    )
    fcm_llm_config = serializers.PrimaryKeyRelatedField(
        queryset=LLMConfig.objects.all(),
        required=False,
        allow_null=True,
    )
    default_surfaces = AgentDefaultSurfaceWriteSerializer(many=True, required=False)
    max_tool_calls = serializers.IntegerField(
        required=False, allow_null=True, min_value=1
    )
    tool_timeout = serializers.IntegerField(
        required=False, allow_null=True, min_value=1
    )
    max_consecutive_failures = serializers.IntegerField(
        required=False, allow_null=True, min_value=1
    )
    schema_max_retries = serializers.IntegerField(
        required=False, allow_null=True, min_value=0
    )

    class Meta:
        model = AgentDefinition
        fields = [
            "name",
            "description",
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
        ]

    def validate(self, attrs):
        default_surfaces_data = attrs.get("default_surfaces")

        if default_surfaces_data is not None:
            organization = self.context.get("organization")
            agent_definition = self.instance

            if organization is not None:
                SurfaceValidator.validate_agent_default_surfaces(
                    items=default_surfaces_data,
                    agent_definition=agent_definition,
                    organization=organization,
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
