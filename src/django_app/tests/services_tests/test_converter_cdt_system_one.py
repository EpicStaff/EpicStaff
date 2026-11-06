import pytest
from rbac.models import Organization
from tables.models import (
    ClassificationDecisionTableNode,
    Graph,
    LLMConfig,
    LLMModel,
    Provider,
    SystemOneConfig,
)
from tables.models.graph_models import ClassificationDecisionTablePrompt
from tables.services.converter_service import ConverterService
from tables.services.secrets import secret_resolver, secret_service
from utils.graph_utils import NodeNameResolver

QUESTIONS = {"is_engineering": {"type": "noul", "instructions": "Engineering?"}}
INPUT_MAP = {"company": "variables.company"}


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org CDT System One")


@pytest.fixture
def default_llm(org):
    provider, _ = Provider.objects.get_or_create(name="openai")
    model = LLMModel.objects.create(name="gpt-default", llm_provider=provider)
    return LLMConfig.objects.create(custom_name="default-llm", model=model, org=org)


@pytest.fixture
def secret(org):
    return secret_service.create(text="ts-key", org=org, name="typesafe-key")


@pytest.fixture
def typesafe_config(org, secret):
    return SystemOneConfig.objects.create(
        org=org,
        custom_name="jev",
        provider="typesafe",
        model_name="jev-1.14.0",
        api_key_secret=secret,
    )


@pytest.fixture
def node(org, default_llm):
    graph = Graph.objects.create(name="cdt-s1", org=org)
    return ClassificationDecisionTableNode.objects.create(
        graph=graph, default_llm_config=default_llm
    )


def add_entry(node, config):
    ClassificationDecisionTablePrompt.objects.create(
        cdt_node=node,
        prompt_key="company_check",
        kind="system_one",
        system_one_config=config,
        questions=QUESTIONS,
        input_map=INPUT_MAP,
        result_variable="company_check",
    )


def convert(node):
    node = ClassificationDecisionTableNode.objects.get(pk=node.pk)
    return ConverterService().convert_classification_decision_table_node_to_pydantic(
        node,
        resolver=NodeNameResolver(graph_id=node.graph_id),
        graph_id=node.graph_id,
    )


@pytest.mark.django_db
def test_system_one_entry_converts_without_the_default_llm_fallback(node, typesafe_config, secret):
    add_entry(node, typesafe_config)

    entry = convert(node).prompts["company_check"]

    assert entry.kind == "system_one"
    assert entry.llm_data is None
    assert entry.llm_id is None
    assert entry.system_one_config.provider == "typesafe"
    assert entry.system_one_config.model_name == "jev-1.14.0"
    assert entry.system_one_config.api_key_secret_id == secret.id
    assert entry.questions["is_engineering"].type == "noul"
    assert entry.input_map == INPUT_MAP
    assert entry.result_variable == "company_check"


@pytest.mark.django_db
def test_llm_entry_still_falls_back_to_the_default_llm(node, default_llm):
    ClassificationDecisionTablePrompt.objects.create(cdt_node=node, prompt_key="p1")

    entry = convert(node).prompts["p1"]

    assert entry.kind == "llm"
    assert entry.llm_id == default_llm.id
    assert entry.llm_data.provider == "openai"
    assert entry.system_one_config is None


@pytest.mark.django_db
def test_llm_backed_config_carries_its_llm_data(org, node, default_llm):
    config = SystemOneConfig.objects.create(
        org=org, custom_name="llm-backed", provider="llm", llm_config=default_llm
    )
    add_entry(node, config)

    entry = convert(node).prompts["company_check"]

    assert entry.system_one_config.llm_data.provider == "openai"
    assert entry.system_one_config.llm_data.config.model == "gpt-default"


@pytest.mark.django_db
def test_entry_whose_config_was_deleted_converts_with_no_config(node, typesafe_config):
    add_entry(node, typesafe_config)
    typesafe_config.delete()

    entry = convert(node).prompts["company_check"]

    assert entry.kind == "system_one"
    assert entry.system_one_config is None


@pytest.mark.django_db
def test_secret_resolver_fills_the_typesafe_key(org, node, typesafe_config):
    add_entry(node, typesafe_config)
    data = convert(node)

    resolved = secret_resolver.resolve_payload(payload=data, org_id=org.id)

    assert resolved.prompts["company_check"].system_one_config.api_key == "ts-key"
    assert data.prompts["company_check"].system_one_config.api_key is None


@pytest.mark.django_db
def test_stored_graph_schema_has_no_typesafe_key(node, typesafe_config):
    add_entry(node, typesafe_config)

    stored = convert(node).model_dump_json()

    assert "ts-key" not in stored
    assert "api_key_secret_id" not in stored
