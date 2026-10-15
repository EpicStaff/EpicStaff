"""Authored resources return `created_by` as a user summary and `created_at` as an ISO time.

Both are read-only: the server sets them on create (and on copy, which creates a new
resource); rows created before `created_at` existed keep rendering it as null.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import status

from agents.models import AgentDefinition
from tables.models import (
    ElevenLabsRealtimeConfig,
    EmbeddingConfig,
    EmbeddingModel,
    GeminiRealtimeConfig,
    Graph,
    Label,
    LLMConfig,
    LLMModel,
    OpenAIRealtimeConfig,
    Provider,
    PythonCode,
    PythonCodeTool,
    RealtimeChannel,
    SubGraphNode,
    TelegramTriggerNode,
    TwilioChannel,
    WebhookTrigger,
    WebhookTriggerNode,
)
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

CLIENT_SUPPLIED_CREATED_AT = "2001-01-01T00:00:00Z"
OLD_CREATED_AT = datetime(2001, 1, 1, tzinfo=UTC)


def _summary(user) -> dict:
    return {"id": user.id, "display_name": user.display_name or None, "avatar_url": None}


def _parse(rendered: str) -> datetime:
    assert isinstance(rendered, str), rendered
    parsed = parse_datetime(rendered)
    assert parsed is not None, f"not an ISO datetime: {rendered!r}"
    return parsed


def _rows(body):
    return body["results"] if isinstance(body, dict) else body


def _embedding_model() -> EmbeddingModel:
    provider, _ = Provider.objects.get_or_create(name="created-fields-provider")
    model, _ = EmbeddingModel.objects.get_or_create(
        name="created-fields-embedding", embedding_provider=provider
    )
    return model


def _llm_model() -> LLMModel:
    provider, _ = Provider.objects.get_or_create(name="created-fields-provider")
    model, _ = LLMModel.objects.get_or_create(name="created-fields-llm", llm_provider=provider)
    return model


def _python_code() -> PythonCode:
    return PythonCode.objects.create(code="def main(): return 1", entrypoint="main")


def _python_code_tool(org, *, name: str, author=None, built_in: bool = False) -> PythonCodeTool:
    return PythonCodeTool.objects.create(
        name=name,
        description="tool",
        python_code=_python_code(),
        org=org,
        built_in=built_in,
        created_by=author,
    )


@pytest.fixture
def acme_admin(admin_acme):
    admin_acme.display_name = "Acme Admin"
    admin_acme.save(update_fields=["display_name"])
    return admin_acme


@pytest.fixture
def acme_client(client_as, acme_admin, acme):
    client = client_as(acme_admin)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


# ---- created_at: LLM, embedding and voice configs, RealtimeChannel, WebhookTrigger, AgentDefinition ----


@dataclass(frozen=True)
class CreatedAtResource:
    url: str
    model: type
    name_field: str
    patch_value: str
    # Fields a POST needs besides the name, built per test.
    extra_payload: Callable[[], dict] = dict

    def create_payload(self, name: str) -> dict:
        return {self.name_field: name, **self.extra_payload()}

    def make_row(self, org, name: str):
        return self.model.objects.create(org=org, **{self.name_field: name})


CREATED_AT_RESOURCES = [
    CreatedAtResource(
        "/api/llm-configs/",
        LLMConfig,
        "custom_name",
        "renamed-config",
        extra_payload=lambda: {"model": _llm_model().id},
    ),
    CreatedAtResource(
        "/api/embedding-configs/",
        EmbeddingConfig,
        "custom_name",
        "renamed-embedding",
        extra_payload=lambda: {"model": _embedding_model().id},
    ),
    CreatedAtResource(
        "/api/openai-realtime-configs/", OpenAIRealtimeConfig, "custom_name", "renamed-openai"
    ),
    CreatedAtResource(
        "/api/elevenlabs-realtime-configs/",
        ElevenLabsRealtimeConfig,
        "custom_name",
        "renamed-elevenlabs",
    ),
    CreatedAtResource(
        "/api/gemini-realtime-configs/", GeminiRealtimeConfig, "custom_name", "renamed-gemini"
    ),
    CreatedAtResource("/api/realtime-channels/", RealtimeChannel, "name", "renamed-channel"),
    CreatedAtResource(
        "/api/webhook-triggers/",
        WebhookTrigger,
        "path",
        "renamed-trigger-path",
        extra_payload=lambda: {"provider_type": None},
    ),
    CreatedAtResource("/api/agent-definitions/", AgentDefinition, "name", "renamed-agent"),
]


def _legacy_row(resource: CreatedAtResource, org):
    """A row created before `created_at` existed: its creation time is unknown."""
    row = resource.make_row(org, "legacy-row")
    resource.model._base_manager.filter(pk=row.pk).update(created_at=None)
    return row


@pytest.mark.django_db
@pytest.mark.parametrize("resource", CREATED_AT_RESOURCES, ids=lambda resource: resource.url)
class TestCreatedAt:
    def test_create_stamps_the_server_time_whatever_the_client_sends(self, resource, acme_client):
        before = timezone.now()

        response = acme_client.post(
            resource.url,
            {**resource.create_payload("created-row"), "created_at": CLIENT_SUPPLIED_CREATED_AT},
            format="json",
        )

        after = timezone.now()
        assert response.status_code == status.HTTP_201_CREATED, response.data
        created_at = _parse(response.json()["created_at"])
        assert before <= created_at <= after
        stored = resource.model._base_manager.get(pk=response.data["id"]).created_at
        assert stored == created_at

    def test_patch_ignores_client_supplied_created_at(self, resource, acme_client, acme):
        row = resource.make_row(acme, "existing-row")
        original = row.created_at

        response = acme_client.patch(
            f"{resource.url}{row.id}/",
            {"created_at": CLIENT_SUPPLIED_CREATED_AT, resource.name_field: resource.patch_value},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.data
        row.refresh_from_db()
        assert row.created_at == original
        assert getattr(row, resource.name_field) == resource.patch_value

    def test_legacy_row_keeps_a_null_created_at_through_reads_and_edits(self, resource, acme_client, acme):
        legacy = _legacy_row(resource, acme)

        detail = acme_client.get(f"{resource.url}{legacy.id}/")
        listing = acme_client.get(resource.url)

        assert detail.status_code == status.HTTP_200_OK, detail.data
        assert detail.json()["created_at"] is None
        assert listing.status_code == status.HTTP_200_OK, listing.data
        listed = next(row for row in _rows(listing.json()) if row["id"] == legacy.id)
        assert listed["created_at"] is None

        response = acme_client.patch(
            f"{resource.url}{legacy.id}/",
            {"created_at": CLIENT_SUPPLIED_CREATED_AT, resource.name_field: resource.patch_value},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.data
        assert response.json()["created_at"] is None
        assert resource.model._base_manager.get(pk=legacy.pk).created_at is None

    def test_other_org_row_is_not_found(self, resource, acme_client, beta):
        beta_row = resource.make_row(beta, "beta-row")

        response = acme_client.get(f"{resource.url}{beta_row.id}/")

        assert response.status_code == status.HTTP_404_NOT_FOUND


# ---- created_by as a user summary ----


@pytest.mark.django_db
class TestWebhookTriggerAuthor:
    def test_trigger_nodes_nest_the_trigger_author_and_creation_time(
        self, acme_client, acme_admin, acme
    ):
        trigger = WebhookTrigger.objects.create(path="nested", org=acme, created_by=acme_admin)
        graph = Graph.objects.create(name="trigger-flow", org=acme)
        webhook_node = WebhookTriggerNode.objects.create(
            graph=graph, node_name="hook", python_code=_python_code(), webhook_trigger=trigger
        )
        telegram_node = TelegramTriggerNode.objects.create(
            graph=graph, node_name="telegram", webhook_trigger=trigger
        )

        webhook_detail = acme_client.get(f"/api/webhook-trigger-nodes/{webhook_node.id}/")
        telegram_detail = acme_client.get(f"/api/telegram-trigger-nodes/{telegram_node.id}/")

        for response in (webhook_detail, telegram_detail):
            assert response.status_code == status.HTTP_200_OK, response.data
            nested = response.json()["webhook_trigger"]
            assert nested["created_by"] == _summary(acme_admin)
            assert _parse(nested["created_at"]) == trigger.created_at

    def test_realtime_channel_nests_the_trigger_author(self, acme_client, acme_admin, acme):
        trigger = WebhookTrigger.objects.create(path="voice", org=acme, created_by=acme_admin)
        channel = RealtimeChannel.objects.create(name="voice-channel", org=acme)
        TwilioChannel.objects.create(channel=channel, account_sid="AC1", webhook_trigger=trigger)

        response = acme_client.get(f"/api/realtime-channels/{channel.id}/")

        assert response.status_code == status.HTTP_200_OK, response.data
        nested = response.json()["twilio"]["webhook_trigger"]
        assert nested["created_by"] == _summary(acme_admin)
        assert _parse(nested["created_at"]) == trigger.created_at


@pytest.mark.django_db
class TestPythonCodeToolAuthor:
    def test_built_in_tool_has_no_author_even_after_a_label_update(self, acme_client, acme):
        built_in = _python_code_tool(None, name="BuiltInAuthorless", built_in=True)
        label = Label.objects.create(name="favourites", scope=Label.Scope.TOOL, org=acme)

        detail = acme_client.get(f"/api/python-code-tool/{built_in.id}/")
        updated = acme_client.patch(
            f"/api/python-code-tool/{built_in.id}/", {"labels": [label.id]}, format="json"
        )

        assert detail.status_code == status.HTTP_200_OK, detail.data
        assert detail.json()["created_by"] is None
        assert updated.status_code == status.HTTP_200_OK, updated.data
        assert updated.json()["labels"] == [label.id]
        assert updated.json()["created_by"] is None
        built_in.refresh_from_db()
        assert built_in.created_by_id is None

@pytest.mark.django_db
class TestGraphAuthor:
    def test_create_and_detail_return_the_author_and_creation_time(
        self, acme_client, acme_admin, member_only
    ):
        before = timezone.now()

        created = acme_client.post(
            "/api/graphs/",
            {"name": "authored-flow", "created_by": member_only.id},
            format="json",
        )
        detail = acme_client.get(f"/api/graphs/{created.data['id']}/")

        assert created.status_code == status.HTTP_201_CREATED, created.data
        for response in (created, detail):
            body = response.json()
            assert body["created_by"] == _summary(acme_admin)
            assert _parse(body["created_at"]) >= before
        assert Graph.objects.get(pk=created.data["id"]).created_by_id == acme_admin.id

    def test_light_list_returns_the_author(self, acme_client, acme_admin, acme):
        graph = Graph.objects.create(name="light-flow", org=acme, created_by=acme_admin)

        response = acme_client.get("/api/graph-light/")

        assert response.status_code == status.HTTP_200_OK, response.data
        listed = next(row for row in _rows(response.json()) if row["id"] == graph.id)
        assert listed["created_by"] == _summary(acme_admin)
        assert _parse(listed["created_at"]) == graph.created_at

    def test_subgraph_node_detail_returns_the_subflow_author(
        self, acme_client, member_only, acme
    ):
        subflow = Graph.objects.create(name="subflow", org=acme, created_by=member_only)
        node = SubGraphNode.objects.create(
            graph=Graph.objects.create(name="parent-flow", org=acme),
            node_name="sub",
            subgraph=subflow,
        )

        response = acme_client.get(f"/api/subgraph-nodes/{node.id}/")

        assert response.status_code == status.HTTP_200_OK, response.data
        assert response.json()["subgraph_detail"]["created_by"] == _summary(member_only)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("model", "url", "make_source"),
    [
        (PythonCodeTool, "/api/python-code-tool/{}/copy/", lambda org, author: _python_code_tool(org, name="source-tool", author=author)),
        (Graph, "/api/graphs/{}/copy/", lambda org, author: Graph.objects.create(name="source-flow", org=org, created_by=author)),
    ],
    ids=["tool", "flow"],
)
def test_copy_is_authored_by_the_copier_with_a_fresh_creation_time(
    model, url, make_source, acme_client, acme_admin, member_only, acme
):
    source = make_source(acme, member_only)
    model.objects.filter(pk=source.pk).update(created_at=OLD_CREATED_AT)
    before = timezone.now()

    response = acme_client.post(url.format(source.id), {}, format="json")

    assert response.status_code == status.HTTP_201_CREATED, response.data
    assert response.json()["created_by"] == _summary(acme_admin)
    assert _parse(response.json()["created_at"]) >= before
    assert model.objects.get(pk=response.data["id"]).created_by_id == acme_admin.id


# ---- org scoping ----


def _beta_webhook_trigger(beta) -> WebhookTrigger:
    return WebhookTrigger.objects.create(path="beta-trigger", org=beta)


def _beta_graph(beta, name: str = "beta-flow") -> Graph:
    return Graph.objects.create(name=name, org=beta)


def _beta_webhook_trigger_url(beta) -> str:
    return f"/api/webhook-triggers/{_beta_webhook_trigger(beta).id}/"


def _beta_webhook_trigger_node_url(beta) -> str:
    node = WebhookTriggerNode.objects.create(
        graph=_beta_graph(beta),
        node_name="hook",
        python_code=_python_code(),
        webhook_trigger=_beta_webhook_trigger(beta),
    )
    return f"/api/webhook-trigger-nodes/{node.id}/"


def _beta_telegram_trigger_node_url(beta) -> str:
    node = TelegramTriggerNode.objects.create(
        graph=_beta_graph(beta), node_name="telegram", webhook_trigger=_beta_webhook_trigger(beta)
    )
    return f"/api/telegram-trigger-nodes/{node.id}/"


def _beta_python_code_tool_url(beta) -> str:
    return f"/api/python-code-tool/{_python_code_tool(beta, name='beta-tool').id}/"


def _beta_graph_url(beta) -> str:
    return f"/api/graphs/{_beta_graph(beta).id}/"


def _beta_graph_light_url(beta) -> str:
    return f"/api/graph-light/{_beta_graph(beta).id}/"


def _beta_subgraph_node_url(beta) -> str:
    node = SubGraphNode.objects.create(
        graph=_beta_graph(beta), node_name="sub", subgraph=_beta_graph(beta, "beta-subflow")
    )
    return f"/api/subgraph-nodes/{node.id}/"


OTHER_ORG_DETAIL_URLS = [
    _beta_webhook_trigger_url,
    _beta_webhook_trigger_node_url,
    _beta_telegram_trigger_node_url,
    _beta_python_code_tool_url,
    _beta_graph_url,
    _beta_graph_light_url,
    _beta_subgraph_node_url,
]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "beta_detail_url", OTHER_ORG_DETAIL_URLS, ids=lambda make_url: make_url.__name__
)
def test_other_org_authored_row_is_not_found(beta_detail_url, acme_client, beta):
    response = acme_client.get(beta_detail_url(beta))

    assert response.status_code == status.HTTP_404_NOT_FOUND
