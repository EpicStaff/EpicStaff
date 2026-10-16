"""The flow node fields that hold a PythonCode, described once for the suites that check
a PythonCode field on every write and read path (node API, bulk save, import, export,
copy, session data).

Each slot knows how to create its node through the ORM, how to describe it in a request,
and where its code sits in an export and in the session `GraphData`, so a test
parametrized over `PYTHON_CODE_SLOTS` exercises the same behaviour on every code slot.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from django.db.models import Model

from tables.import_export.enums import EntityType
from tables.models import Graph, PythonCode
from tables.models.graph_models import (
    ClassificationDecisionTableNode,
    PythonNode,
    WebhookTriggerNode,
)


@dataclass(frozen=True)
class PythonCodeSlot:
    """One node field holding a PythonCode, and how tests build and address it.

    Attributes:
        id: Readable pytest id.
        basename: DRF router basename of the node's own endpoint.
        graph_list_key: The node's `<type>_node_list` key on Graph and in bulk save.
        code_field: The node's PythonCode field: its key in a request, an export and
            the session node data.
        entity_type: The node's `node_type` in a graph export.
        session_list_key: The list on the session `GraphData` holding the node.
        request_fields: Request fields the node needs besides graph, name and the code.
    """

    id: str
    model: type[Model]
    basename: str
    graph_list_key: str
    code_field: str
    entity_type: EntityType
    session_list_key: str
    request_fields: Callable[[], dict[str, Any]] = dict

    def create(self, graph: Graph, python_code: PythonCode) -> Model:
        return self.model.objects.create(
            graph=graph, node_name=f"{self.id}-node", **{self.code_field: python_code}
        )

    def request_body(self, graph: Graph, python_code: dict, **fields) -> dict[str, Any]:
        return {
            "graph": graph.id,
            "node_name": f"{self.id}-node",
            self.code_field: python_code,
            **self.request_fields(),
            **fields,
        }

    def python_code_of(self, node: Model) -> PythonCode:
        return getattr(node, self.code_field)

    def only_node_in(self, graph: Graph) -> Model:
        return self.model.objects.select_related(self.code_field).get(graph=graph)

    def stored_timeout(self, node_id: int) -> int:
        node = self.model.objects.select_related(self.code_field).get(pk=node_id)
        return self.python_code_of(node).execution_timeout


PYTHON_CODE_SLOTS = [
    PythonCodeSlot(
        id="python-node",
        model=PythonNode,
        basename="pythonnode",
        graph_list_key="python_node_list",
        code_field="python_code",
        entity_type=EntityType.PYTHON_NODE,
        session_list_key="python_node_list",
    ),
    PythonCodeSlot(
        id="webhook-trigger-node",
        model=WebhookTriggerNode,
        basename="webhooktriggernode",
        graph_list_key="webhook_trigger_node_list",
        code_field="python_code",
        entity_type=EntityType.WEBHOOK_TRIGGER_NODE,
        session_list_key="webhook_trigger_node_data_list",
        request_fields=lambda: {"metadata": {}},
    ),
    PythonCodeSlot(
        id="cdt-pre-computation",
        model=ClassificationDecisionTableNode,
        basename="classificationdecisiontablenode",
        graph_list_key="classification_decision_table_node_list",
        code_field="pre_python_code",
        entity_type=EntityType.CLASSIFICATION_DECISION_TABLE_NODE,
        session_list_key="classification_decision_table_node_list",
    ),
    PythonCodeSlot(
        id="cdt-post-computation",
        model=ClassificationDecisionTableNode,
        basename="classificationdecisiontablenode",
        graph_list_key="classification_decision_table_node_list",
        code_field="post_python_code",
        entity_type=EntityType.CLASSIFICATION_DECISION_TABLE_NODE,
        session_list_key="classification_decision_table_node_list",
    ),
]

PYTHON_CODE_SLOT_IDS = [slot.id for slot in PYTHON_CODE_SLOTS]
