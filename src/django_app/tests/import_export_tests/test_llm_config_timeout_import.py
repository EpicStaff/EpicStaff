"""`timeout` of an imported LLM config.

Invariant: an import moves a timeout outside the bounds onto the nearest bound instead of
failing, because a file from before the bound existed can carry any number: below 1 is
stored as 1, above the deployment maximum (and Infinity) as the maximum, NaN as the field
default (120). Null stays null and a numeric string is read as its number. A value that is
not a number rejects the whole import, full or partial, with 400 and nothing created.

Importing the same config again reuses the one the first import created: the existing
config is matched on the timeout the import stores, not on the raw value in the file.
"""

import copy
import math

import pytest
from django.conf import settings
from django.urls import reverse
from rest_framework import status

from rbac.models import Organization
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.registry import entity_registry
from tables.import_export.services.partial_export_service import (
    GraphPartialExportService,
    NodeRef,
)
from tables.models import Graph, LLMConfig
from tables.models.graph_models import ClassificationDecisionTableNode
from tests.helpers import UNRESTRICTED_EXPORT_POLICY, data_to_json_file

MAX_SECONDS = settings.LLM_CONFIG_TIMEOUT_MAX_SECONDS


@pytest.fixture
def exported_config(export_service, gpt_4o_llm, default_org) -> dict:
    config = LLMConfig.objects.create(
        custom_name="timeout-import", model=gpt_4o_llm, org=default_org
    )
    export_data = export_service.export_entities(
        EntityType.LLM_CONFIG, [config.id], policy=UNRESTRICTED_EXPORT_POLICY
    ).data
    return copy.deepcopy(export_data[EntityType.LLM_CONFIG][0])


def _import_as_dependency(config_data: dict, org) -> LLMConfig:
    """Import the config the way a flow or agent that uses it does: reuse a matching
    config of the importing org, otherwise create one."""
    mapper = IDMapper()
    mapper.map(EntityType.LLM_MODEL, config_data["model"], config_data["model"], False)
    return entity_registry.get_strategy(EntityType.LLM_CONFIG).import_entity(
        config_data, mapper, is_main=False, org_id=org.id
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("in_file", "stored"),
    [
        (0.5, 1.0),
        (MAX_SECONDS + 1, MAX_SECONDS),
        (math.nan, 120.0),
        (math.inf, MAX_SECONDS),
        (-math.inf, 1.0),
        (None, None),
        ("120", 120.0),
    ],
    ids=["below-minimum", "above-maximum", "nan", "infinity", "negative-infinity", "null", "string"],
)
def test_imported_timeout_is_stored_within_the_bounds(exported_config, in_file, stored):
    exported_config["timeout"] = in_file
    importing_org = Organization.objects.create(name="timeout-import-target")

    imported = _import_as_dependency(exported_config, importing_org)

    imported.refresh_from_db()
    assert imported.timeout == stored


@pytest.mark.django_db
def test_reimporting_a_config_with_an_out_of_range_timeout_reuses_it(
    exported_config, default_org
):
    exported_config["timeout"] = MAX_SECONDS * 10
    # Back into the org it was exported from, after the original is gone: the first
    # import keeps its name, so only the timeout decides whether the second one matches.
    LLMConfig.objects.filter(pk=exported_config["id"]).delete()

    imported_ids = {
        _import_as_dependency(copy.deepcopy(exported_config), default_org).pk for _ in range(2)
    }

    assert len(imported_ids) == 1
    assert LLMConfig.objects.get(pk=imported_ids.pop()).timeout == MAX_SECONDS
    assert LLMConfig.objects.filter(org=default_org).count() == 1


def _flow_export(export_service, graph, timeout) -> dict:
    export_data = export_service.export_entities(
        EntityType.GRAPH, [graph.id], policy=UNRESTRICTED_EXPORT_POLICY
    ).data
    [config_entry] = export_data[EntityType.LLM_CONFIG]
    config_entry["timeout"] = timeout
    return export_data


@pytest.mark.django_db
def test_non_numeric_timeout_rejects_a_full_import(
    auth_client, export_service, exportable_graph_with_agent_node
):
    export_data = _flow_export(export_service, exportable_graph_with_agent_node, "abc")
    graph_count_before = Graph.objects.count()
    config_count_before = LLMConfig.objects.count()

    response = auth_client.post(
        reverse("graphs-import-entity"),
        {"file": data_to_json_file(data=export_data, filename="flow.json")},
        format="multipart",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert "timeout" in response.data["message"]
    assert Graph.objects.count() == graph_count_before
    assert LLMConfig.objects.count() == config_count_before


@pytest.mark.django_db
def test_non_numeric_timeout_rejects_a_partial_import(auth_client, gpt_4o_llm, default_org):
    graph = Graph.objects.create(name="timeout-partial-import", org=default_org)
    cdt_node = ClassificationDecisionTableNode.objects.create(
        graph=graph,
        node_name="classify",
        default_llm_config=LLMConfig.objects.create(
            custom_name="timeout-partial-import", model=gpt_4o_llm, org=default_org
        ),
    )
    result = GraphPartialExportService(entity_registry).export(
        [NodeRef(entity_type=EntityType.CLASSIFICATION_DECISION_TABLE_NODE, node_id=cdt_node.id)],
        org_id=default_org.id,
        policy=UNRESTRICTED_EXPORT_POLICY,
    )
    assert not result.has_errors, result.errors
    export_data = result.data
    [config_entry] = export_data[EntityType.LLM_CONFIG]
    config_entry["timeout"] = "abc"
    node_count_before = ClassificationDecisionTableNode.objects.count()
    config_count_before = LLMConfig.objects.count()

    response = auth_client.post(
        reverse("graphs-partial-import", args=[graph.id]),
        {"file": data_to_json_file(data=export_data, filename="nodes.json")},
        format="multipart",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert "timeout" in response.data["message"]
    assert ClassificationDecisionTableNode.objects.count() == node_count_before
    assert LLMConfig.objects.count() == config_count_before
