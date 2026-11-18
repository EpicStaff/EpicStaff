"""Restoring from the recycle bin code that declares secrets needs secrets:USE.

A single restore refuses a caller without USE with 403
`code_with_secrets_requires_secrets_use_permission` and restores nothing, when the
binned item brings back, or back live, Python code declaring a secret: a flow whose
binned nodes have such code, a Python code tool whose code declares one, or a webhook
trigger whose restore reconnects live webhook trigger nodes with such code. A bulk
restore reports such an item as failed and restores the rest. A declared secret counts
while it is in the recycle bin too. The flows:USE trigger check runs first.
"""

import pytest
from rest_framework import status

from rbac.models.enums import Permission, ResourceType
from tables.exceptions import (
    CodeWithSecretsRequiresSecretsUsePermissionError,
    FlowWithTriggerNodesRequiresUsePermissionError,
)
from tables.models import Graph, PythonCode, PythonCodeTool, WebhookTrigger
from tables.models.graph_models import ClassificationDecisionTableNode, PythonNode, WebhookTriggerNode
from tables.services.secrets import secret_service
from tests.custom_role_fixtures import *  # noqa: F401,F403
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

DENIED_CODE = CodeWithSecretsRequiresSecretsUsePermissionError.default_code
FLOWS_URL = "/api/graphs/"
TOOLS_URL = "/api/python-code-tool/"
WEBHOOK_TRIGGERS_URL = "/api/webhook-triggers/"
WRITE = Permission.CREATE | Permission.READ | Permission.UPDATE | Permission.DELETE
CODE = 'def main(**kwargs):\n    return get_secret("BIN_KEY")\n'


def _grants(*, flows_use: bool, secrets: Permission):
    flows = WRITE | Permission.USE if flows_use else WRITE
    return {
        ResourceType.FLOWS: flows,
        ResourceType.WEBHOOKS: flows,
        ResourceType.TOOLS: WRITE,
        ResourceType.SECRETS: secrets,
    }


@pytest.fixture
def no_secrets_use_client(custom_role_client, acme):
    """Holds flows:USE, so the trigger check passes, but only READ on secrets."""
    return custom_role_client(
        acme, _grants(flows_use=True, secrets=Permission.READ), "bin-no-secrets-use"
    )


@pytest.fixture
def secrets_use_client(custom_role_client, acme):
    return custom_role_client(
        acme,
        _grants(flows_use=True, secrets=Permission.READ | Permission.USE),
        "bin-secrets-use",
    )


@pytest.fixture
def neither_use_client(custom_role_client, acme):
    return custom_role_client(
        acme, _grants(flows_use=False, secrets=Permission.READ), "bin-neither-use"
    )


@pytest.fixture
def secret(acme):
    return secret_service.create(text="sk-bin", org=acme, name="BIN_KEY")


def _declaring_code(secret):
    python_code = PythonCode.objects.create(code=CODE)
    python_code.secrets.set([secret])
    return python_code


def _flow_with_python_node(org, secret=None, name="Bin flow"):
    graph = Graph.objects.create(name=name, org=org)
    PythonNode.objects.create(
        graph=graph,
        node_name="work",
        python_code=_declaring_code(secret)
        if secret
        else PythonCode.objects.create(code="def main(**kwargs):\n    return 1\n"),
    )
    return graph


def _flow_with_cdt_post_code(org, secret):
    graph = Graph.objects.create(name="Bin CDT flow", org=org)
    ClassificationDecisionTableNode.objects.create(
        graph=graph, node_name="classify", post_python_code=_declaring_code(secret)
    )
    return graph


def _webhook_trigger_with_declaring_node(org, secret):
    """A webhook trigger whose live flow's webhook node declares `secret`."""
    trigger = WebhookTrigger.objects.create(path="bin-secret-path", org=org)
    WebhookTriggerNode.objects.create(
        graph=Graph.objects.create(name="Live hook flow", org=org),
        node_name="Incoming",
        webhook_trigger=trigger,
        python_code=_declaring_code(secret),
    )
    return trigger


def _declaring_tool(org, secret, name="Bin tool"):
    return PythonCodeTool.objects.create(
        name=name, description="reads a secret", python_code=_declaring_code(secret), org=org
    )


def _bin_restore(client, base_url, binned):
    return client.post(f"{base_url}{binned.pk}/restore/", format="json")


