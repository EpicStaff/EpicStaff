"""System One prompt entries of a Classification Decision Table through flow and partial export/import."""

import json

import pytest
from rbac.models import Organization
from rest_framework.exceptions import ValidationError
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.registry import entity_registry
from tables.import_export.services.partial_export_service import (
    GraphPartialExportService,
    NodeRef,
)
from tables.import_export.strategies.nodes.classification_decision_table_node import (
    ClassificationDecisionTableNodeStrategy,
)
from tables.models import Graph, LLMConfig, SystemOneConfig
from tables.models.graph_models import (
    ClassificationDecisionTableNode,
    ClassificationDecisionTablePrompt,
)
from tables.services.secrets import secret_service

from tests.helpers import UNRESTRICTED_EXPORT_POLICY

QUESTIONS = {"is_engineering": {"type": "noul", "instructions": "Engineering?"}}
INPUT_MAP = {"company": "variables.company"}


@pytest.fixture
def target_org(db):
    return Organization.objects.create(name="Import target")


@pytest.fixture
def source_flow(default_org, llm_config):
    """A flow whose CDT holds a TypeSafe entry (with a secret) and an LLM-backed entry."""
    graph = Graph.objects.create(name="s1-flow", org=default_org)
    node = ClassificationDecisionTableNode.objects.create(graph=graph, node_name="cdt")
    secret = secret_service.create(text="ts-key", org=default_org, name="TS")
    typesafe = SystemOneConfig.objects.create(
        org=default_org,
        custom_name="jev",
        provider="typesafe",
        model_name="jev-1.14.0",
        api_key_secret=secret,
    )
    llm_backed = SystemOneConfig.objects.create(
        org=default_org, custom_name="llm-s1", provider="llm", llm_config=llm_config
    )
    for key, config in (("jev_check", typesafe), ("llm_check", llm_backed)):
        ClassificationDecisionTablePrompt.objects.create(
            cdt_node=node,
            prompt_key=key,
            kind="system_one",
            system_one_config=config,
            questions=QUESTIONS,
            input_map=INPUT_MAP,
            result_variable=key,
        )
    return graph, node


def _cdt_prompts_of(data):
    [cdt_node] = data[EntityType.GRAPH][0]["nodes"]
    return cdt_node["prompt_configs"]


def _imported_prompts(id_mapper, target_org):
    new_graph_id = id_mapper.get_created_ids(EntityType.GRAPH)[0]
    return {
        prompt.prompt_key: prompt
        for prompt in ClassificationDecisionTablePrompt.objects.filter(
            cdt_node__graph_id=new_graph_id
        ).select_related("system_one_config__llm_config")
    }


@pytest.mark.django_db
def test_flow_export_carries_system_one_configs_and_no_secret(source_flow, export_service):
    graph, _ = source_flow

    data = export_service.export_entities(
        EntityType.GRAPH, [graph.id], policy=UNRESTRICTED_EXPORT_POLICY
    ).data

    assert sorted(c["custom_name"] for c in data[EntityType.SYSTEM_ONE_CONFIG]) == ["jev", "llm-s1"]
    assert [c["custom_name"] for c in data[EntityType.LLM_CONFIG]] == ["MyGPT-4o"]
    assert "api_key_secret" not in json.dumps(data)
    exported = {p["prompt_key"]: p for p in _cdt_prompts_of(data)}
    assert exported["jev_check"]["kind"] == "system_one"
    assert exported["jev_check"]["questions"] == QUESTIONS
    assert exported["jev_check"]["input_map"] == INPUT_MAP


@pytest.mark.django_db
def test_flow_import_into_another_org_recreates_the_configs_there(
    source_flow, export_service, import_service, target_org
):
    graph, _ = source_flow
    data = export_service.export_entities(
        EntityType.GRAPH, [graph.id], policy=UNRESTRICTED_EXPORT_POLICY
    ).data

    id_mapper, _ = import_service.import_data(data, EntityType.GRAPH, org_id=target_org.id)

    prompts = _imported_prompts(id_mapper, target_org)
    typesafe = prompts["jev_check"].system_one_config
    llm_backed = prompts["llm_check"].system_one_config
    assert (typesafe.org_id, typesafe.custom_name, typesafe.api_key_secret_id) == (
        target_org.id,
        "jev",
        None,
    )
    assert llm_backed.org_id == target_org.id
    assert llm_backed.llm_config.org_id == target_org.id
    for prompt in prompts.values():
        assert (prompt.kind, prompt.questions, prompt.input_map) == (
            "system_one",
            QUESTIONS,
            INPUT_MAP,
        )
        assert prompt.llm_config_id is None
    assert typesafe.id != SystemOneConfig.objects.get(custom_name="jev", org=graph.org).id


@pytest.mark.django_db
def test_partial_export_of_the_cdt_node_carries_its_system_one_configs(source_flow):
    graph, node = source_flow

    result = GraphPartialExportService(entity_registry).export(
        [NodeRef(entity_type=EntityType.CLASSIFICATION_DECISION_TABLE_NODE, node_id=node.id)],
        org_id=graph.org_id,
        policy=UNRESTRICTED_EXPORT_POLICY,
    )

    assert not result.has_errors, result.errors
    assert sorted(c["custom_name"] for c in result.data[EntityType.SYSTEM_ONE_CONFIG]) == [
        "jev",
        "llm-s1",
    ]
    assert [c["custom_name"] for c in result.data[EntityType.LLM_CONFIG]] == ["MyGPT-4o"]
    assert "api_key_secret" not in json.dumps(result.data)


