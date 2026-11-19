from rest_framework import serializers
from tables.models import (
    DashboardActiveTrigger,
    DashboardKnowledgeUsage,
    DashboardLiveSession,
    DashboardReport,
)

TOTAL_FIELDS = (
    "agents",
    "flows",
    "roles_builtin",
    "roles_custom",
    "users",
    "knowledge_total",
    "knowledge_naive",
    "knowledge_graph",
    "knowledge_not_indexed",
    "files",
    "files_bytes",
    "llm_configs",
    "embedding_configs",
    "realtime_configs",
    "tools_python",
    "tools_mcp",
    "plugins",
)


class DashboardActiveTriggerSerializer(serializers.ModelSerializer):
    class Meta:
        model = DashboardActiveTrigger
        fields = ("trigger_type", "node_id", "node_name", "graph_id", "graph_name", "next_run_at")


class DashboardLiveSessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = DashboardLiveSession
        fields = ("session_id", "graph_id", "graph_name", "status", "created_at")


class DashboardKnowledgeUsageSerializer(serializers.ModelSerializer):
    class Meta:
        model = DashboardKnowledgeUsage
        fields = (
            "rag_type",
            "collections",
            "embedding_tokens",
            "llm_input_tokens",
            "llm_output_tokens",
            "cost_usd",
            "unknown_cost_count",
        )


class DashboardReportSerializer(serializers.ModelSerializer):
    next_build_at = serializers.SerializerMethodField()
    totals = serializers.SerializerMethodField()
    active_triggers = serializers.SerializerMethodField()
    live_sessions = serializers.SerializerMethodField()
    knowledge_usage = serializers.SerializerMethodField()

    class Meta:
        model = DashboardReport
        fields = (
            "built_at",
            "next_build_at",
            "totals",
            "active_triggers",
            "live_sessions",
            "knowledge_usage",
        )

    def get_next_build_at(self, report):
        return None

    def get_totals(self, report):
        return {field: getattr(report, field) for field in TOTAL_FIELDS}

    def get_active_triggers(self, report):
        rows = DashboardActiveTrigger.objects.filter(org_id=report.org_id).order_by(
            "trigger_type", "graph_name", "node_name"
        )
        return DashboardActiveTriggerSerializer(rows, many=True).data

    def get_live_sessions(self, report):
        rows = DashboardLiveSession.objects.filter(org_id=report.org_id).order_by("created_at")
        return DashboardLiveSessionSerializer(rows, many=True).data

    def get_knowledge_usage(self, report):
        rows = DashboardKnowledgeUsage.objects.filter(org_id=report.org_id).order_by("rag_type")
        return DashboardKnowledgeUsageSerializer(rows, many=True).data
