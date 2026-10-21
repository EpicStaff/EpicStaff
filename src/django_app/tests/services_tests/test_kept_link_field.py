"""What a row links to now, binned rows included: the persisted value both the secret
reference guard and KeptLinkPrimaryKeyRelatedField compare against."""

import pytest
from rest_framework import serializers
from rest_framework.test import APIRequestFactory
from tables.models import Graph, PythonCode, Secret, WebhookTrigger
from tables.models.graph_models import WebhookTriggerNode
from tables.serializers.model_serializers.node_serializers.trigger_serializers import (
    WebhookTriggerNodeSerializer,
)
from tables.serializers.utils.soft_delete_fields import KeptLinkPrimaryKeyRelatedField
from tables.services.secrets import linked_ids
from tables.services.secrets.declaration_validator import describe_unreadable_secrets
from tables.services.secrets.secret_service import secret_service
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

pytestmark = pytest.mark.django_db


def test_linked_ids_include_a_binned_secret_in_a_many_to_many(acme):
    live = secret_service.create(text="live-value", org=acme, name="live")
    binned = secret_service.create(text="binned-value", org=acme, name="binned")
    python_code = PythonCode.objects.create(code="def main(**kwargs): ...")
    python_code.secrets.set([live, binned])
    binned.delete()

    assert linked_ids(python_code.secrets) == {live.pk, binned.pk}
    assert not Secret.all_objects.get(pk=binned.pk).active


@pytest.mark.parametrize(
    "value,expected",
    [(None, set()), (7, {7}), ([3, 4], {3, 4}), ((), set())],
)
def test_linked_ids_of_plain_values(value, expected):
    assert linked_ids(value) == expected


def test_only_the_binned_trigger_already_linked_is_offered(acme, admin_acme):
    linked = WebhookTrigger.objects.create(org=acme, path="orders", provider_type="ngrok")
    unlinked = WebhookTrigger.objects.create(org=acme, path="refunds", provider_type="ngrok")
    live = WebhookTrigger.objects.create(org=acme, path="live", provider_type="ngrok")
    node = WebhookTriggerNode.objects.create(
        graph=Graph.objects.create(name="Flow", org=acme),
        node_name="Hook",
        python_code=PythonCode.objects.create(code="def main(**kwargs): ..."),
        webhook_trigger=linked,
    )
    linked.delete()
    unlinked.delete()
    request = APIRequestFactory().patch("/")
    request.user = admin_acme
    request.META["HTTP_X_ORGANIZATION_ID"] = str(acme.id)

    field = WebhookTriggerNodeSerializer(instance=node, context={"request": request}).fields[
        "webhook_trigger"
    ]

    assert set(field.get_queryset().values_list("pk", flat=True)) == {linked.pk, live.pk}


class _OwnerWithoutPersistedValue(serializers.Serializer):
    webhook_trigger = KeptLinkPrimaryKeyRelatedField(queryset=WebhookTrigger.all_objects.all())


def test_an_owner_that_cannot_say_what_it_links_to_is_a_programming_error():
    field = _OwnerWithoutPersistedValue().fields["webhook_trigger"]

    with pytest.raises(TypeError, match="PersistedValueMixin"):
        field.get_queryset()


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

