from agents.models import AgentDefinition
from rest_framework import serializers


class AgentDefinitionImportSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentDefinition
        # created_at is instance-local: auto_now_add makes it read-only here, so an
        # import would discard it. Reuse matching (COMPARED_FIELDS in the strategy)
        # ignores it, so excluding it only keeps the export free of a dead value.
        exclude = ["org", "created_by", "created_at", "default_surface_list"]

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        ret["owned_surfaces"] = list(instance.owned_surfaces.values_list("id", flat=True))
        ret["default_surfaces"] = list(instance.default_surfaces.values("surface_id", "place"))
        return ret
