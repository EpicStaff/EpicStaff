"""A resource keeps its link to a secret (or webhook trigger) in the recycle bin when
it's saved unchanged; a new link to a binned one is still refused."""

from unittest.mock import patch

import pytest
from django.urls import reverse
from rest_framework import status
from tables.models import Graph, PythonCode, Secret, WebhookTrigger
from tables.models.graph_models import WebhookTriggerNode
from tables.models.python_models import PythonCodeTool
from tables.services.copy_services.helpers import copy_python_code
from tables.models.webhook_models import NgrokWebhookConfig, WebhookTriggerAuthKind
from tables.services.secrets import secret_service
from tables.services.webhook_trigger_service import WebhookTriggerService
from tests.api_tests.test_secret_use_fk_fields import (  # noqa: F401  -- fixtures
    GATED,
    GATED_6B,
    elevenlabs_config_pointing_at_secret_a,
    embedding_config_pointing_at_secret_a,
    gemini_config_pointing_at_secret_a,
    llm_config_pointing_at_secret_a,
    mcp_tool_pointing_at_secret_a,
    no_use_client_6b,
    openai_realtime_config_pointing_at_secret_a,
    realtime_config_pointing_at_secret_a,
    realtime_transcription_config_pointing_at_secret_a,
    secret_a,
    secret_b,
    telegram_trigger_node_pointing_at_secret_a,
    twilio_channel_pointing_at_secret_a,
    use_client_6b,
)

REGISTER = "tables.signals.webhook_signals.WebhookTriggerService.register_webhooks"
PYTHON_CODE_DATA = {"code": "def main(**kwargs): ...", "entrypoint": "main", "libraries": []}
#: Long enough for a webhook trigger's auth secret (32+ characters).
TRIGGER_SECRET_TEXT = "trigger-secret-value-for-tests-0123456789"


@pytest.fixture(autouse=True)
def _no_tunnel_calls():
    with patch(REGISTER, return_value=True):
        yield


def _bin(secret):
    secret.delete()
    assert not Secret.all_objects.get(pk=secret.pk).active


