"""System One entries in a Classification Decision Table's Prompt Library: what a save stores and refuses."""

import pytest
from tables.models import Graph, SystemOneConfig
from tables.models.graph_models import (
    ClassificationDecisionTableNode,
    ClassificationDecisionTablePrompt,
)
from tables.models.llm_models import LLMConfig

from tests.rbac_cross_org_fixtures import *

CDT_URL = "/api/classification-decision-table-node/"
QUESTIONS = {"is_engineering": {"type": "noul", "instructions": "Engineering?"}}
INPUT_MAP = {"company": "variables.company"}


def system_one_prompt(config_id, **overrides):
    return {
        "prompt_key": "company_check",
        "kind": "system_one",
        "system_one_config": config_id,
        "questions": QUESTIONS,
        "input_map": INPUT_MAP,
        "result_variable": "company_check",
        **overrides,
    }


@pytest.fixture
def client_a(client_as, admin_acme, acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


@pytest.fixture
def graph(acme):
    return Graph.objects.create(name="g", metadata={"nodes": [], "edges": []}, org=acme)


@pytest.fixture
def acme_config(acme):
    return SystemOneConfig.objects.create(
        org=acme, custom_name="jev", provider="typesafe", model_name="jev-1.14.0"
    )


@pytest.fixture
def acme_llm_config(acme):
    return LLMConfig.objects.create(custom_name="a-llm", org=acme)


def bulk_save(client, graph, prompts):
    """Save the graph's one CDT node, updating it when an earlier save created it."""
    graph.refresh_from_db()
    node = ClassificationDecisionTableNode.objects.filter(graph=graph).first()
    node_data = {"graph": graph.id, "node_name": "cdt", "prompt_configs": prompts}
    if node:
        node_data["id"] = node.id
    payload = {
        "save_version": graph.save_version,
        "classification_decision_table_node_list": [node_data],
    }
    return client.post(f"/api/graphs/{graph.id}/save/", payload, format="json")


@pytest.mark.django_db
def test_bulk_save_stores_a_system_one_entry(client_a, graph, acme_config):
    resp = bulk_save(client_a, graph, [system_one_prompt(acme_config.id)])

    assert resp.status_code == 200, resp.content
    prompt = ClassificationDecisionTablePrompt.objects.get(prompt_key="company_check")
    assert prompt.kind == "system_one"
    assert prompt.system_one_config_id == acme_config.id
    assert prompt.questions == QUESTIONS
    assert prompt.input_map == INPUT_MAP
    assert prompt.llm_config_id is None


NULL_CRITERIA_QUESTIONS = {
    "is_engineering": {"type": "noul", "instructions": "Engineering?", "criteria": None}
}


@pytest.mark.django_db
def test_bulk_save_stores_questions_normalised(client_a, graph, acme_config):
    prompt = system_one_prompt(acme_config.id, questions=NULL_CRITERIA_QUESTIONS)

    resp = bulk_save(client_a, graph, [prompt])

    assert resp.status_code == 200, resp.content
    stored = ClassificationDecisionTablePrompt.objects.get(prompt_key="company_check")
    assert stored.questions == QUESTIONS


@pytest.mark.django_db
def test_single_node_save_stores_questions_normalised(client_a, graph, acme_config):
    prompt = system_one_prompt(acme_config.id, questions=NULL_CRITERIA_QUESTIONS)

    resp = client_a.post(
        CDT_URL,
        {"graph": graph.id, "node_name": "cdt1", "prompt_configs": [prompt]},
        format="json",
    )

    assert resp.status_code == 201, resp.content
    stored = ClassificationDecisionTablePrompt.objects.get(prompt_key="company_check")
    assert stored.questions == QUESTIONS


@pytest.mark.django_db
def test_bulk_save_accepts_an_incomplete_system_one_entry(client_a, graph):
    resp = bulk_save(client_a, graph, [system_one_prompt(None, questions={})])

    assert resp.status_code == 200, resp.content
    prompt = ClassificationDecisionTablePrompt.objects.get(prompt_key="company_check")
    assert prompt.kind == "system_one"
    assert prompt.system_one_config_id is None
    assert prompt.questions == {}


@pytest.mark.django_db
def test_entry_without_kind_is_still_an_llm_entry(client_a, graph, acme_llm_config):
    prompt_data = {"prompt_key": "p1", "llm_config": acme_llm_config.id}

    resp = bulk_save(client_a, graph, [prompt_data])

    assert resp.status_code == 200, resp.content
    prompt = ClassificationDecisionTablePrompt.objects.get(prompt_key="p1")
    assert prompt.kind == "llm"
    assert prompt.llm_config_id == acme_llm_config.id


@pytest.mark.django_db
def test_bulk_save_refuses_another_orgs_config(client_a, graph, beta):
    other = SystemOneConfig.objects.create(org=beta, custom_name="b", provider="llm")

    resp = bulk_save(client_a, graph, [system_one_prompt(other.id)])

    assert resp.status_code == 400, resp.content
    assert "system_one_config" in str(resp.content)
    assert not ClassificationDecisionTablePrompt.objects.filter(system_one_config=other).exists()


@pytest.mark.django_db
def test_single_node_save_refuses_another_orgs_config(client_a, graph, beta):
    other = SystemOneConfig.objects.create(org=beta, custom_name="b", provider="llm")

    resp = client_a.post(
        CDT_URL,
        {
            "graph": graph.id,
            "node_name": "cdt1",
            "prompt_configs": [system_one_prompt(other.id)],
        },
        format="json",
    )

    assert resp.status_code == 400, resp.content
    assert "system_one_config" in str(resp.content)
    assert not ClassificationDecisionTableNode.objects.filter(node_name="cdt1").exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"questions": {"class": QUESTIONS["is_engineering"]}}, "questions"),
        ({"questions": {"_x": QUESTIONS["is_engineering"]}}, "questions"),
        ({"questions": {"q": {"type": "noul"}}}, "questions"),
        ({"questions": []}, "questions"),
        ({"llm_config": "ACME_LLM"}, "llm_config"),
        ({"input_map": {"a": 1}}, "input_map"),
        ({"kind": "llm"}, "kind"),
        ({"kind": "other"}, "kind"),
    ],
)
def test_bulk_save_refuses_an_invalid_entry(
    client_a, graph, acme_config, acme_llm_config, overrides, field
):
    overrides = {
        key: acme_llm_config.id if value == "ACME_LLM" else value
        for key, value in overrides.items()
    }

    resp = bulk_save(client_a, graph, [system_one_prompt(acme_config.id, **overrides)])

    assert resp.status_code == 400, resp.content
    assert field in str(resp.content)
    assert not ClassificationDecisionTablePrompt.objects.filter(prompt_key="company_check").exists()


