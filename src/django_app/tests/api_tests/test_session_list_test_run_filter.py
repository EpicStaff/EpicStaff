"""GET /api/sessions/?is_test_run= — split editor test runs from real runs."""

import pytest
from django.urls import reverse
from rest_framework import status

from tables.models import Graph
from tables.models.session_models import Session, SessionTrigger
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

LIST_URL = reverse("session-list")
TEST_RUN_KEY = SessionTrigger.TEST_RUN_EXTRA_KEY


def _session(graph, *, trigger_type=None, extra=None, session_status=Session.SessionStatus.END):
    session = Session.objects.create(graph=graph, status=session_status, variables={})
    if trigger_type is not None:
        SessionTrigger.objects.create(session=session, trigger_type=trigger_type, extra=extra or {})
    return session


@pytest.fixture
def acme_client(client_as, admin_acme, acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


@pytest.fixture
def acme_graph(acme):
    return Graph.objects.create(name="test-run-filter-flow", org=acme)


@pytest.fixture
def sessions(acme_graph, beta):
    """One session per kind in acme, plus a test-run session in beta that must never leak."""
    beta_graph = Graph.objects.create(name="beta-test-run-filter-flow", org=beta)
    return {
        "manual": _session(acme_graph, trigger_type=SessionTrigger.TriggerType.MANUAL),
        "webhook_live": _session(
            acme_graph,
            trigger_type=SessionTrigger.TriggerType.WEBHOOK,
            extra={"path": "orders", "config_id": None},
        ),
        "webhook_flag_false": _session(
            acme_graph,
            trigger_type=SessionTrigger.TriggerType.WEBHOOK,
            extra={"path": "orders", TEST_RUN_KEY: False},
        ),
        "webhook_test_run": _session(
            acme_graph,
            trigger_type=SessionTrigger.TriggerType.WEBHOOK,
            extra={"path": "orders", TEST_RUN_KEY: True},
            session_status=Session.SessionStatus.ERROR,
        ),
        "telegram_test_run": _session(
            acme_graph,
            trigger_type=SessionTrigger.TriggerType.TELEGRAM,
            extra={"chat_id": 7, TEST_RUN_KEY: True},
        ),
        "no_trigger": _session(acme_graph),
        "beta_test_run": _session(
            beta_graph,
            trigger_type=SessionTrigger.TriggerType.WEBHOOK,
            extra={TEST_RUN_KEY: True},
        ),
    }


def _ids(response):
    assert response.status_code == status.HTTP_200_OK, response.content
    return {row["id"] for row in response.data["results"]}


def _pks(sessions, *names):
    return {sessions[name].pk for name in names}


ACME_TEST_RUN = ("webhook_test_run", "telegram_test_run")
ACME_NON_TEST_RUN = ("manual", "webhook_live", "webhook_flag_false", "no_trigger")


@pytest.mark.django_db
class TestSessionListIsTestRunFilter:
    @pytest.mark.parametrize("detailed", ["true", "false"])
    @pytest.mark.parametrize("raw_value", ["true", "True", "1"])
    def test_true_returns_only_test_run_sessions(self, acme_client, sessions, detailed, raw_value):
        response = acme_client.get(LIST_URL, {"is_test_run": raw_value, "detailed": detailed})

        assert _ids(response) == _pks(sessions, *ACME_TEST_RUN)
        assert response.data["count"] == len(ACME_TEST_RUN)

    @pytest.mark.parametrize("detailed", ["true", "false"])
    @pytest.mark.parametrize("raw_value", ["false", "FALSE", "0"])
    def test_false_returns_everything_else_including_sessions_without_trigger(
        self, acme_client, sessions, detailed, raw_value
    ):
        response = acme_client.get(LIST_URL, {"is_test_run": raw_value, "detailed": detailed})

        assert _ids(response) == _pks(sessions, *ACME_NON_TEST_RUN)
        assert response.data["count"] == len(ACME_NON_TEST_RUN)

    def test_true_and_false_partition_the_unfiltered_list(self, acme_client, sessions):
        all_ids = _ids(acme_client.get(LIST_URL))
        test_run_ids = _ids(acme_client.get(LIST_URL, {"is_test_run": "true"}))
        other_ids = _ids(acme_client.get(LIST_URL, {"is_test_run": "false"}))

        assert all_ids == _pks(sessions, *ACME_TEST_RUN, *ACME_NON_TEST_RUN)
        assert test_run_ids | other_ids == all_ids
        assert not test_run_ids & other_ids

    @pytest.mark.parametrize("query", [{}, {"is_test_run": ""}])
    def test_omitted_or_empty_does_not_filter(self, acme_client, sessions, query):
        assert _ids(acme_client.get(LIST_URL, query)) == _pks(
            sessions, *ACME_TEST_RUN, *ACME_NON_TEST_RUN
        )

    def test_composes_with_trigger_type(self, acme_client, sessions):
        test_run_webhooks = acme_client.get(
            LIST_URL, {"is_test_run": "true", "trigger_type": "webhook"}
        )
        live_webhooks = acme_client.get(
            LIST_URL, {"is_test_run": "false", "trigger_type": "webhook"}
        )

        assert _ids(test_run_webhooks) == _pks(sessions, "webhook_test_run")
        assert _ids(live_webhooks) == _pks(sessions, "webhook_live", "webhook_flag_false")

    def test_composes_with_status_and_graph_id(self, acme_client, sessions, acme_graph):
        other_graph = Graph.objects.create(name="other-flow", org=acme_graph.org)
        _session(
            other_graph,
            trigger_type=SessionTrigger.TriggerType.WEBHOOK,
            extra={TEST_RUN_KEY: True},
            session_status=Session.SessionStatus.ERROR,
        )

        response = acme_client.get(
            LIST_URL,
            {"is_test_run": "true", "status": "error", "graph_id": acme_graph.pk},
        )

        assert _ids(response) == _pks(sessions, "webhook_test_run")
        assert response.data["count"] == 1

    def test_other_orgs_test_run_session_never_appears(self, acme_client, sessions):
        test_run_ids = _ids(acme_client.get(LIST_URL, {"is_test_run": "true"}))
        other_ids = _ids(acme_client.get(LIST_URL, {"is_test_run": "false"}))

        assert sessions["beta_test_run"].pk not in test_run_ids | other_ids

    def test_filter_and_is_test_run_agree_on_non_boolean_flags(self, acme_client, acme_graph):
        non_boolean_flag_sessions = [
            _session(
                acme_graph,
                trigger_type=SessionTrigger.TriggerType.WEBHOOK,
                extra={TEST_RUN_KEY: flag_value},
            )
            for flag_value in (1, "true")
        ]

        test_run_ids = _ids(acme_client.get(LIST_URL, {"is_test_run": "true"}))
        other_ids = _ids(acme_client.get(LIST_URL, {"is_test_run": "false"}))

        for session in non_boolean_flag_sessions:
            assert session.pk not in test_run_ids
            assert session.pk in other_ids
            assert session.trigger.is_test_run is False

    @pytest.mark.parametrize("raw_value", ["yes", "maybe", "2", "truee"])
    def test_invalid_value_returns_400(self, acme_client, sessions, raw_value):
        response = acme_client.get(LIST_URL, {"is_test_run": raw_value})

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert response.data["message"].startswith("is_test_run:")
