import pytest

from tables.models.graph_models import (
    Graph,
    GraphOrganizationUser,
    StartNode,
)
from tables.models.rbac_models import OrganizationUser
from tables.services.session_manager_service import SessionManagerService


@pytest.mark.django_db
def test_create_session_uses_passed_graph_user(default_org, regular_user):
    graph = Graph.objects.create(name="cs", org=default_org)
    StartNode.objects.create(graph=graph, variables={"variables": {}})
    membership = OrganizationUser.objects.get(user=regular_user, org=default_org)
    gu = GraphOrganizationUser.objects.create(graph=graph, organization_user=membership)

    session = SessionManagerService().create_session(
        graph_id=graph.id, variables={}, graph_user=gu
    )
    assert session.graph_user_id == gu.id


def test_run_session_no_longer_has_choose_variables():
    assert not hasattr(SessionManagerService, "choose_variables")
