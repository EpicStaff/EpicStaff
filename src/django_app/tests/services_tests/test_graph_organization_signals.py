import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext

from rbac.models import OrganizationUser
from tables.models.graph_models import Graph, GraphOrganization, GraphOrganizationUser


@pytest.fixture
def graph_organization(default_org):
    graph = Graph.objects.create(name="persistent", org=default_org)
    yield GraphOrganization.objects.create(graph=graph, user_variables={"theme": "dark"})


@pytest.fixture
def graph_users(graph_organization, default_org, org_admin_role):
    graph_users = []
    for index in range(3):
        user = get_user_model().objects.create_user(
            email=f"flow-user-{index}@example.com", password="UserStrongPass123!"
        )
        membership = OrganizationUser.objects.create(
            user=user, org=default_org, role=org_admin_role
        )
        graph_users.append(
            GraphOrganizationUser.objects.create(
                graph=graph_organization.graph,
                organization_user=membership,
                persistent_variables={"theme": "light"},
            )
        )
    yield graph_users


@pytest.mark.django_db
def test_saving_only_persistent_variables_does_not_walk_the_flow_users(
    graph_organization, graph_users
):
    graph_organization.user_variables = {"theme": "dark", "language": "en"}
    graph_organization.persistent_variables = {"counter": 1}

    with CaptureQueriesContext(connection) as captured:
        graph_organization.save(update_fields=["persistent_variables"])

    assert len(captured.captured_queries) == 1
    for graph_user in graph_users:
        graph_user.refresh_from_db()
        assert graph_user.persistent_variables == {"theme": "light"}


@pytest.mark.parametrize("update_fields", [None, ["user_variables"]])
@pytest.mark.django_db
def test_saving_user_variables_seeds_new_keys_into_every_flow_user(
    graph_organization, graph_users, update_fields
):
    graph_organization.user_variables = {"theme": "dark", "language": "en"}

    graph_organization.save(update_fields=update_fields)

    for graph_user in graph_users:
        graph_user.refresh_from_db()
        assert graph_user.persistent_variables == {"theme": "light", "language": "en"}


@pytest.mark.django_db
def test_syncing_flow_users_reads_their_emails_without_a_query_per_user(
    graph_organization, graph_users
):
    graph_organization.user_variables = {"theme": "dark", "language": "en"}

    with CaptureQueriesContext(connection) as captured:
        graph_organization.save(update_fields=["user_variables"])

    selects = [
        query["sql"] for query in captured.captured_queries if query["sql"].startswith("SELECT")
    ]
    # One read of the flow users joined to their memberships and accounts; no lazy
    # lookup of a membership or an account per user.
    assert len(selects) == 1
    assert '"tables_graphorganizationuser"' in selects[0]
    assert '"rbac_user"' in selects[0]