def _bin_bulk_restore(client, base_url, ids):
    return client.post(f"{base_url}recycle-bin/restore/", {"ids": ids}, format="json")


def _is_binned(row):
    return not type(row).all_objects.get(pk=row.pk).active


def _assert_refused(response):
    assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
    assert response.data["code"] == DENIED_CODE


def _binned_flow(org, secret):
    flow = _flow_with_python_node(org, secret)
    flow.delete()
    return FLOWS_URL, flow


def _binned_cdt_flow(org, secret):
    flow = _flow_with_cdt_post_code(org, secret)
    flow.delete()
    return FLOWS_URL, flow


def _binned_tool(org, secret):
    tool = _declaring_tool(org, secret)
    tool.delete()
    return TOOLS_URL, tool


def _binned_webhook_trigger(org, secret):
    trigger = _webhook_trigger_with_declaring_node(org, secret)
    trigger.delete()
    return WEBHOOK_TRIGGERS_URL, trigger


BINNED_SECRET_CODE = [
    pytest.param(_binned_flow, id="flow"),
    pytest.param(_binned_cdt_flow, id="flow-cdt-post-code"),
    pytest.param(_binned_tool, id="python-code-tool"),
    pytest.param(_binned_webhook_trigger, id="webhook-trigger"),
]


@pytest.mark.django_db
class TestSingleRestore:
    @pytest.mark.parametrize("bin_item", BINNED_SECRET_CODE)
    def test_without_use_is_refused_and_restores_nothing(
        self, no_secrets_use_client, acme, secret, bin_item
    ):
        base_url, binned = bin_item(acme, secret)

        response = _bin_restore(no_secrets_use_client, base_url, binned)

        _assert_refused(response)
        assert _is_binned(binned)

    @pytest.mark.parametrize("bin_item", BINNED_SECRET_CODE)
    def test_with_use_restores(self, secrets_use_client, acme, secret, bin_item):
        base_url, binned = bin_item(acme, secret)

        response = _bin_restore(secrets_use_client, base_url, binned)

        assert response.status_code == status.HTTP_200_OK, response.content
        assert not _is_binned(binned)

    def test_a_flow_without_secret_code_restores_without_use(self, no_secrets_use_client, acme):
        flow = _flow_with_python_node(acme)
        flow.delete()

        response = _bin_restore(no_secrets_use_client, FLOWS_URL, flow)

        assert response.status_code == status.HTTP_200_OK, response.content
        assert not _is_binned(flow)

    def test_a_binned_declared_secret_still_counts(self, no_secrets_use_client, acme, secret):
        """A binned secret stays linked, and comes back readable once it is restored."""
        flow = _flow_with_python_node(acme, secret)
        flow.delete()
        secret.delete()

        response = _bin_restore(no_secrets_use_client, FLOWS_URL, flow)

        _assert_refused(response)

    def test_a_declaring_node_binned_before_the_flow_does_not_count(
        self, no_secrets_use_client, acme, secret
    ):
        """It stays in the bin when the flow comes back, so no secret code comes back."""
        flow = _flow_with_python_node(acme, secret)
        PythonNode.objects.get(graph=flow).delete()
        flow.delete()

        response = _bin_restore(no_secrets_use_client, FLOWS_URL, flow)

        assert response.status_code == status.HTTP_200_OK, response.content

    def test_the_trigger_refusal_wins_when_both_apply(self, neither_use_client, acme, secret):
        flow = Graph.objects.create(name="Hook flow", org=acme)
        WebhookTriggerNode.objects.create(
            graph=flow,
            node_name="Incoming",
            webhook_trigger=WebhookTrigger.objects.create(path="both-path", org=acme),
            python_code=_declaring_code(secret),
        )
        flow.delete()

        response = _bin_restore(neither_use_client, FLOWS_URL, flow)

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
        assert response.data["code"] == FlowWithTriggerNodesRequiresUsePermissionError.default_code
        assert _is_binned(flow)


