"""The five node types that carry `execution_timeout`, described once for the suites
that check the field on every write and read path (node API, bulk save, import,
export, copy, session data).

Each spec knows how to create its node through the ORM and how to describe it in a
create request, so a test parametrized over `EXECUTION_TIMEOUT_NODE_SPECS` exercises
the same behaviour on every node that runs code in the sandbox.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from django.db.models import Model

from tables.import_export.enums import EntityType
from tables.models import Graph, PythonCode
from tables.models.graph_models import (
    AudioTranscriptionNode,
    ClassificationDecisionTableNode,
    FileExtractorNode,
    PythonNode,
    WebhookTriggerNode,
)

PYTHON_CODE_DATA = {"code": "def main(**kwargs): return 1", "entrypoint": "main", "libraries": []}
FILE_INPUT_MAP = {"file": "variables.file"}


def _python_code() -> PythonCode:
    return PythonCode.objects.create(code=PYTHON_CODE_DATA["code"], entrypoint="main")


@dataclass(frozen=True)
class ExecutionTimeoutNodeSpec:
    """One node type with an execution timeout, and how tests build it.

    Attributes:
        id: Readable pytest id.
        model: The node model.
        basename: DRF router basename of the node's own endpoint.
        graph_list_key: The `<type>_node_list` key on Graph (related_name) and in
            the bulk-save payload.
        session_list_key: The list on the session `GraphData` holding the node.
        entity_type: The node's `node_type` in a graph export.
        extra_create_fields: ORM fields the node needs besides graph and name.
        extra_request_fields: Request fields the node's serializer needs besides
            graph and name.
    """

    id: str
    model: type[Model]
    basename: str
    graph_list_key: str
    session_list_key: str
    entity_type: EntityType
    extra_create_fields: Callable[[], dict[str, Any]] = field(default=lambda: {})
    extra_request_fields: dict[str, Any] = field(default_factory=dict)

    def create(self, graph: Graph, **fields) -> Model:
        fields.setdefault("node_name", f"{self.id}-node")
        return self.model.objects.create(graph=graph, **self.extra_create_fields(), **fields)

    def request_body(self, graph: Graph, **fields) -> dict[str, Any]:
        return {
            "graph": graph.id,
            "node_name": f"{self.id}-node",
            **self.extra_request_fields,
            **fields,
        }


EXECUTION_TIMEOUT_NODE_SPECS = [
    ExecutionTimeoutNodeSpec(
        id="python",
        model=PythonNode,
        basename="pythonnode",
        graph_list_key="python_node_list",
        session_list_key="python_node_list",
        entity_type=EntityType.PYTHON_NODE,
        extra_create_fields=lambda: {"python_code": _python_code()},
        extra_request_fields={"python_code": PYTHON_CODE_DATA},
    ),
    ExecutionTimeoutNodeSpec(
        id="webhook-trigger",
        model=WebhookTriggerNode,
        basename="webhooktriggernode",
        graph_list_key="webhook_trigger_node_list",
        session_list_key="webhook_trigger_node_data_list",
        entity_type=EntityType.WEBHOOK_TRIGGER_NODE,
        extra_create_fields=lambda: {"python_code": _python_code()},
        extra_request_fields={"python_code": PYTHON_CODE_DATA, "metadata": {}},
    ),
    ExecutionTimeoutNodeSpec(
        id="classification-decision-table",
        model=ClassificationDecisionTableNode,
        basename="classificationdecisiontablenode",
        graph_list_key="classification_decision_table_node_list",
        session_list_key="classification_decision_table_node_list",
        entity_type=EntityType.CLASSIFICATION_DECISION_TABLE_NODE,
    ),
    ExecutionTimeoutNodeSpec(
        id="file-extractor",
        model=FileExtractorNode,
        basename="fileextractornode",
        graph_list_key="file_extractor_node_list",
        session_list_key="file_extractor_node_list",
        entity_type=EntityType.FILE_EXTRACTOR_NODE,
        extra_create_fields=lambda: {"input_map": FILE_INPUT_MAP},
        extra_request_fields={"input_map": FILE_INPUT_MAP},
    ),
    ExecutionTimeoutNodeSpec(
        id="audio-transcription",
        model=AudioTranscriptionNode,
        basename="audiotranscriptionnode",
        graph_list_key="audio_transcription_node_list",
        session_list_key="audio_transcription_node_list",
        entity_type=EntityType.AUDIO_TRANSCRIPTION_NODE,
        extra_create_fields=lambda: {"input_map": FILE_INPUT_MAP},
        extra_request_fields={"input_map": FILE_INPUT_MAP},
    ),
]

EXECUTION_TIMEOUT_NODE_SPEC_IDS = [spec.id for spec in EXECUTION_TIMEOUT_NODE_SPECS]

# Values the API and import must reject rather than clamp: below the 1-minute minimum,
# missing a value, or not a whole number of minutes.
INVALID_EXECUTION_TIMEOUTS = [0, -5, None, 2.5, "ten"]
INVALID_EXECUTION_TIMEOUT_IDS = ["zero", "negative", "null", "fraction", "text"]
