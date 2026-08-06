"""The six places Python code lives, declared once.

Both features that reason about node code read this: the session-start declaration
validator, and the Secret Usage sources. Duplicating the list is the failure this
prevents, and the risk is asymmetric — a site missed by the usage sources is a
wrong number on a dashboard, while a site missed by the validator is a hole in the
allow-list.

PythonCode is not OrgScopedModel and has no org column, which is why every entry
declares how it reaches the org.
"""

from dataclasses import dataclass

from tables.models import PythonCodeTool
from tables.models.graph_models import (
    ClassificationDecisionTableNode,
    ConditionalEdge,
    PythonNode,
    WebhookTriggerNode,
)

# Frontend NodeType values, from
# frontend/src/app/visual-programming/core/enums/node-type.ts. The backend's own
# NodeType (tables/import_export/enums.py) uses Django class names ("PythonNode")
# and is deliberately not reused: these strings are a wire contract.
NODE_TYPE_PYTHON = "python"
NODE_TYPE_WEBHOOK_TRIGGER = "webhook-trigger"
NODE_TYPE_CLASSIFICATION_TABLE = "classification-decision-table"
NODE_TYPE_EDGE = "edge"


@dataclass(frozen=True)
class PythonCodeSite:
    """One model field that points at a PythonCode."""

    model: type
    code_field: str
    node_type: str | None
    """A NODE_TYPE_* value, or None for PythonCodeTool, which is not a flow node."""
    org_path: str | None = "graph__org_id"
    """ORM path from this model to the org id. None means the model is a hybrid
    resource that must be scoped with org_visible_q instead (built-ins carry
    org=NULL, so an org_id filter would hide them)."""
    name_field: str | None = "node_name"
    """None means the row has no name of its own — ConditionalEdge, which borrows
    the identity of the node it branches off."""


PYTHON_CODE_SITES: tuple[PythonCodeSite, ...] = (
    PythonCodeSite(
        model=PythonNode, code_field="python_code", node_type=NODE_TYPE_PYTHON
    ),
    PythonCodeSite(
        model=WebhookTriggerNode,
        code_field="python_code",
        node_type=NODE_TYPE_WEBHOOK_TRIGGER,
    ),
    PythonCodeSite(
        model=ClassificationDecisionTableNode,
        code_field="pre_python_code",
        node_type=NODE_TYPE_CLASSIFICATION_TABLE,
    ),
    PythonCodeSite(
        model=ClassificationDecisionTableNode,
        code_field="post_python_code",
        node_type=NODE_TYPE_CLASSIFICATION_TABLE,
    ),
    PythonCodeSite(
        model=ConditionalEdge,
        code_field="python_code",
        node_type=NODE_TYPE_EDGE,
        name_field=None,
    ),
    PythonCodeSite(
        model=PythonCodeTool,
        code_field="python_code",
        node_type=None,
        org_path=None,
        name_field="name",
    ),
)

#: The five sites that live inside a graph. PythonCodeTool is org-owned rather than
#: graph-owned, so a per-graph walk cannot reach it — it is gated in the converter
#: instead (see declaration_validator.assert_tool_secrets_declared).
GRAPH_PYTHON_CODE_SITES: tuple[PythonCodeSite, ...] = tuple(
    site for site in PYTHON_CODE_SITES if site.org_path is not None
)
