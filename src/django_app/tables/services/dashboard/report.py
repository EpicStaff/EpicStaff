from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal

from agents.models import AgentDefinition
from ai_models.models import EmbeddingConfig, LLMConfig
from django.db import connection, transaction
from django.db.models import Count, Exists, OuterRef, Q, Subquery, Sum
from django.utils import timezone
from loguru import logger
from rbac.models import Organization, OrganizationUser, Role
from tables.models import (
    BaseRagType,
    DashboardActiveTrigger,
    DashboardKnowledgeUsage,
    DashboardLiveSession,
    DashboardRagType,
    DashboardReport,
    DashboardTriggerType,
    ElevenLabsRealtimeConfig,
    GeminiRealtimeConfig,
    Graph,
    McpTool,
    OpenAIRealtimeConfig,
    PythonCodeTool,
    ScheduleTriggerNode,
    Session,
    SessionTrigger,
    SourceCollection,
    StorageFile,
    TelegramTriggerNode,
    WebhookTriggerNode,
)
from tables.models.knowledge_models import GraphRag, NaiveRag
from tables.services.dashboard.rollup import roll_up_since_last_build
from tables.services.dashboard.schedule import is_build_due

DASHBOARD_BUILD_LOCK = 4684

_plugin_counter: Callable[[int], int] | None = None


def register_plugin_counter(counter: Callable[[int], int]) -> None:
    global _plugin_counter
    _plugin_counter = counter


def count_totals(org_id: int) -> dict[str, int]:
    files = StorageFile.objects.filter(org_id=org_id, item_type="file").aggregate(
        count=Count("pk"), size=Sum("size")
    )
    knowledge = _count_knowledge(org_id)
    return {
        "agents": AgentDefinition.objects.filter(org_id=org_id).count(),
        "flows": Graph.objects.filter(org_id=org_id).count(),
        "roles_builtin": Role.objects.filter(is_built_in=True).count(),
        "roles_custom": Role.objects.filter(org_id=org_id).count(),
        "users": OrganizationUser.objects.filter(org_id=org_id).count(),
        "knowledge_total": knowledge["total"],
        "knowledge_naive": knowledge["naive"],
        "knowledge_graph": knowledge["graph"],
        "knowledge_not_indexed": knowledge["not_indexed"],
        "files": files["count"],
        "files_bytes": files["size"] or 0,
        "llm_configs": LLMConfig.objects.filter(org_id=org_id).count(),
        "embedding_configs": EmbeddingConfig.objects.filter(org_id=org_id).count(),
        "realtime_configs": sum(
            model.objects.filter(org_id=org_id).count()
            for model in (OpenAIRealtimeConfig, ElevenLabsRealtimeConfig, GeminiRealtimeConfig)
        ),
        "tools_python": PythonCodeTool.objects.filter(org_id=org_id, built_in=False).count(),
        "tools_mcp": McpTool.objects.filter(org_id=org_id).count(),
        "plugins": _plugin_counter(org_id) if _plugin_counter else 0,
    }


def _count_knowledge(org_id: int) -> dict[str, int]:
    def has_rag(rag_type: str) -> Exists:
        return Exists(
            BaseRagType.objects.filter(source_collection=OuterRef("pk"), rag_type=rag_type)
        )

    return (
        SourceCollection.objects.filter(org_id=org_id)
        .annotate(
            has_naive=has_rag(BaseRagType.RagType.NAIVE),
            has_graph=has_rag(BaseRagType.RagType.GRAPH),
        )
        .aggregate(
            total=Count("pk"),
            naive=Count("pk", filter=Q(has_naive=True)),
            graph=Count("pk", filter=Q(has_graph=True)),
            not_indexed=Count("pk", filter=Q(has_naive=False, has_graph=False)),
        )
    )


def collect_active_triggers(org_id: int) -> list[DashboardActiveTrigger]:
    sources = (
        (DashboardTriggerType.SCHEDULE, ScheduleTriggerNode.objects.filter(is_active=True)),
        (DashboardTriggerType.WEBHOOK, WebhookTriggerNode.objects.all()),
        (DashboardTriggerType.TELEGRAM, TelegramTriggerNode.objects.all()),
    )
    triggers = []
    for trigger_type, nodes in sources:
        last_event_at = Subquery(
            SessionTrigger.objects.filter(**{f"{trigger_type}_trigger_node": OuterRef("pk")})
            .filter(~Q(extra__contains={SessionTrigger.TEST_RUN_EXTRA_KEY: True}))
            .order_by("-session__created_at")
            .values("session__created_at")[:1]
        )
        nodes = (
            nodes.filter(graph__org_id=org_id, graph__active=True)
            .select_related("graph")
            .annotate(last_event_at=last_event_at)
        )
        triggers.extend(
            DashboardActiveTrigger(
                org_id=org_id,
                trigger_type=trigger_type,
                node_id=node.id,
                node_name=node.node_name,
                graph_id=node.graph_id,
                graph_name=node.graph.name,
                next_run_at=getattr(node, "next_run_date_time", None),
                last_event_at=node.last_event_at,
            )
            for node in nodes
        )
    return triggers