@pytest.mark.django_db
@pytest.mark.parametrize("endpoint,field,fixture_name", GATED + GATED_6B)
def test_an_unchanged_binned_secret_is_kept_without_use_permission(
    request, no_use_client_6b, endpoint, field, fixture_name, secret_a
):
    instance = request.getfixturevalue(fixture_name)
    _bin(secret_a)

    response = no_use_client_6b.patch(
        f"{endpoint}{instance.pk}/", {field: secret_a.id}, format="json"
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    instance.refresh_from_db()
    assert getattr(instance, field) == secret_a.id


@pytest.mark.django_db
def test_a_new_link_to_a_binned_secret_is_refused(
    use_client_6b, llm_config_pointing_at_secret_a, secret_b
):
    _bin(secret_b)

    response = use_client_6b.patch(
        f"/api/llm-configs/{llm_config_pointing_at_secret_a.id}/",
        {"api_key_secret_id": secret_b.id},
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert "Invalid pk" in str(response.content)
    llm_config_pointing_at_secret_a.refresh_from_db()
    assert llm_config_pointing_at_secret_a.api_key_secret_id != secret_b.id


@pytest.mark.django_db
def test_a_twilio_channel_keeps_its_binned_trigger(
    no_use_client_6b, twilio_channel_pointing_at_secret_a, default_org
):
    channel = twilio_channel_pointing_at_secret_a
    trigger = WebhookTrigger.objects.create(org=default_org, path="calls", provider_type="ngrok")
    channel.webhook_trigger = trigger
    channel.save()
    trigger.delete()

    response = no_use_client_6b.patch(
        f"/api/twilio-channels/{channel.pk}/", {"webhook_trigger": trigger.id}, format="json"
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    channel.refresh_from_db()
    assert channel.webhook_trigger_id == trigger.id


def _python_node(graph, secrets):
    python_code = PythonCode.objects.create(code="def main(**kwargs): ...")
    python_code.secrets.set(secrets)
    return WebhookTriggerNode.objects.create(
        graph=graph, node_name="Hook", python_code=python_code
    )


def _save_python_node(client, graph, node, secret_ids):
    graph.refresh_from_db()
    entry = {
        "id": node.id,
        "graph": graph.id,
        "node_name": "Hook",
        "metadata": {},
        "python_code": {**PYTHON_CODE_DATA, "secret_ids": secret_ids},
        "webhook_trigger": None,
    }
    return client.post(
        reverse("graphs-save-flow", args=[graph.id]),
        {"save_version": graph.save_version, "webhook_trigger_node_list": [entry]},
        format="json",
    )


def _linked_ids(node):
    return set(node.python_code.secrets(manager="all_objects").values_list("pk", flat=True))


@pytest.mark.django_db
def test_python_node_round_trip_keeps_a_binned_secret_without_use_permission(
    no_use_client_6b, default_org, secret_a, secret_b
):
    graph = Graph.objects.create(name="Flow", org=default_org)
    node = _python_node(graph, [secret_a, secret_b])
    _bin(secret_b)

    # What the editor reads, and then sends back unchanged.
    read = no_use_client_6b.get(f"/api/webhook-trigger-nodes/{node.id}/")
    assert read.status_code == status.HTTP_200_OK, read.content
    sent_ids = [secret["id"] for secret in read.json()["python_code"]["secrets"]]
    assert set(sent_ids) == {secret_a.id, secret_b.id}

    response = _save_python_node(no_use_client_6b, graph, node, sent_ids)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert _linked_ids(node) == {secret_a.id, secret_b.id}


@pytest.mark.django_db
def test_the_flow_read_lists_a_binned_secret_though_it_prefetches_secrets(
    no_use_client_6b, default_org, secret_a, secret_b
):
    graph = Graph.objects.create(name="Flow", org=default_org)
    _python_node(graph, [secret_a, secret_b])
    _bin(secret_b)

    response = no_use_client_6b.get(f"/api/graphs/{graph.id}/")

    assert response.status_code == status.HTTP_200_OK, response.content
    (node,) = response.json()["webhook_trigger_node_list"]
    assert {secret["id"] for secret in node["python_code"]["secrets"]} == {secret_a.id, secret_b.id}


@pytest.mark.django_db
def test_removing_a_binned_secret_from_python_code_unlinks_it(
    use_client_6b, default_org, secret_a, secret_b
):
    graph = Graph.objects.create(name="Flow", org=default_org)
    node = _python_node(graph, [secret_a, secret_b])
    _bin(secret_b)

    response = _save_python_node(use_client_6b, graph, node, [secret_a.id])

    assert response.status_code == status.HTTP_200_OK, response.content
    assert _linked_ids(node) == {secret_a.id}


@pytest.mark.django_db
def test_python_node_cannot_add_a_binned_secret(use_client_6b, default_org, secret_a, secret_b):
    graph = Graph.objects.create(name="Flow", org=default_org)
    node = _python_node(graph, [secret_a])
    _bin(secret_b)

    response = _save_python_node(use_client_6b, graph, node, [secret_a.id, secret_b.id])

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert "Invalid pk" in str(response.content)
    assert _linked_ids(node) == {secret_a.id}


@pytest.mark.django_db
def test_trigger_settings_keep_binned_auth_and_tunnel_secrets(
    django_user_model, default_org
):
    from tests.api_tests.test_secret_use_fk_fields import _client_with_grants
    from rbac.models.enums import Permission, ResourceType

    client = _client_with_grants(
        org=default_org,
        django_user_model=django_user_model,
        email="binned-trigger-settings@example.com",
        resource_permissions={
            ResourceType.SECRETS.value: int(Permission.READ),
            ResourceType.WEBHOOKS.value: int(
                Permission.CREATE | Permission.READ | Permission.UPDATE | Permission.DELETE
            ),
        },
    )
    tunnel_secret = secret_service.create(text="ngrok-token", org=default_org, name="tunnel")
    auth_secret = secret_service.create(text=TRIGGER_SECRET_TEXT, org=default_org, name="auth")
    trigger = WebhookTrigger.objects.create(org=default_org, path="orders", provider_type="ngrok")
    NgrokWebhookConfig.objects.create(trigger=trigger, name="tunnel", auth_token_secret=tunnel_secret)
    WebhookTriggerService().set_trigger_auth_secret(
        trigger, auth_secret, kind=WebhookTriggerAuthKind.WEBHOOK
    )
    _bin(tunnel_secret)
    _bin(auth_secret)

    response = client.patch(
        f"/api/webhook-triggers/{trigger.id}/",
        {
            "auth_secret_id": auth_secret.id,
            "ngrok_config": {"name": "tunnel", "auth_token_secret_id": tunnel_secret.id},
        },
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    trigger.refresh_from_db()
    assert trigger.auth.secret_id == auth_secret.id
    assert NgrokWebhookConfig.objects.get(trigger=trigger).auth_token_secret_id == tunnel_secret.id


@pytest.mark.django_db
def test_updating_a_tool_answers_with_its_new_secrets_not_the_prefetched_ones(
    use_client_6b, default_org, secret_a, secret_b
):
    python_code = PythonCode.objects.create(code="def main(**kwargs): ...", entrypoint="main")
    python_code.secrets.set([secret_a])
    tool = PythonCodeTool.objects.create(
        org=default_org, name="Lookup", description="", python_code=python_code
    )

    response = use_client_6b.patch(
        f"/api/python-code-tool/{tool.id}/",
        {"python_code": {**PYTHON_CODE_DATA, "secret_ids": [secret_a.id, secret_b.id]}},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    answered = {secret["id"] for secret in response.json()["python_code"]["secrets"]}
    assert answered == {secret_a.id, secret_b.id}


@pytest.mark.django_db
def test_a_copy_keeps_a_binned_secret_link(default_org, secret_a, secret_b):
    python_code = PythonCode.objects.create(code="def main(**kwargs): ...")
    python_code.secrets.set([secret_a, secret_b])
    _bin(secret_b)

    duplicate = copy_python_code(python_code)

    linked = set(duplicate.secrets(manager="all_objects").values_list("pk", flat=True))
    assert linked == {secret_a.id, secret_b.id}