def _node_data(**prompt_overrides):
    prompt = {"id": 1, "prompt_key": "company_check", "kind": "system_one", **prompt_overrides}
    return {"node_name": "cdt", "prompt_configs": [prompt]}


def _import_node(graph, node_data, id_mapper=None, org_id=None):
    id_mapper = id_mapper or IDMapper()
    id_mapper.map(EntityType.GRAPH, 1, graph.id)
    node_data["graph"] = 1
    return ClassificationDecisionTableNodeStrategy().create_entity(
        node_data, id_mapper, org_id=org_id or graph.org_id
    )


@pytest.mark.django_db
def test_import_refuses_invalid_questions_and_creates_nothing(default_org):
    graph = Graph.objects.create(name="target", org=default_org)

    with pytest.raises(ValidationError) as error:
        _import_node(graph, _node_data(questions={"class": {"type": "noul"}}))

    assert "questions" in error.value.detail


@pytest.mark.django_db
def test_import_refuses_an_invalid_input_map(default_org):
    graph = Graph.objects.create(name="target", org=default_org)

    with pytest.raises(ValidationError) as error:
        _import_node(graph, _node_data(questions=QUESTIONS, input_map={"company": 5}))

    assert "input_map" in error.value.detail


@pytest.mark.django_db
def test_import_refuses_an_unknown_kind(default_org):
    graph = Graph.objects.create(name="target", org=default_org)

    with pytest.raises(ValidationError) as error:
        _import_node(graph, _node_data(kind="bogus"))

    assert "kind" in error.value.detail


@pytest.mark.django_db
def test_a_bad_file_leaves_no_rows_behind(source_flow, export_service, import_service, target_org):
    graph, _ = source_flow
    data = export_service.export_entities(
        EntityType.GRAPH, [graph.id], policy=UNRESTRICTED_EXPORT_POLICY
    ).data
    _cdt_prompts_of(data)[0]["questions"] = {"class": {"type": "noul"}}
    before = (Graph.objects.count(), SystemOneConfig.objects.count())

    with pytest.raises(ValidationError) as error:
        import_service.import_data(data, EntityType.GRAPH, org_id=target_org.id)

    assert "questions" in error.value.detail
    assert (Graph.objects.count(), SystemOneConfig.objects.count()) == before


@pytest.mark.django_db
def test_import_drops_an_unmapped_system_one_config(default_org):
    graph = Graph.objects.create(name="target", org=default_org)
    foreign = SystemOneConfig.objects.create(
        org=Organization.objects.create(name="other"), custom_name="x", provider="typesafe"
    )

    node = _import_node(
        graph,
        _node_data(system_one_config=foreign.id, questions=QUESTIONS, input_map=INPUT_MAP),
    )

    prompt = ClassificationDecisionTablePrompt.objects.get(cdt_node=node)
    assert prompt.system_one_config_id is None
    assert (prompt.kind, prompt.questions, prompt.input_map) == ("system_one", QUESTIONS, INPUT_MAP)


@pytest.mark.django_db
def test_import_drops_the_other_kinds_field(default_org):
    graph = Graph.objects.create(name="target", org=default_org)
    llm_config = LLMConfig.objects.create(custom_name="llm", org=default_org)
    config = SystemOneConfig.objects.create(
        org=default_org, custom_name="jev", provider="typesafe", model_name="jev-1.14.0"
    )
    id_mapper = IDMapper()
    id_mapper.map(EntityType.LLM_CONFIG, llm_config.id, llm_config.id)
    id_mapper.map(EntityType.SYSTEM_ONE_CONFIG, config.id, config.id)

    system_one_node = _import_node(
        graph,
        _node_data(system_one_config=config.id, llm_config=llm_config.id),
        id_mapper=id_mapper,
    )
    llm_node = _import_node(
        graph,
        _node_data(kind="llm", system_one_config=config.id, llm_config=llm_config.id),
        id_mapper=id_mapper,
    )

    system_one_prompt = ClassificationDecisionTablePrompt.objects.get(cdt_node=system_one_node)
    llm_prompt = ClassificationDecisionTablePrompt.objects.get(cdt_node=llm_node)
    assert (system_one_prompt.system_one_config_id, system_one_prompt.llm_config_id) == (
        config.id,
        None,
    )
    assert (llm_prompt.system_one_config_id, llm_prompt.llm_config_id) == (None, llm_config.id)


@pytest.mark.django_db
def test_an_older_file_without_kind_imports_as_an_llm_entry(default_org):
    graph = Graph.objects.create(name="target", org=default_org)
    node_data = {"node_name": "cdt", "prompt_configs": [{"id": 1, "prompt_key": "old"}]}

    node = _import_node(graph, node_data)

    prompt = ClassificationDecisionTablePrompt.objects.get(cdt_node=node)
    assert (prompt.kind, prompt.system_one_config_id, prompt.questions) == ("llm", None, {})
