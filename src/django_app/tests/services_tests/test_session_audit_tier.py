"""The session payload tells crew how long the session's audit events are kept."""

import pytest
from src.shared.retention import DataType, RetentionPolicy, RetentionRule

from rbac.models import Organization, OrganizationRetention
from tables.models import Graph, PythonCode
from tables.models.graph_models import Edge, PythonNode, StartNode
from tables.services.session_manager_service import SessionManagerService
from tables.services.trigger_spec import TriggerSpec

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


def _audit_policy(default_days: int, max_days: int | None) -> RetentionPolicy:
    return RetentionPolicy(
        rules={
            DataType.SESSIONS: RetentionRule(default_days=30, max_days=None),
            DataType.CONVERSATIONS: RetentionRule(default_days=30, max_days=None),
            DataType.AUDIT: RetentionRule(default_days=default_days, max_days=max_days),
        }
    )


@pytest.fixture(autouse=True)
def retention_policy(settings):
    settings.RETENTION_POLICY = _audit_policy(default_days=365, max_days=None)


def _session_data_for(org: Organization):
    graph = Graph.objects.create(name="audit-tier-graph", org=org)
    start_node = StartNode.objects.create(graph=graph, variables={"variables": {}})
    python_node = PythonNode.objects.create(
        graph=graph,
        python_code=PythonCode.objects.create(
            code="def main(**kwargs):\n    return 1\n", entrypoint="main"
        ),
        node_name="python",
    )
    Edge.objects.create(graph=graph, start_node_id=start_node.pk, end_node_id=python_node.pk)

    service = SessionManagerService()
    session = service.create_session(
        graph=graph, start_node=start_node, variables={}, trigger=TriggerSpec.manual()
    )
    return service.create_session_data(session=session, start_node=start_node)


@pytest.mark.django_db
def test_session_data_carries_effective_audit_retention(acme):
    OrganizationRetention.objects.create(org=acme, audit_days=90)

    assert _session_data_for(acme).audit_retention_days == 90


@pytest.mark.django_db
def test_org_without_retention_row_gets_the_instance_default(acme):
    assert _session_data_for(acme).audit_retention_days == 365


@pytest.mark.django_db
def test_org_choice_above_a_lowered_cap_is_clamped(acme, settings):
    OrganizationRetention.objects.create(org=acme, audit_days=365)
    settings.RETENTION_POLICY = _audit_policy(default_days=30, max_days=180)

    assert _session_data_for(acme).audit_retention_days == 180


@pytest.mark.django_db
def test_another_orgs_retention_does_not_apply(acme, beta):
    OrganizationRetention.objects.create(org=beta, audit_days=30)

    assert _session_data_for(acme).audit_retention_days == 365