@pytest.mark.django_db
def test_changing_the_kind_of_an_existing_entry_is_refused(client_a, graph):
    assert bulk_save(client_a, graph, [{"prompt_key": "p1"}]).status_code == 200

    resp = bulk_save(client_a, graph, [{"prompt_key": "p1", "kind": "system_one", "questions": {}}])

    assert resp.status_code == 400, resp.content
    assert "kind" in str(resp.content)
    assert ClassificationDecisionTablePrompt.objects.get(prompt_key="p1").kind == "llm"


@pytest.mark.django_db
def test_resending_a_system_one_entry_without_kind_and_with_an_llm_config_is_refused(
    client_a, graph, acme_config, acme_llm_config
):
    assert bulk_save(client_a, graph, [system_one_prompt(acme_config.id)]).status_code == 200

    resp = bulk_save(
        client_a,
        graph,
        [{"prompt_key": "company_check", "llm_config": acme_llm_config.id}],
    )

    assert resp.status_code == 400, resp.content
    assert "llm_config" in str(resp.content)


@pytest.mark.django_db
def test_resaving_without_kind_keeps_the_stored_system_one_fields(client_a, graph, acme_config):
    assert bulk_save(client_a, graph, [system_one_prompt(acme_config.id)]).status_code == 200

    resp = bulk_save(client_a, graph, [{"prompt_key": "company_check", "prompt_text": "x"}])

    assert resp.status_code == 200, resp.content
    prompt = ClassificationDecisionTablePrompt.objects.get(prompt_key="company_check")
    assert (prompt.kind, prompt.system_one_config_id, prompt.questions) == (
        "system_one",
        acme_config.id,
        QUESTIONS,
    )


@pytest.mark.django_db
def test_deleting_the_config_keeps_the_entry_without_it(client_a, graph, acme_config):
    assert bulk_save(client_a, graph, [system_one_prompt(acme_config.id)]).status_code == 200

    resp = client_a.delete(f"/api/system-one-configs/{acme_config.id}/")

    assert resp.status_code == 204, resp.content
    prompt = ClassificationDecisionTablePrompt.objects.get(prompt_key="company_check")
    assert prompt.system_one_config_id is None
    assert prompt.kind == "system_one"


@pytest.mark.django_db
def test_a_payload_repeating_a_prompt_key_is_refused(client_a, graph, acme_llm_config):
    resp = bulk_save(
        client_a,
        graph,
        [
            {"prompt_key": "p2", "llm_config": acme_llm_config.id},
            {"prompt_key": "p1", "llm_config": acme_llm_config.id},
            {"prompt_key": "p1", "kind": "system_one"},
            {"prompt_key": "p2", "kind": "system_one"},
        ],
    )

    assert resp.status_code == 400, resp.content
    assert (
        resp.json()["message"]
        == "prompt_configs: p2: prompt_key: Each prompt name can appear only once."
    )
    assert not ClassificationDecisionTablePrompt.objects.filter(
        prompt_key__in=["p1", "p2"]
    ).exists()
