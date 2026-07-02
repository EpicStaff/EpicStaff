from __future__ import annotations

from django.core import exceptions as dj_exceptions
from django.db import transaction

from tables.exceptions import SurfaceValidationError
from tables.models.agent_models.agent_models import AgentDefaultSurface, SurfacePlace
from tables.models.agent_models.surface_models import Surface
from tables.services.surface_content_service import (
    CATALOG_SURFACE_CONTENT,
    SurfaceContentService,
)


class SurfaceService:
    @staticmethod
    def validate_surface_data(*, instance, organization, attrs):
        if instance is not None:
            candidate = Surface(
                pk=instance.pk,
                organization_id=instance.organization_id,
                name=instance.name,
                description=instance.description,
                instructions=instance.instructions,
                allow_creation=instance.allow_creation,
            )
            candidate._state.adding = False
        else:
            candidate = Surface()

        for field_name in (
            "name",
            "description",
            "instructions",
            "allow_creation",
            "owner_agent",
        ):
            if field_name in attrs:
                setattr(candidate, field_name, attrs[field_name])

        candidate.organization = organization

        try:
            candidate.full_clean()
        except dj_exceptions.ValidationError as exc:
            if hasattr(exc, "message_dict"):
                raise SurfaceValidationError(detail=exc.message_dict)
            raise SurfaceValidationError(detail=exc.messages)

        return attrs

    @staticmethod
    @transaction.atomic
    def create_surface(*, organization, validated_data):
        python_tools_data = validated_data.pop("python_tools", [])
        mcp_tools_data = validated_data.pop("mcp_tools", [])
        storage_items_data = validated_data.pop("storage_items", [])
        knowledge_data = validated_data.pop("knowledge", [])

        surface = Surface.objects.create(organization=organization, **validated_data)

        SurfaceService._replace_python_tools(surface, python_tools_data)
        SurfaceService._replace_mcp_tools(surface, mcp_tools_data)
        SurfaceService._replace_storage_items(surface, storage_items_data)
        SurfaceService._replace_knowledge(surface, knowledge_data)

        return surface

    @staticmethod
    @transaction.atomic
    def update_surface(*, instance, validated_data, partial):
        python_tools_data = validated_data.pop("python_tools", None)
        mcp_tools_data = validated_data.pop("mcp_tools", None)
        storage_items_data = validated_data.pop("storage_items", None)
        knowledge_data = validated_data.pop("knowledge", None)

        scalar_keys = list(validated_data.keys())

        for key, value in validated_data.items():
            setattr(instance, key, value)

        if partial:
            if scalar_keys:
                instance.save(update_fields=scalar_keys)
        else:
            instance.save()

        if python_tools_data is not None or not partial:
            SurfaceService._replace_python_tools(instance, python_tools_data or [])

        if mcp_tools_data is not None or not partial:
            SurfaceService._replace_mcp_tools(instance, mcp_tools_data or [])

        if storage_items_data is not None or not partial:
            SurfaceService._replace_storage_items(instance, storage_items_data or [])

        if knowledge_data is not None or not partial:
            SurfaceService._replace_knowledge(instance, knowledge_data or [])

        return instance

    @staticmethod
    def _replace_python_tools(surface, items):
        SurfaceContentService.replace_python_tools(
            surface, items, CATALOG_SURFACE_CONTENT
        )

    @staticmethod
    def _replace_mcp_tools(surface, items):
        SurfaceContentService.replace_mcp_tools(surface, items, CATALOG_SURFACE_CONTENT)

    @staticmethod
    def _replace_storage_items(surface, items):
        SurfaceContentService.replace_storage_items(
            surface, items, CATALOG_SURFACE_CONTENT
        )

    @staticmethod
    def _replace_knowledge(surface, items):
        SurfaceContentService.replace_knowledge(surface, items, CATALOG_SURFACE_CONTENT)


class AgentDefinitionSurfaceService:
    @staticmethod
    def get_default_surfaces(agent_definition):
        explicit = list(agent_definition.default_surfaces.all())
        explicit_surface_ids = {ads.surface_id for ads in explicit}
        result = [{"surface": ads.surface_id, "place": ads.place} for ads in explicit]

        for surface in agent_definition.owned_surfaces.all():
            if surface.id not in explicit_surface_ids:
                result.append({"surface": surface.id, "place": SurfacePlace.ALL})

        return result

    @staticmethod
    @transaction.atomic
    def set_default_surfaces(*, agent_definition, items):
        AgentDefaultSurface.objects.filter(agent_definition=agent_definition).delete()

        AgentDefaultSurface.objects.bulk_create(
            [
                AgentDefaultSurface(
                    agent_definition=agent_definition,
                    surface=item["surface"],
                    place=item["place"],
                )
                for item in items
            ]
        )
