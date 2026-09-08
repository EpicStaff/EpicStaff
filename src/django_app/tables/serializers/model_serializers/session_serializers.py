from rest_framework import serializers

from tables.models.session_models import (
    AgentSessionMessage,
    Session,
    SessionTrigger,
    TaskSessionMessage,
    UserSessionMessage,
)


class UserSessionMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserSessionMessage

        fields = "__all__"


class TaskSessionMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskSessionMessage

        fields = "__all__"


class AgentSessionMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentSessionMessage
        fields = "__all__"


class SessionTriggerSerializer(serializers.ModelSerializer):
    trigger_id = serializers.IntegerField(read_only=True, allow_null=True)

    class Meta:
        model = SessionTrigger
        fields = ("trigger_type", "trigger_id")


class SessionSerializer(serializers.ModelSerializer):
    trigger = SessionTriggerSerializer(read_only=True)

    class Meta:
        model = Session
        fields = "__all__"
        read_only_fields = [
            "id",
            "status",
            "status_updated_at",
            "variables",
            "created_at",
            "finished_at",
            "graph",
            "graph_schema",
            "parent_session",
            "trigger",
        ]


class SessionLightSerializer(serializers.ModelSerializer):
    has_output_files = serializers.BooleanField(read_only=True)
    graph_name = serializers.CharField(source="graph.name", read_only=True)
    trigger = SessionTriggerSerializer(read_only=True)

    class Meta:
        model = Session
        fields = (
            "id",
            "graph_id",
            "graph_name",
            "status",
            "status_updated_at",
            "created_at",
            "finished_at",
            "parent_session",
            "has_output_files",
            "trigger",
        )
