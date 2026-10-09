from agents.models import AgentDefinition
from agents.serializers.agent_definition_serializers import InstructionListField
from rest_framework import serializers


class AgentDefinitionImportSerializer(serializers.ModelSerializer):
    instruction_list = InstructionListField(required=False)

    class Meta:
        model = AgentDefinition
        exclude = ["organization", "default_surface_list"]

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        ret["owned_surfaces"] = list(instance.owned_surfaces.values_list("id", flat=True))
        ret["default_surfaces"] = list(instance.default_surfaces.values("surface_id", "place"))
        return ret
