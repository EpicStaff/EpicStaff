from rest_framework import serializers
from tables.models.crew_models import ToolConfig
from tables.models.python_models import PythonCodeTool
from tables.models.realtime_models import VoiceChoices


class RunSessionSerializer(serializers.Serializer):
    graph_id = serializers.IntegerField(required=True)
    variables = serializers.DictField(required=False)


class GetUpdatesSerializer(serializers.Serializer):
    session_id = serializers.IntegerField(required=True)


class AnswerToLLMSerializer(serializers.Serializer):
    session_id = serializers.IntegerField(required=True)
    crew_id = serializers.IntegerField(required=True)
    execution_order = serializers.IntegerField(required=True)
    name = serializers.CharField()
    answer = serializers.CharField()


class EnvironmentConfigSerializer(serializers.Serializer):
    data = serializers.DictField(required=True)


class InitRealtimeSerializer(serializers.Serializer):
    agent_id = serializers.IntegerField(required=True)


class BaseToolSerializer(serializers.Serializer):

    unique_name = serializers.CharField(required=True)  # type + id
    data = serializers.DictField(required=True)

    def to_representation(self, instance):  # instance is a Tool instance
        from tables.serializers.model_serializers import PythonCodeToolSerializer, ToolConfigSerializer

        repr = {}
        if isinstance(instance, PythonCodeTool):
            repr["unique_name"] = f"python-code-tool:{instance.pk}"
            repr["data"] = PythonCodeToolSerializer(instance).data
        elif isinstance(instance, ToolConfig):
            repr["unique_name"] = f"configured-tool:{instance.pk}"
            repr["data"] = ToolConfigSerializer(instance).data
        else:
            raise TypeError(
                f"Unsupported tool type for serialization: {type(instance)}"
            )

        return repr
    
    