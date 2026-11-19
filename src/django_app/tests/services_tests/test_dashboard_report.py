from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rbac.models import Organization, Role
from tables.models import (
    BaseRagType,
    DashboardActiveTrigger,
    DashboardKnowledgeUsage,
    DashboardLiveSession,
    DashboardRagType,
    DashboardReport,
    Graph,
    ScheduleTriggerNode,
    Session,
    SourceCollection,
)
from tables.models.knowledge_models import NaiveRag
from tables.services.dashboard import report as report_service
from tables.services.dashboard.report import build_all_reports, build_report

pytestmark = pytest.mark.django_db


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Acme")


@pytest.fixture
def other_org(db):
    return Organization.objects.create(name="Globex")


@pytest.fixture
def flow(org):
    return Graph.objects.create(name="Orders", org=org)


def _collection(org, name, *rag_types):
    collection = SourceCollection.objects.create(collection_name=name, org=org)
    for rag_type in rag_types:
        BaseRagType.objects.create(rag_type=rag_type, source_collection=collection)
    return collection


def _session(flow, status, parent=None):
    return Session.objects.create(
        graph=flow, status=status, status_updated_at=timezone.now(), parent_session=parent
    )


def test_binned_flows_and_other_orgs_are_not_counted(org, other_org, flow):
    Graph.objects.create(name="Old", org=org).delete()
    Graph.objects.create(name="Foreign", org=other_org)

    assert build_report(org.id).flows == 1


def test_roles_are_split_into_builtin_and_custom(org):
    Role.objects.create(name="Support", org=org)

    report = build_report(org.id)

    assert report.roles_custom == 1
    assert report.roles_builtin == Role.objects.filter(is_built_in=True).count()


def test_collection_with_both_rag_types_counts_once_in_total(org):
    _collection(org, "both", BaseRagType.RagType.NAIVE, BaseRagType.RagType.GRAPH)
    _collection(org, "naive", BaseRagType.RagType.NAIVE)
    _collection(org, "empty")

    report = build_report(org.id)

    assert report.knowledge_total == 3
    assert report.knowledge_naive == 2
    assert report.knowledge_graph == 1
    assert report.knowledge_not_indexed == 1


def test_active_triggers_skip_disabled_schedules_and_binned_flows(org, flow):
    next_run = timezone.now() + timedelta(hours=1)
    ScheduleTriggerNode.objects.create(
        graph=flow, node_name="Hourly", is_active=True, next_run_date_time=next_run
    )
    ScheduleTriggerNode.objects.create(graph=flow, node_name="Disabled")
    binned_flow = Graph.objects.create(name="Binned", org=org)
    ScheduleTriggerNode.objects.create(graph=binned_flow, node_name="Gone", is_active=True)
    binned_flow.delete()

    build_report(org.id)

    trigger = DashboardActiveTrigger.objects.get(org=org)
    assert (trigger.node_name, trigger.graph_name, trigger.next_run_at) == (
        "Hourly",
        "Orders",
        next_run,
    )


def test_live_sessions_are_unfinished_root_sessions(org, flow):
    root = _session(flow, Session.SessionStatus.WAIT_FOR_USER)
    _session(flow, Session.SessionStatus.RUN, parent=root)
    _session(flow, Session.SessionStatus.END)

    build_report(org.id)

    assert list(DashboardLiveSession.objects.values_list("session_id", "status")) == [
        (root.id, Session.SessionStatus.WAIT_FOR_USER)
    ]


def test_knowledge_usage_sums_known_cost_and_counts_unknown(org):
    usages = (
        {"total": {"embedding_tokens": 100, "cost_usd": 0.25}},
        {"total": {"embedding_tokens": 50, "cost_usd": None}},
        {},
    )
    for index, usage in enumerate(usages):
        collection = _collection(org, f"c{index}", BaseRagType.RagType.NAIVE)
        NaiveRag.objects.create(
            base_rag_type=collection.rag_types.get(), indexing_usage=usage
        )

    build_report(org.id)

    naive = DashboardKnowledgeUsage.objects.get(org=org, rag_type=DashboardRagType.NAIVE)
    assert naive.collections == 3
    assert naive.embedding_tokens == 150
    assert naive.cost_usd == Decimal("0.25")
    assert naive.unknown_cost_count == 1
    assert DashboardKnowledgeUsage.objects.get(org=org, rag_type=DashboardRagType.GRAPH)


def test_second_build_replaces_rows_instead_of_adding(org, flow):
    ScheduleTriggerNode.objects.create(graph=flow, node_name="Hourly", is_active=True)
    first = build_report(org.id)

    second = build_report(org.id)

    assert DashboardReport.objects.filter(org=org).count() == 1
    assert DashboardActiveTrigger.objects.filter(org=org).count() == 1
    assert DashboardKnowledgeUsage.objects.filter(org=org).count() == 2
    assert second.built_at > first.built_at


def test_one_failing_org_does_not_stop_the_others(org, other_org, monkeypatch):
    real_build = report_service.build_report

    def build_or_fail(org_id):
        if org_id == org.id:
            raise RuntimeError("boom")
        return real_build(org_id)

    monkeypatch.setattr(report_service, "build_report", build_or_fail)

    built, failed = build_all_reports()

    assert failed == [org.id]
    assert other_org.id in built
    assert DashboardReport.objects.filter(org=other_org).exists()
