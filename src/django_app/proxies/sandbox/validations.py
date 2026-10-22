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
from tables.models.python_models import PythonCodeTool

from proxies.sandbox.errors import VenvInUseError
from proxies.sandbox.models import SandboxVenvBinding

__all__ = ["assert_venv_unused"]

MAX_NAMED_OWNERS = 5


def assert_venv_unused(binding: SandboxVenvBinding) -> None:
    """Refuse to release a venv that some Python code still runs in.

    `PythonCode.venv` is PROTECTed, so the delete would fail regardless; this runs
    first so the caller is told what is in the way instead of getting an integrity
    error, and so the upstream venv is never removed before that is known.

    Raises:
        VenvInUseError: A `PythonCode` points at this venv. Rendered as 409.
    """
    code_ids = list(binding.python_codes.values_list("pk", flat=True))
    if not code_ids:
        return
    raise VenvInUseError(_describe_owners(code_ids))


def _describe_owners(code_ids: list[int]) -> str:
    live, binned = _owner_names(code_ids)
    if live:
        return (
            f"This environment is still used by {_name_list(live)}. "
            "Move them to another environment before deleting it."
        )
    if binned:
        # Telling the caller to move these would be a dead end: a binned tool or node
        # is in no flow and in no tool list, so there is nothing to open and change.
        return (
            f"This environment is kept by {_name_list(binned)} in the recycle bin, "
            "which could still be restored. Empty the recycle bin to release it."
        )
    # Deleting a tool or a node does not delete its PythonCode, so a row can
    # outlive everything that referenced it. Nothing in the UI points at what
    # is holding the venv, so say that instead of naming nothing.
    return "This environment is still referenced by Python code that no tool or node uses any more."


def _name_list(names: list[str]) -> str:
    shown = ", ".join(names[:MAX_NAMED_OWNERS])
    if len(names) > MAX_NAMED_OWNERS:
        shown = f"{shown} and {len(names) - MAX_NAMED_OWNERS} more"
    return shown


def _owner_names(code_ids: list[int]) -> tuple[list[str], list[str]]:
    """Every tool and node whose code runs in the venv, live ones and binned ones apart.

    Binned ones still hold the environment: they can be restored, and they would
    need the one they were built against. They are reported apart because the caller
    cannot act on them the way it acts on a live owner.

    The flag is read in the same pass rather than queried twice per model: the live
    and the binned name are wanted together, and one query per model answers both.
    """
    owners: list[tuple[str, bool]] = [
        *PythonCodeTool.all_objects.filter(python_code_id__in=code_ids).values_list(
            "name", "active"
        ),
        *PythonNode.all_objects.filter(python_code_id__in=code_ids).values_list(
            "node_name", "active"
        ),
        *WebhookTriggerNode.all_objects.filter(python_code_id__in=code_ids).values_list(
            "node_name", "active"
        ),
        *ClassificationDecisionTableNode.all_objects.filter(
            Q(pre_python_code_id__in=code_ids) | Q(post_python_code_id__in=code_ids)
        ).values_list("node_name", "active"),
    ]
    live = {name for name, active in owners if active}
    binned = {name for name, active in owners if not active} - live
    return sorted(live), sorted(binned)
