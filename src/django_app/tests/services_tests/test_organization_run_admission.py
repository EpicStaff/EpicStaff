"""A deactivated organization starts no run, through the checks the apps really register."""

import pytest
from loguru import logger

from rbac.governance.organization_run_admission import OrganizationInactiveError
from rbac.models import Organization
from tables.models import Graph, PythonCode, Session
from tables.models.graph_models import StartNode, WebhookTriggerNode
from tables.models.webhook_models import WebhookTrigger
from tables.services.run_admission import (
    RunKind,
    RunSubject,
    assert_run_admitted,
    assert_still_admitted,
)
from tables.services.webhook_trigger_service import WebhookTriggerService
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403
from tests.services_tests.session_trigger_creation_test import _stub_publish

pytestmark = [pytest.mark.django_db]


@pytest.fixture
def acme_flow(acme):
    graph = Graph.objects.create(name="acme-flow", org=acme)
    StartNode.objects.create(graph=graph, variables={"variables": {}})
    return graph


def _deactivate(org):
    Organization.objects.filter(pk=org.pk).update(is_active=False)


def _subject(graph):
    return RunSubject(RunKind.FLOW, graph.pk, graph.org_id)


def test_a_run_of_an_active_organization_is_admitted(acme_flow):
    assert_still_admitted(assert_run_admitted(_subject(acme_flow)))


def test_a_run_of_a_deactivated_organization_is_refused(acme_flow):
    _deactivate(acme_flow.org)

    with pytest.raises(OrganizationInactiveError):
        assert_run_admitted(_subject(acme_flow))


def test_a_run_whose_organization_is_deactivated_while_it_is_built_is_refused_again(acme_flow):
    admission = assert_run_admitted(_subject(acme_flow))
    _deactivate(acme_flow.org)

    with pytest.raises(OrganizationInactiveError):
        assert_still_admitted(admission)


def test_a_superadmin_cannot_run_a_flow_of_a_deactivated_organization(
    acme_flow, client_as, superadmin, monkeypatch
):
    _deactivate(acme_flow.org)
    _stub_publish(monkeypatch)

    response = client_as(superadmin).post(
        "/api/run-session/", {"graph_id": acme_flow.pk}, format="json"
    )

    assert response.status_code == 409, response.content
    assert response.json()["code"] == "organization_inactive"
    assert not Session.objects.exists()


def test_a_webhook_of_a_deactivated_organization_starts_no_session(acme_flow, monkeypatch):
    trigger = WebhookTrigger.objects.create(path="inactive-org-hook", org=acme_flow.org)
    WebhookTriggerNode.objects.create(
        graph=acme_flow,
        node_name="hook",
        webhook_trigger=trigger,
        python_code=PythonCode.objects.create(code="def main(**kwargs): ..."),
    )
    _deactivate(acme_flow.org)
    _stub_publish(monkeypatch)
    warnings: list[str] = []
    sink_id = logger.add(lambda message: warnings.append(message.record["message"]), level="WARNING")
    try:
        WebhookTriggerService().handle_webhook_trigger(path="inactive-org-hook", payload={})
    finally:
        logger.remove(sink_id)

    assert not Session.objects.exists()
    refusals = [line for line in warnings if line.startswith("Run refused:")]
    assert len(refusals) == 1
    assert refusals[0].endswith("(organization_inactive)")
