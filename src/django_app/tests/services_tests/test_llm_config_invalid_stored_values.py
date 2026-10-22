"""A config row saved before the API validated its JSON fields must fail as a domain error.

The rows are written through the ORM, bypassing the serializer, as older rows were.
"""

import pytest

from rbac.models import Organization
from tables.exceptions import CdtExplainLLMConfigInvalidError
from tables.models import Graph, LLMConfig, Provider
from tables.models.graph_models import ClassificationDecisionTableNode
from tables.models.llm_models import LLMModel
from tables.services.cdt_explain.service import CdtExplainService
from tables.services.llm_clients import InvalidLLMConfigError, get_llm_client


@pytest.fixture
def org(db):
    yield Organization.objects.create(name="Invalid stored values org")


@pytest.fixture
def model(db):
    provider, _ = Provider.objects.get_or_create(name="openai")
    yield LLMModel.objects.create(name="epicstaff-stored-shape-model", llm_provider=provider)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "field_name, value",
    [
        ("extra_headers", {"X-Retry": 3}),
        ("logit_bias", {"foo": 1}),
        ("stop", {"a": 1}),
    ],
)
def test_get_llm_client_raises_invalid_config_naming_the_field(org, model, field_name, value):
    config = LLMConfig.objects.create(
        custom_name="malformed", model=model, org=org, **{field_name: value}
    )

    with pytest.raises(InvalidLLMConfigError) as excinfo:
        get_llm_client(config, api_key=None)

    assert excinfo.value.field_names == [field_name]
    assert field_name in str(excinfo.value)


@pytest.mark.django_db
def test_cdt_explain_returns_invalid_config_error(org, model):
    graph = Graph.objects.create(name="cdt", org=org)
    node = ClassificationDecisionTableNode.objects.create(graph=graph, node_name="cdt_node")
    config = LLMConfig.objects.create(
        custom_name="malformed", model=model, org=org, logit_bias={"foo": 1}
    )

    with pytest.raises(CdtExplainLLMConfigInvalidError) as excinfo:
        CdtExplainService().explain(
            pk=node.pk,
            org_id=org.id,
            llm_config_id=config.id,
            table={},
            blocks=[{"id": "block-1"}],
        )

    assert excinfo.value.status_code == 400
    assert "logit_bias" in str(excinfo.value.detail)
