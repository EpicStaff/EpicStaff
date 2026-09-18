from django.core.exceptions import ObjectDoesNotExist
from rest_framework import serializers

from tables.models import Graph, TaskNode
from tables.import_export.serializers.inline_surface import serialize_inline_surface


class TaskNodeImportSerializer(serializers.ModelSerializer):
    node_type = serializers.CharField(required=False)
    graph = serializers.PrimaryKeyRelatedField(
        queryset=Graph.objects.all(), write_only=True
    )

    class Meta:
        model = TaskNode
        exclude = ["created_at", "updated_at", "surface_list"]

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        ret["surface_list"] = list(instance.surface_list.values_list("id", flat=True))

        try:
            ret["inline_surface"] = serialize_inline_surface(instance.inline_surface)
        except ObjectDoesNotExist:
            ret["inline_surface"] = None

        return ret
