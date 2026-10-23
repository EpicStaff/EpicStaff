"""Import is a writer of a CDT node's `metadata["explanations"]` too: full import stores, and
partial (copy-paste) import returns, only what `PUT …/explanations/` would accept, and never
fail over an explanation."""

import pytest

from tables.constants.cdt_explanation_limits import MAX_STORED_EXPLANATIONS
from tables.import_export.enums import EntityType
from tables.import_export.registry import entity_registry
from tables.import_export.services.partial_export_service import (
    GraphPartialExportService,
    NodeRef,
)
from tables.import_export.services.partial_import_service import PartialImportService
from tables.models.graph_models import ClassificationDecisionTableNode, Graph


def _explanation(text="Checks the score."):
    return {"text": text, "generatedBy": "gpt-4o-mini", "fingerprint": "fp-1"}


_VALID = {"node:pre": _explanation()}
_MALFORMED = {
    **_VALID,
    "rule:name:numeric:decision": {"text": 123, "generatedBy": "g", "fingerprint": "f"},
    "rule:name:partial:decision": {"text": "t"},
    "rule:name:extra:decision": {**_explanation(), "extra": "dropped"},
    "k" * 513: _explanation(),
}
_TOO_MANY = {f"step-{index}": _explanation() for index in range(MAX_STORED_EXPLANATIONS + 1)}

CASES = [
    pytest.param(
        _MALFORMED, {**_VALID, "rule:name:extra:decision": _explanation()}, id="malformed"
    ),
    # Over a limit, entries are kept in step-key order until the map is full.
    pytest.param(
        _TOO_MANY,
        {key: _TOO_MANY[key] for key in sorted(_TOO_MANY)[:MAX_STORED_EXPLANATIONS]},
        id="too-many-entries",
    ),
]


def _source_node(org, explanations):
    graph = Graph.objects.create(name="cdt-explanations-source", org=org)
    # Through the ORM, the way graphs saved before validation hold them.
    return ClassificationDecisionTableNode.objects.create(
        graph=graph, node_name="cdt", metadata={"color": "#fff", "explanations": explanations}
    )


@pytest.mark.parametrize(("exported", "imported"), CASES)
@pytest.mark.django_db
def test_graph_import_stores_only_storable_explanations(
    default_org, export_service, import_service, exported, imported
):
    source = _source_node(default_org, exported)
    export_data = export_service.export_entities(EntityType.GRAPH, [source.graph_id])

    id_mapper, _ = import_service.import_data(export_data, EntityType.GRAPH)

    new_graph_id = id_mapper.get_created_ids(EntityType.GRAPH)[0]
    node = ClassificationDecisionTableNode.objects.get(graph_id=new_graph_id)
    assert node.metadata["explanations"] == imported
    assert node.metadata["color"] == "#fff"


@pytest.mark.parametrize(("exported", "imported"), CASES)
@pytest.mark.django_db
def test_partial_import_returns_only_storable_explanations(default_org, exported, imported):
    source = _source_node(default_org, exported)
    export = GraphPartialExportService(entity_registry).export(
        [NodeRef(entity_type=EntityType.CLASSIFICATION_DECISION_TABLE_NODE, node_id=source.id)],
        org_id=default_org.id,
    )
    assert not export.has_errors, export.errors
    target = Graph.objects.create(name="cdt-explanations-target", org=default_org)

    result = PartialImportService(entity_registry).import_data(
        export.data, target, org_id=default_org.id
    )

    [node] = result.content["classification_decision_table_node_list"]
    assert node["metadata"]["explanations"] == imported
    assert node["metadata"]["color"] == "#fff"
