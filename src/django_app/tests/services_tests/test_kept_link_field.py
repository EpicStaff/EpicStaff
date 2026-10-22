"""What a row links to now, binned rows included: the secret reference guard's lookup,
shared by the guard and KeptLinkPrimaryKeyRelatedField."""

from types import SimpleNamespace

import pytest
from tables.models import Graph, PythonCode, Secret, WebhookTrigger
from tables.models.graph_models import WebhookTriggerNode
from tables.serializers.model_serializers.node_serializers.trigger_serializers import (
    WebhookTriggerNodeSerializer,
)
from tables.services.secrets.declaration_validator import describe_unreadable_secrets
from tables.services.secrets.reference_guard import secret_reference_guard
from tables.services.secrets.secret_service import secret_service
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

pytestmark = pytest.mark.django_db


def test_current_ids_include_a_binned_secret_in_a_many_to_many(acme):
    live = secret_service.create(text="live-value", org=acme, name="live")
    binned = secret_service.create(text="binned-value", org=acme, name="binned")
    python_code = PythonCode.objects.create(code="def main(**kwargs): ...")
    python_code.secrets.set([live, binned])
    binned.delete()

    current = secret_reference_guard.current_ids(
        serializer=SimpleNamespace(instance=python_code), source="secrets"
    )

    assert current == {live.pk, binned.pk}
    assert not Secret.all_objects.get(pk=binned.pk).active


def test_current_ids_of_a_single_link_include_a_binned_row(acme):
    trigger = WebhookTrigger.objects.create(org=acme, path="orders", provider_type="ngrok")
    node = WebhookTriggerNode.objects.create(
        graph=Graph.objects.create(name="Flow", org=acme),
        node_name="Hook",
        python_code=PythonCode.objects.create(code="def main(**kwargs): ..."),
        webhook_trigger=trigger,
    )
    trigger.delete()

    current = secret_reference_guard.current_ids(
        serializer=WebhookTriggerNodeSerializer(instance=node), source="webhook_trigger"
    )

    assert current == {trigger.pk}


def test_unreadable_secrets_name_the_binned_ones_apart_from_the_undeclared():
    message = describe_unreadable_secrets(
        subject='node "Fetch"',
        owner="that node",
        undeclared={"OLD_KEY", "TYPO_KEY"},
        binned={"OLD_KEY"},
        declared={"API_KEY"},
    )

    assert message == (
        'node "Fetch" calls get_secret("TYPO_KEY"), which is not declared for that node. '
        "Declared: API_KEY. "
        'node "Fetch" calls get_secret("OLD_KEY"), which reads a secret in the recycle bin. '
        "Restore it from the Recycle Bin, or pick another secret for that node."
    )

