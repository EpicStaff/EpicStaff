from rest_framework import serializers

from tables.models.graph_models import GraphSessionMessage
from tables.models.session_models import Session, SessionPrincipal


class GraphSessionMessageExportSerializer(serializers.ModelSerializer):
    class Meta:
        model = GraphSessionMessage
        fields = [
            "id",
            "session_id",
            "created_at",
            "name",
            "execution_order",
            "uuid",
            "message_data",
        ]


class SessionPrincipalExportSerializer(serializers.ModelSerializer):
    class Meta:
        model = SessionPrincipal
        fields = ["kind", "user", "api_key", "email"]


class SessionExportSerializer(serializers.ModelSerializer):
    principal = SessionPrincipalExportSerializer(read_only=True)
    trigger_type = serializers.CharField(source="trigger.trigger_type", default=None)
    trigger_node_name = serializers.CharField(source="trigger.node_name", default=None)

    class Meta:
        model = Session
        fields = [
            "id",
            "status",
            "entrypoint",
            "created_at",
            "finished_at",
            "token_usage",
            "principal",
            "trigger_type",
            "trigger_node_name",
        ]
