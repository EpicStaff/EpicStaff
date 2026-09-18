from django.core.exceptions import ObjectDoesNotExist
from rest_framework import serializers

from tables.models import Graph, AgentNode
from tables.import_export.serializers.inline_surface import serialize_inline_surface


class AgentNodeImportSerializer(serializers.ModelSerializer):
    node_type = serializers.CharField(required=False)
    graph = serializers.PrimaryKeyRelatedField(
        queryset=Graph.objects.all(), write_only=True
    )

    class Meta:
        model = AgentNode
        exclude = ["created_at", "updated_at", "surface_list"]

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        ret["surface_list"] = list(instance.surface_list.values_list("id", flat=True))

        try:
            ret["inline_surface"] = serialize_inline_surface(instance.inline_surface)
        except ObjectDoesNotExist:
            ret["inline_surface"] = None

        ret["tasks"] = [
            {
                "id": task.id,
                "name": task.name,
                "order": task.order,
                "instructions": task.instructions,
                "output_schema": task.output_schema,
                "context_tasks": list(task.context_tasks.values_list("id", flat=True)),
            }
            for task in instance.tasks.all()
        ]

        return ret
