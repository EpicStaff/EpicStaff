import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from tables.models import Graph
from tables.models.session_models import Session
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


def _membership_queries(captured_queries):
    return [
        query["sql"]
        for query in captured_queries
        if 'FROM "rbac_organization_user"' in query["sql"]
    ]


@pytest.mark.django_db
def test_scoped_list_resolves_membership_once(client_as, member_only, acme):
    graph = Graph.objects.create(name="Gate cache flow", org=acme)
    session = Session.objects.create(
        graph=graph, status=Session.SessionStatus.PENDING, variables={}
    )
    client = client_as(member_only)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

    with CaptureQueriesContext(connection) as context:
        response = client.get("/api/sessions/?detailed=false")

    assert response.status_code == 200
    assert [row["id"] for row in response.data["results"]] == [session.id]
    # The gate's membership check plus the permission resolver's role lookup;
    # the view reuses the org the gate resolved instead of checking again.
    assert len(_membership_queries(context.captured_queries)) == 2
