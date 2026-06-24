from rest_framework import serializers

from tables.models.session_models import (
    AgentSessionMessage,
    Session,
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


class SessionSerializer(serializers.ModelSerializer):
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
        ]

    def to_representation(self, instance):
        """Remove 'shared' proxy from variables for UI display"""
        data = super().to_representation(instance)
        if data.get("variables") and isinstance(data["variables"], dict):
            data["variables"] = {
                k: v for k, v in data["variables"].items() if k != "shared"
            }
        return data


class SessionLightSerializer(serializers.ModelSerializer):
    has_output_files = serializers.BooleanField(read_only=True)
    graph_name = serializers.CharField(source="graph.name", read_only=True)

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
        )
