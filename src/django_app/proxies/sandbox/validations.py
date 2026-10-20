"""Rules a venv must satisfy before the gateway passes a request upstream.

The sandbox service owns a venv's own invariants; what it cannot see is this
side of the boundary -- which rows in this database point at it, who may reach
it, what state the local bindings are in. Those rules live here, one function
per rule, each raising from `errors` so the viewset only decides when to ask.
"""

from django.db.models import Q
from tables.models.graph_models import (
    ClassificationDecisionTableNode,
    PythonNode,
    WebhookTriggerNode,
)
from tables.models.python_models import PythonCode, PythonCodeTool

from proxies.sandbox.errors import VenvInUseError

__all__ = ["assert_venv_unused"]

# Enough to recognise what is in the way, without an unbounded error message.
MAX_NAMED_OWNERS = 5


def assert_venv_unused(venv_id: int) -> None:
    """Refuse to release a venv that some Python code still runs in.

    `PythonCode.venv_id` is a plain integer column with no foreign key behind it,
    so nothing in the database stops a venv from being deleted out from under the
    code that runs in it.

    Raises:
        VenvInUseError: A `PythonCode` points at this venv. Rendered as 409.
    """
    code_ids = list(PythonCode.objects.filter(venv_id=venv_id).values_list("pk", flat=True))
    if not code_ids:
        return
    raise VenvInUseError(_describe_owners(code_ids))


def _describe_owners(code_ids: list[int]) -> str:
    names = _owner_names(code_ids)
    if not names:
        # Deleting a tool or a node does not delete its PythonCode, so a row can
        # outlive everything that referenced it. Nothing in the UI points at what
        # is holding the venv, so say that instead of naming nothing.
        return (
            "This environment is still referenced by Python code that no tool or node "
            "uses any more."
        )

    shown = ", ".join(names[:MAX_NAMED_OWNERS])
    if len(names) > MAX_NAMED_OWNERS:
        shown = f"{shown} and {len(names) - MAX_NAMED_OWNERS} more"
    return (
        f"This environment is still used by {shown}. "
        "Move them to another environment before deleting it."
    )


def _owner_names(code_ids: list[int]) -> list[str]:
    """Every tool and node whose code runs in the venv, binned ones included.

    `all_objects` on purpose: a tool or node in the recycle bin can be restored,
    so it still needs the environment it was built against.
    """
    tools = PythonCodeTool.all_objects.filter(python_code_id__in=code_ids).values_list(
        "name", flat=True
    )
    python_nodes = PythonNode.all_objects.filter(python_code_id__in=code_ids).values_list(
        "node_name", flat=True
    )
    webhook_nodes = WebhookTriggerNode.all_objects.filter(python_code_id__in=code_ids).values_list(
        "node_name", flat=True
    )
    decision_tables = ClassificationDecisionTableNode.all_objects.filter(
        Q(pre_python_code_id__in=code_ids) | Q(post_python_code_id__in=code_ids)
    ).values_list("node_name", flat=True)
    return sorted({*tools, *python_nodes, *webhook_nodes, *decision_tables})