LIVE_STATUSES = (
    Session.SessionStatus.PENDING,
    Session.SessionStatus.RUN,
    Session.SessionStatus.WAIT_FOR_USER,
)


def collect_live_sessions(org_id: int) -> list[DashboardLiveSession]:
    sessions = (
        Session.objects.visible_in_org(org_id)
        .filter(status__in=LIVE_STATUSES, parent_session__isnull=True)
        .select_related("graph")
        .order_by("created_at")
    )
    return [
        DashboardLiveSession(
            org_id=org_id,
            session_id=session.id,
            graph_id=session.graph_id,
            graph_name=session.graph.name,
            status=session.status,
            created_at=session.created_at,
        )
        for session in sessions
    ]


def collect_knowledge_usage(org_id: int) -> list[DashboardKnowledgeUsage]:
    rags_by_type = (
        (DashboardRagType.NAIVE, NaiveRag),
        (DashboardRagType.GRAPH, GraphRag),
    )
    rows = []
    for rag_type, rag_model in rags_by_type:
        rags = rag_model.objects.filter(
            base_rag_type__source_collection__org_id=org_id,
            base_rag_type__active=True,
            base_rag_type__source_collection__active=True,
        ).values_list("base_rag_type__source_collection_id", "indexing_usage")
        row = DashboardKnowledgeUsage(org_id=org_id, rag_type=rag_type, cost_usd=Decimal(0))
        collection_ids = set()
        for collection_id, usage in rags:
            collection_ids.add(collection_id)
            total = (usage or {}).get("total")
            if not total:
                continue
            row.embedding_tokens += total.get("embedding_tokens") or 0
            row.llm_input_tokens += total.get("llm_input_tokens") or 0
            row.llm_output_tokens += total.get("llm_output_tokens") or 0
            if total.get("cost_usd") is None:
                row.unknown_cost_count += 1
            else:
                row.cost_usd += Decimal(str(total["cost_usd"]))
        row.collections = len(collection_ids)
        rows.append(row)
    return rows


def build_report(org_id: int) -> DashboardReport:
    now = timezone.now()
    today = now.date()
    rolled_up_through = (
        DashboardReport.objects.filter(org_id=org_id)
        .values_list("rolled_up_through", flat=True)
        .first()
    )
    roll_up_since_last_build(org_id, rolled_up_through, today)

    totals = count_totals(org_id)
    triggers = collect_active_triggers(org_id)
    live_sessions = collect_live_sessions(org_id)
    knowledge_usage = collect_knowledge_usage(org_id)

    with transaction.atomic():
        report, _ = DashboardReport.objects.update_or_create(
            org_id=org_id,
            defaults={"built_at": now, "rolled_up_through": today, **totals},
        )
        for model, rows in (
            (DashboardActiveTrigger, triggers),
            (DashboardLiveSession, live_sessions),
            (DashboardKnowledgeUsage, knowledge_usage),
        ):
            model.objects.filter(org_id=org_id).delete()
            model.objects.bulk_create(rows)
    return report


def build_all_reports() -> tuple[list[int], list[int]]:
    built, failed = [], []
    for org_id in Organization.objects.filter(is_active=True).values_list("id", flat=True):
        try:
            build_report(org_id)
            built.append(org_id)
        except Exception:
            logger.exception(f"Dashboard report build failed for org {org_id}")
            failed.append(org_id)
    return built, failed


def build_due_reports(now: datetime) -> tuple[list[int], list[int]]:
    schedules = Organization.objects.filter(is_active=True).values_list(
        "id",
        "dashboard_report__built_at",
        "config__dashboard_refresh_minutes",
        "config__dashboard_refresh_daily_at",
    )
    built, failed = [], []
    for org_id, built_at, chosen_minutes, daily_at in schedules:
        if not is_build_due(built_at, now, chosen_minutes, daily_at):
            continue
        try:
            with _org_build_lock(org_id) as locked:
                if locked and _built_at(org_id) == built_at:
                    build_report(org_id)
                    built.append(org_id)
        except Exception:
            logger.exception(f"Dashboard report build failed for org {org_id}")
            failed.append(org_id)
    return built, failed


def _built_at(org_id: int) -> datetime | None:
    return DashboardReport.objects.filter(org_id=org_id).values_list("built_at", flat=True).first()


@contextmanager
def _org_build_lock(org_id: int) -> Iterator[bool]:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s, %s)", [DASHBOARD_BUILD_LOCK, org_id])
        locked = cursor.fetchone()[0]
    try:
        yield locked
    finally:
        if locked:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s, %s)", [DASHBOARD_BUILD_LOCK, org_id])
