from rest_framework import serializers

from tables.models import Crew, Task
from tables.import_export.enums import EntityType


class TaskImportSerializer(serializers.ModelSerializer):
    tools = serializers.JSONField(required=False)
    context = serializers.JSONField(required=False)

    class Meta:
        model = Task
        exclude = ["crew"]

    def to_representation(self, instance):
        ret = super().to_representation(instance)

        ret["tools"] = {
            EntityType.PYTHON_CODE_TOOL: list(
                instance.task_python_code_tool_list.values_list("tool_id", flat=True)
            ),
            EntityType.MCP_TOOL: list(
                instance.task_mcp_tool_list.values_list("tool_id", flat=True)
            ),
        }
        ret["context"] = list(
            instance.task_context_list.values_list("context_id", flat=True)
        )

        return ret


class CrewImportSerializer(serializers.ModelSerializer):
    tasks = serializers.JSONField(required=False)

    class Meta:
        model = Crew
        exclude = ["tags"]

    def to_representation(self, instance):
        ret = super().to_representation(instance)

        tasks = instance.task_set.all()
        ret["tasks"] = TaskImportSerializer(tasks, many=True).data

        return ret
