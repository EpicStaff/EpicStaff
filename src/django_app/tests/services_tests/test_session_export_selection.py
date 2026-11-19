"""Which sessions a filtered session export carries, and the cap on how many."""

import pytest
from rest_framework.exceptions import NotFound

from tables.exceptions import TooManySessionsToExportError
from tables.models import Graph, Session
from tables.services.session_export_selection import select_sessions_to_export
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

pytestmark = pytest.mark.django_db


@pytest.fixture
def flow(acme):
    return Graph.objects.create(name="Selected flow", org=acme)


def _session(flow, parent=None) -> Session:
    return Session.objects.create(
        graph=flow, status=Session.SessionStatus.END, variables={}, parent_session=parent
    )


@pytest.mark.parametrize(("sessions", "allowed"), [(2, True), (3, False)])
def test_a_filter_may_select_up_to_the_limit(acme, flow, sessions, allowed):
    created = [_session(flow).id for _ in range(sessions)]

    if allowed:
        assert select_sessions_to_export(acme.id, {}, limit=2) == created
    else:
        with pytest.raises(TooManySessionsToExportError):
            select_sessions_to_export(acme.id, {}, limit=2)


def test_only_top_level_sessions_of_the_org_are_selected(acme, beta, flow):
    parent = _session(flow)
    _session(flow, parent=parent)
    _session(Graph.objects.create(name="Theirs", org=beta))

    assert select_sessions_to_export(acme.id, {}, limit=10) == [parent.id]


def test_no_match_is_not_found(acme, flow):
    _session(flow)

    with pytest.raises(NotFound):
        select_sessions_to_export(acme.id, {"status": ["error"]}, limit=10)


def test_another_orgs_flow_is_not_found(acme, beta):
    foreign = Graph.objects.create(name="Theirs", org=beta)
    _session(foreign)

    with pytest.raises(NotFound):
        select_sessions_to_export(acme.id, {"graph_id": foreign.id}, limit=10)
