from django.contrib.postgres.fields import ArrayField
from django.db import models

DURATION_BUCKET_UPPER_SECONDS = (
    1,
    5,
    15,
    30,
    60,
    120,
    300,
    900,
    1800,
    3600,
    10800,
    21600,
    43200,
    86400,
)
DURATION_BUCKET_COUNT = len(DURATION_BUCKET_UPPER_SECONDS) + 1


class DashboardReport(models.Model):
    org = models.OneToOneField(
        "rbac.Organization",
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="dashboard_report",
    )
    built_at = models.DateTimeField()
    rolled_up_through = models.DateField(null=True, blank=True)

    agents = models.PositiveIntegerField(default=0)
    flows = models.PositiveIntegerField(default=0)
    roles_builtin = models.PositiveIntegerField(default=0)
    roles_custom = models.PositiveIntegerField(default=0)
    users = models.PositiveIntegerField(default=0)
    knowledge_total = models.PositiveIntegerField(default=0)
    knowledge_naive = models.PositiveIntegerField(default=0)
    knowledge_graph = models.PositiveIntegerField(default=0)
    knowledge_not_indexed = models.PositiveIntegerField(default=0)
    files = models.PositiveIntegerField(default=0)
    files_bytes = models.PositiveBigIntegerField(default=0)
    llm_configs = models.PositiveIntegerField(default=0)
    embedding_configs = models.PositiveIntegerField(default=0)
    realtime_configs = models.PositiveIntegerField(default=0)
    tools_python = models.PositiveIntegerField(default=0)
    tools_mcp = models.PositiveIntegerField(default=0)
    plugins = models.PositiveIntegerField(default=0)


class DashboardTriggerType(models.TextChoices):
    SCHEDULE = "schedule", "Schedule"
    WEBHOOK = "webhook", "Webhook"
    TELEGRAM = "telegram", "Telegram"


class DashboardActiveTrigger(models.Model):
    org = models.ForeignKey(
        "rbac.Organization",
        on_delete=models.CASCADE,
        related_name="dashboard_active_triggers",
    )
    trigger_type = models.CharField(max_length=16, choices=DashboardTriggerType.choices)
    node_id = models.BigIntegerField()
    node_name = models.CharField(max_length=255)
    graph_id = models.BigIntegerField()
    graph_name = models.CharField(max_length=255)
    next_run_at = models.DateTimeField(null=True, blank=True)


class DashboardLiveSession(models.Model):
    org = models.ForeignKey(
        "rbac.Organization",
        on_delete=models.CASCADE,
        related_name="dashboard_live_sessions",
    )
    session_id = models.BigIntegerField()
    graph_id = models.BigIntegerField()
    graph_name = models.CharField(max_length=255)
    status = models.CharField(max_length=32)
    created_at = models.DateTimeField()


class DashboardRagType(models.TextChoices):
    NAIVE = "naive", "Naive RAG"
    GRAPH = "graph", "GraphRAG"


class DashboardKnowledgeUsage(models.Model):
    org = models.ForeignKey(
        "rbac.Organization",
        on_delete=models.CASCADE,
        related_name="dashboard_knowledge_usage",
    )
    rag_type = models.CharField(max_length=16, choices=DashboardRagType.choices)
    collections = models.PositiveIntegerField(default=0)
    embedding_tokens = models.PositiveBigIntegerField(default=0)
    llm_input_tokens = models.PositiveBigIntegerField(default=0)
    llm_output_tokens = models.PositiveBigIntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=18, decimal_places=6, default=0)
    unknown_cost_count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["org", "rag_type"],
                name="unique_dashboard_knowledge_usage_per_rag_type",
            ),
        ]


class DashboardSessionDailyStat(models.Model):
    org = models.ForeignKey(
        "rbac.Organization",
        on_delete=models.CASCADE,
        related_name="dashboard_session_daily_stats",
    )
    day = models.DateField()
    graph_id = models.BigIntegerField()
    graph_name = models.CharField(max_length=255)
    status = models.CharField(max_length=32)
    trigger_type = models.CharField(max_length=32)
    source_kind = models.CharField(max_length=32)
    source_ref = models.CharField(max_length=64, blank=True, default="")
    source_name = models.CharField(max_length=256, blank=True, default="")
    is_test = models.BooleanField(default=False)

    session_count = models.PositiveIntegerField(default=0)
    duration_seconds_sum = models.PositiveBigIntegerField(default=0)
    duration_histogram = ArrayField(models.PositiveIntegerField(), size=DURATION_BUCKET_COUNT)
    prompt_tokens = models.PositiveBigIntegerField(default=0)
    completion_tokens = models.PositiveBigIntegerField(default=0)
    cached_prompt_tokens = models.PositiveBigIntegerField(default=0)
    total_tokens = models.PositiveBigIntegerField(default=0)
    successful_requests = models.PositiveBigIntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=18, decimal_places=6, default=0)
    unknown_cost_count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "org",
                    "day",
                    "graph_id",
                    "status",
                    "trigger_type",
                    "source_kind",
                    "source_ref",
                    "is_test",
                ],
                name="unique_dashboard_session_daily_stat",
            ),
        ]
