from rest_framework import serializers

from agents.models import AgentDefinition


class AgentDefinitionImportSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentDefinition
        exclude = ["organization", "default_surface_list"]

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        ret["owned_surfaces"] = list(
            instance.owned_surfaces.values_list("id", flat=True)
        )
        ret["default_surfaces"] = list(
            instance.default_surfaces.values("surface_id", "place")
        )
        return ret
