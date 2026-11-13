"""POST /api/classification-decision-table-node/{pk}/explain/ answers by one deadline.

Invariant: a whole explain request, however many batches it is split into, returns within
the deployment maximum (DJANGO_LLM_CONFIG_MAX_TIMEOUT), because the sync view holds a
worker thread until it does. A batch the deadline cuts off, while it waits for the model
or still queued behind the concurrency limit, counts as failed: its steps come back as
failures while the batches that finished keep their explanations. When every batch is cut
off the request fails as upstream_failed.

Only the LLM provider call (`litellm.acompletion`) is replaced; the view, service, secret
resolution and LiteLLMClient run for real.
"""

import asyncio
import json
import time
from types import SimpleNamespace
from unittest import mock

import pytest
from rest_framework import status

from tables.models import Graph
from tables.models.graph_models import ClassificationDecisionTableNode
from tables.models.llm_models import LLMConfig, LLMModel
from tables.models.provider import Provider
from tables.services.cdt_explain import service as cdt_explain_service
from tables.services.secrets import secret_service
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

DEADLINE_SECONDS = 0.5
# Far beyond DEADLINE_SECONDS, and finite, so code without a deadline finishes (and
# fails the assertions) instead of hanging the suite.
STALL_SECONDS = 3.0
ANSWERED_WITHIN_SECONDS = 2.0

# One block per prompt section, so each is its own batch. Batches run in section order:
# computation, condition, manipulation.
FAST_STEP = "step-fast"
STALLED_STEP = "step-stalled"
QUEUED_STEP = "step-queued"
BLOCKS = [
    {"id": FAST_STEP, "block": "pre_computation", "code": "score = 1", "input_map": {}},
    {"id": STALLED_STEP, "block": "condition", "expression": "score > 0"},
    {"id": QUEUED_STEP, "block": "manipulation", "manipulation": {"label": "score"}},
]


def _url(node_id) -> str:
    return f"/api/classification-decision-table-node/{node_id}/explain/"


def _body(llm_config_id) -> dict:
    return {
        "llm_config": llm_config_id,
        "table": {"node_name": "classify", "rules": []},
        "blocks": BLOCKS,
    }


def _chunk(content, finish_reason):
    delta = SimpleNamespace(content=content, tool_calls=None, reasoning_content=None)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta, finish_reason=finish_reason)])


def _model_stalling_on(stalled_step_ids: set[str]):
    """A stand-in for `litellm.acompletion` that explains every step of a batch at once,
    except that it stalls before answering a batch holding one of `stalled_step_ids`."""

    async def answer(**kwargs):
        user_message = kwargs["messages"][-1]["content"]
        step_ids = [block["id"] for block in BLOCKS if f"id: {block['id']}" in user_message]
        if stalled_step_ids.intersection(step_ids):
            await asyncio.sleep(STALL_SECONDS)
        content = json.dumps(
            {"explanations": [{"id": step_id, "text": "Explained."} for step_id in step_ids]}
        )

        async def stream():
            yield _chunk(content, None)
            yield _chunk(None, "stop")

        return stream()

    return answer


@pytest.fixture(autouse=True)
def short_deadline(monkeypatch):
    monkeypatch.setattr(cdt_explain_service, "LLM_CONFIG_TIMEOUT_MAX_SECONDS", DEADLINE_SECONDS)
    # One batch at a time, so the step after the stalled one waits in the queue.
    monkeypatch.setattr(cdt_explain_service, "MAX_CONCURRENCY", 1)


@pytest.fixture
def cdt_node(acme):
    graph = Graph.objects.create(name="flow-acme-explain-deadline", metadata={}, org=acme)
    return ClassificationDecisionTableNode.objects.create(graph=graph, node_name="classify")


@pytest.fixture
def llm_config(acme):
    provider, _ = Provider.objects.get_or_create(name="openai")
    model = LLMModel.objects.create(name="cdt-explain-deadline-model", llm_provider=provider)
    secret = secret_service.create(text="sk-cdt-deadline", org=acme, name="cdt-deadline-key")
    return LLMConfig.objects.create(
        custom_name="with-key", model=model, org=acme, api_key_secret=secret
    )


@pytest.fixture
def acme_client(client_as, acme, admin_acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


def _post_timed(client, cdt_node, llm_config, stalled_step_ids: set[str]):
    started = time.monotonic()
    with mock.patch("litellm.acompletion", side_effect=_model_stalling_on(stalled_step_ids)):
        response = client.post(_url(cdt_node.id), _body(llm_config.id), format="json")
    return response, time.monotonic() - started


@pytest.mark.django_db
def test_batches_cut_off_by_the_deadline_are_failures_and_the_rest_are_explained(
    acme_client, cdt_node, llm_config
):
    response, elapsed = _post_timed(acme_client, cdt_node, llm_config, {STALLED_STEP})

    assert elapsed < ANSWERED_WITHIN_SECONDS
    assert response.status_code == status.HTTP_200_OK, response.content
    body = response.json()
    assert [explanation["id"] for explanation in body["explanations"]] == [FAST_STEP]
    assert [failure["id"] for failure in body["failures"]] == [STALLED_STEP, QUEUED_STEP]


@pytest.mark.django_db
def test_every_batch_cut_off_fails_the_request_as_upstream_failed(
    acme_client, cdt_node, llm_config
):
    all_steps = {block["id"] for block in BLOCKS}

    response, elapsed = _post_timed(acme_client, cdt_node, llm_config, all_steps)

    assert elapsed < ANSWERED_WITHIN_SECONDS
    assert response.status_code == status.HTTP_502_BAD_GATEWAY, response.content
    assert response.json()["code"] == "cdt_explain_upstream_failed"