@pytest.mark.django_db
class TestBulkRestore:
    @pytest.mark.parametrize("bin_item", BINNED_SECRET_CODE)
    def test_without_use_the_item_fails_and_stays_binned(
        self, no_secrets_use_client, acme, secret, bin_item
    ):
        base_url, binned = bin_item(acme, secret)

        response = _bin_bulk_restore(no_secrets_use_client, base_url, [binned.pk])

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.data["restored"] == []
        assert response.data["failed"] == [
            {
                "id": binned.pk,
                "name": getattr(binned, "path" if base_url == WEBHOOK_TRIGGERS_URL else "name"),
                "message": CodeWithSecretsRequiresSecretsUsePermissionError.default_detail,
            }
        ]
        assert _is_binned(binned)

    @pytest.mark.parametrize("bin_item", BINNED_SECRET_CODE)
    def test_with_use_the_item_restores(self, secrets_use_client, acme, secret, bin_item):
        base_url, binned = bin_item(acme, secret)

        response = _bin_bulk_restore(secrets_use_client, base_url, [binned.pk])

        assert response.status_code == status.HTTP_200_OK, response.content
        assert [restored["id"] for restored in response.data["restored"]] == [binned.pk]
        assert not _is_binned(binned)

    def test_without_use_the_other_items_still_restore(self, no_secrets_use_client, acme, secret):
        declaring = _flow_with_python_node(acme, secret, name="Declaring")
        plain = _flow_with_python_node(acme, name="Plain")
        declaring.delete()
        plain.delete()

        response = _bin_bulk_restore(no_secrets_use_client, FLOWS_URL, [declaring.pk, plain.pk])

        assert response.status_code == status.HTTP_200_OK, response.content
        assert [restored["id"] for restored in response.data["restored"]] == [plain.pk]
        assert [failure["id"] for failure in response.data["failed"]] == [declaring.pk]
        assert _is_binned(declaring)
        assert not _is_binned(plain)


@pytest.mark.django_db
class TestWebhookTriggerRestore:
    def test_attached_nodes_without_secret_code_restore_without_use(
        self, no_secrets_use_client, acme
    ):
        trigger = WebhookTrigger.objects.create(path="plain-hook-path", org=acme)
        WebhookTriggerNode.objects.create(
            graph=Graph.objects.create(name="Plain hook flow", org=acme),
            node_name="Incoming",
            webhook_trigger=trigger,
            python_code=PythonCode.objects.create(code="def main(**kwargs):\n    return 1\n"),
        )
        trigger.delete()

        response = _bin_restore(no_secrets_use_client, WEBHOOK_TRIGGERS_URL, trigger)

        assert response.status_code == status.HTTP_200_OK, response.content
        assert not _is_binned(trigger)

    def test_binning_the_trigger_leaves_its_nodes_live_and_linked(self, acme, secret):
        """What makes restoring the trigger reconnect them."""
        trigger = _webhook_trigger_with_declaring_node(acme, secret)
        trigger.delete()

        node = WebhookTriggerNode.objects.get(webhook_trigger_id=trigger.pk)
        assert node.active

    def test_nodes_of_a_flow_binned_before_the_trigger_do_not_count_until_the_flow_comes_back(
        self, no_secrets_use_client, acme, secret
    ):
        """The flow and the trigger are binned in separate batches: binning the flow
        leaves the trigger alone, and binning the trigger leaves the nodes alone."""
        trigger = _webhook_trigger_with_declaring_node(acme, secret)
        flow = WebhookTriggerNode.objects.get(webhook_trigger=trigger).graph
        flow.delete()
        trigger.delete()
        assert flow.soft_delete_batch != WebhookTrigger.all_objects.get(pk=trigger.pk).soft_delete_batch

        trigger_response = _bin_restore(no_secrets_use_client, WEBHOOK_TRIGGERS_URL, trigger)
        flow_response = _bin_restore(no_secrets_use_client, FLOWS_URL, flow)

        assert trigger_response.status_code == status.HTTP_200_OK, trigger_response.content
        _assert_refused(flow_response)
        assert _is_binned(flow)

    def test_a_trigger_binned_in_its_flows_batch_is_refused(self, no_secrets_use_client, acme, secret):
        """No delete path bins them together today; if one does, restoring the trigger
        brings the flow's declaring node back with the batch, so it is still refused."""
        trigger = _webhook_trigger_with_declaring_node(acme, secret)
        flow = WebhookTriggerNode.objects.get(webhook_trigger=trigger).graph
        flow.delete()
        trigger.delete()
        WebhookTrigger.all_objects.filter(pk=trigger.pk).update(
            soft_delete_batch=Graph.all_objects.get(pk=flow.pk).soft_delete_batch
        )

        response = _bin_restore(no_secrets_use_client, WEBHOOK_TRIGGERS_URL, trigger)

        _assert_refused(response)
        assert _is_binned(trigger)
