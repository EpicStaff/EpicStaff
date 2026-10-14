"""GET /api/webhook-triggers/{id}/flows/: which flows hold a trigger node on a webhook trigger.

The settings page asks before opening the edit dialog, so a user who may edit webhooks
but not run flows learns which flows make the edit need flows:RUN. `flow_count` counts
the distinct live flows with a live webhook or Telegram trigger node on the trigger;
`flows` names the first 50 by name, then id, and only for a caller who may read flows.
The action is a webhooks READ; another org's trigger is a 404.
"""

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from rbac.models import OrganizationUser, Role, RolePermission
from rbac.models.enums import Permission, ResourceType
from tables.models import Graph, PythonCode, WebhookTrigger
from tables.models.graph_models import TelegramTriggerNode, WebhookTriggerNode
from tables.services.webhook_trigger_service import WebhookTriggerService
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

# Generous on purpose: the point is that it doesn't grow with the number of flows.
MAX_QUERIES = 15


def _client(client_as, django_user_model, org, grants, name):
    role = Role.objects.create(name=name, org=org, is_built_in=False)
    for resource_type, permissions in grants.items():
        RolePermission.objects.create(
            role=role, resource_type=resource_type, permissions=int(permissions)
        )
    user = django_user_model.objects.create_user(
        email=f"{name}@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org, role=role)
    client = client_as(user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client


@pytest.fixture(autouse=True)
def republished(mocker, mock_telegram_service):
    """Attaching a trigger node republishes tunnels and registers Telegram; both mocked."""
    mocker.patch.object(WebhookTriggerService, "register_webhooks", return_value=True)


@pytest.fixture
def flows_reader_client(client_as, django_user_model, acme):
    """Reads webhooks and flows; cannot run flows."""
    return _client(
        client_as,
        django_user_model,
        acme,
        {ResourceType.WEBHOOKS: Permission.READ, ResourceType.FLOWS: Permission.READ},
        "wtf-flows-reader",
    )


@pytest.fixture
def webhooks_only_client(client_as, django_user_model, acme):
    """Manages webhooks; holds nothing on flows."""
    return _client(
        client_as,
        django_user_model,
        acme,
        {ResourceType.WEBHOOKS: Permission.READ | Permission.UPDATE},
        "wtf-webhooks-only",
    )


@pytest.fixture
def no_webhooks_client(client_as, django_user_model, acme):
    return _client(
        client_as,
        django_user_model,
        acme,
        {ResourceType.FLOWS: Permission.READ | Permission.RUN},
        "wtf-no-webhooks",
    )


@pytest.fixture
def superadmin_client(client_as, superadmin, acme):
    client = client_as(superadmin)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


def _trigger(org, path):
    return WebhookTrigger.objects.create(path=path, org=org, provider_type=None)


def _flow(org, name):
    return Graph.objects.create(name=name, org=org)


def _attach_webhook_node(graph, trigger):
    return WebhookTriggerNode.objects.create(
        graph=graph,
        node_name="Incoming",
        webhook_trigger=trigger,
        python_code=PythonCode.objects.create(code="def main(**kwargs): ..."),
    )


def _attach_telegram_node(graph, trigger):
    return TelegramTriggerNode.objects.create(graph=graph, node_name="Bot", webhook_trigger=trigger)


def _flows_url(trigger):
    return reverse("webhooktrigger-flows-using-trigger", args=[trigger.id])


@pytest.mark.django_db
class TestFlowsUsingTrigger:
    def test_trigger_without_nodes(self, flows_reader_client, acme):
        trigger = _trigger(acme, "wtf-empty")
        _attach_webhook_node(_flow(acme, "Uses another trigger"), _trigger(acme, "wtf-other"))

        response = flows_reader_client.get(_flows_url(trigger))

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.data == {"flow_count": 0, "flows": []}

    @pytest.mark.parametrize(
        "attach", [_attach_webhook_node, _attach_telegram_node], ids=["webhook", "telegram"]
    )
    def test_one_flow_with_a_trigger_node(self, flows_reader_client, acme, attach):
        trigger = _trigger(acme, "wtf-one")
        flow = _flow(acme, "Inbound orders")
        attach(flow, trigger)

        response = flows_reader_client.get(_flows_url(trigger))

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.data == {
            "flow_count": 1,
            "flows": [{"id": flow.id, "name": "Inbound orders"}],
        }

    def test_a_flow_with_both_node_types_counts_once(self, flows_reader_client, acme):
        trigger = _trigger(acme, "wtf-both")
        flow = _flow(acme, "Both kinds")
        _attach_webhook_node(flow, trigger)
        _attach_webhook_node(flow, trigger)
        _attach_telegram_node(flow, trigger)

        response = flows_reader_client.get(_flows_url(trigger))

        assert response.data == {"flow_count": 1, "flows": [{"id": flow.id, "name": "Both kinds"}]}

    def test_flows_are_ordered_by_name_then_id(self, flows_reader_client, acme):
        trigger = _trigger(acme, "wtf-ordered")
        support = _flow(acme, "Support bot")
        orders = _flow(acme, "Inbound orders")
        _attach_telegram_node(support, trigger)
        _attach_webhook_node(orders, trigger)
        _attach_webhook_node(_flow(acme, "Unrelated"), _trigger(acme, "wtf-unrelated"))

        response = flows_reader_client.get(_flows_url(trigger))

        assert response.data == {
            "flow_count": 2,
            "flows": [
                {"id": orders.id, "name": "Inbound orders"},
                {"id": support.id, "name": "Support bot"},
            ],
        }

    def test_soft_deleted_nodes_and_flows_do_not_count(self, flows_reader_client, acme):
        trigger = _trigger(acme, "wtf-soft-deleted")
        node = _attach_webhook_node(_flow(acme, "Node deleted"), trigger)
        WebhookTriggerNode.all_objects.filter(pk=node.pk).update(
            is_soft_deleted=True, soft_deleted_at=timezone.now()
        )
        deleted_flow = _flow(acme, "Flow deleted")
        _attach_telegram_node(deleted_flow, trigger)
        Graph.all_objects.filter(pk=deleted_flow.pk).update(
            is_soft_deleted=True, soft_deleted_at=timezone.now()
        )

        response = flows_reader_client.get(_flows_url(trigger))

        assert response.data == {"flow_count": 0, "flows": []}

    def test_more_flows_than_the_limit(self, flows_reader_client, acme):
        trigger = _trigger(acme, "wtf-many")
        graphs = Graph.objects.bulk_create(
            Graph(name=f"Flow {index:03d}", org=acme) for index in range(55)
        )
        TelegramTriggerNode.objects.bulk_create(
            TelegramTriggerNode(graph=graph, node_name="Bot", webhook_trigger=trigger)
            for graph in graphs
        )

        response = flows_reader_client.get(_flows_url(trigger))

        assert response.data["flow_count"] == 55
        assert [flow["name"] for flow in response.data["flows"]] == [
            f"Flow {index:03d}" for index in range(50)
        ]


@pytest.mark.django_db
class TestAccess:
    def test_without_flows_read_the_names_are_withheld(self, webhooks_only_client, acme):
        trigger = _trigger(acme, "wtf-hidden")
        _attach_webhook_node(_flow(acme, "Secret plans"), trigger)
        _attach_telegram_node(_flow(acme, "Other plans"), trigger)

        response = webhooks_only_client.get(_flows_url(trigger))

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.data == {"flow_count": 2, "flows": []}

    def test_without_webhooks_read_is_403(self, no_webhooks_client, acme):
        trigger = _trigger(acme, "wtf-forbidden")

        response = no_webhooks_client.get(_flows_url(trigger))

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content

    def test_superadmin_sees_the_names(self, superadmin_client, acme):
        trigger = _trigger(acme, "wtf-superadmin")
        flow = _flow(acme, "Superadmin view")
        _attach_webhook_node(flow, trigger)

        response = superadmin_client.get(_flows_url(trigger))

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.data == {
            "flow_count": 1,
            "flows": [{"id": flow.id, "name": "Superadmin view"}],
        }

    @pytest.mark.parametrize("client_fixture", ["flows_reader_client", "superadmin_client"])
    def test_another_orgs_trigger_is_404(self, request, beta, client_fixture):
        trigger = _trigger(beta, "wtf-beta")
        _attach_webhook_node(_flow(beta, "Beta flow"), trigger)

        response = request.getfixturevalue(client_fixture).get(_flows_url(trigger))

        assert response.status_code == status.HTTP_404_NOT_FOUND, response.content
        assert b"Beta flow" not in response.content

    def test_missing_org_header_is_400(self, client_as, admin_acme, acme):
        trigger = _trigger(acme, "wtf-no-header")

        response = client_as(admin_acme).get(_flows_url(trigger))

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert response.data["code"] == "org_context_required"


@pytest.mark.django_db
def test_query_count_does_not_grow_with_the_flows(
    flows_reader_client, acme, django_assert_max_num_queries
):
    trigger = _trigger(acme, "wtf-queries")
    _attach_webhook_node(_flow(acme, "First"), trigger)
    with django_assert_max_num_queries(MAX_QUERIES) as one_flow:
        flows_reader_client.get(_flows_url(trigger))

    for index in range(6):
        flow = _flow(acme, f"More {index}")
        _attach_webhook_node(flow, trigger)
        _attach_telegram_node(flow, trigger)
    with django_assert_max_num_queries(MAX_QUERIES) as seven_flows:
        response = flows_reader_client.get(_flows_url(trigger))

    assert response.data["flow_count"] == 7
    assert len(response.data["flows"]) == 7
    assert len(seven_flows) == len(one_flow)
