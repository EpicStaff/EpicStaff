from dataclasses import dataclass

from src.shared.models.storage_scope import StorageAction
from tables.models.graph_models import (
    AgentNode,
    AudioTranscriptionNode,
    ClassificationDecisionTableNode,
    FileExtractorNode,
    PythonNode,
    TaskNode,
    WebhookTriggerNode,
)

GRANT_ACTION_NAMES: tuple[tuple[StorageAction, str], ...] = (
    (StorageAction.READ, "read"),
    (StorageAction.WRITE, "write"),
    (StorageAction.DELETE, "delete"),
)


@dataclass(frozen=True)
class GrantSlot:
    """One grant of a node: its flag columns and the node fields that steer what its code does.

    Attributes:
        prefix: Column prefix of the flags: "" for a node with one grant, "pre_" and
            "post_" for the two code slots of a classification decision table.
        steering_fields: Plain fields (and relations) of the node that change what the
            code does or reads, compared as stored. `surface_list`, `inline_surface` and
            `agent_definition` stand for the node's tools, which come from its surfaces.
        code_fields: Names of nested PythonCode fields on the node that hold the code.
    """

    prefix: str = ""
    steering_fields: tuple[str, ...] = ()
    code_fields: tuple[str, ...] = ()

    @property
    def flag_names(self) -> tuple[str, str, str]:
        """The columns holding read, write and delete, in that order."""
        read, write, delete = (
            f"{self.prefix}storage_grant_{name}" for _, name in GRANT_ACTION_NAMES
        )
        return read, write, delete


# What a nested PythonCode changes about the run: its source, its entrypoint, the arguments
# it is called with and the environment it runs in (which is where its libraries come from).
PYTHON_CODE_STEERING_FIELDS: tuple[str, ...] = ("code", "entrypoint", "global_kwargs", "venv")

# The tools of an agent or task node come from its surfaces, and the agent runs them as
# its prompt (instructions, task text, output schema) says.
_TOOL_STEERING_FIELDS = ("input_map", "agent_definition", "surface_list", "inline_surface")

# Every model carrying grants. Adding a code-running node type: give it
# `StorageGrantFields` (or per-slot columns), add its slots here, and nothing else
# changes: the write check, the import and copy caps, the flow-wide requirements and
# the bulk save all read this table.
STORAGE_GRANT_SLOTS: dict[type, tuple[GrantSlot, ...]] = {
    PythonNode: (
        GrantSlot(steering_fields=("input_map", "use_storage"), code_fields=("python_code",)),
    ),
    WebhookTriggerNode: (
        GrantSlot(steering_fields=("use_storage",), code_fields=("python_code",)),
    ),
    FileExtractorNode: (GrantSlot(steering_fields=("input_map",)),),
    AudioTranscriptionNode: (GrantSlot(steering_fields=("input_map",)),),
    AgentNode: (GrantSlot(steering_fields=(*_TOOL_STEERING_FIELDS, "tasks")),),
    TaskNode: (
        GrantSlot(steering_fields=(*_TOOL_STEERING_FIELDS, "instructions", "output_schema")),
    ),
    ClassificationDecisionTableNode: (
        GrantSlot(
            prefix="pre_",
            steering_fields=("pre_input_map", "pre_use_storage"),
            code_fields=("pre_python_code",),
        ),
        GrantSlot(
            prefix="post_",
            steering_fields=("post_input_map", "post_use_storage"),
            code_fields=("post_python_code",),
        ),
    ),
}
