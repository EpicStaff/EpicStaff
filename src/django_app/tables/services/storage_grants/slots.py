from dataclasses import dataclass

from src.shared.models.storage_scope import StorageAction
from tables.models.graph_models import (
    AudioTranscriptionNode,
    ClassificationDecisionTableNode,
    FileExtractorNode,
    PythonNode,
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
            code does or reads, compared as stored.
        code_fields: Names of nested PythonCode fields on the node that hold the code.
    """

    prefix: str = ""
    steering_fields: tuple[str, ...] = ()
    code_fields: tuple[str, ...] = ()

    @property
    def flag_names(self) -> tuple[str, ...]:
        """The columns holding the slot's actions, in the order read, write, delete."""
        return tuple(f"{self.prefix}storage_grant_{name}" for _, name in GRANT_ACTION_NAMES)


# What a nested PythonCode changes about the run: its source, its entrypoint, the arguments
# it is called with and the environment it runs in (which is where its libraries come from).
PYTHON_CODE_STEERING_FIELDS: tuple[str, ...] = ("code", "entrypoint", "global_kwargs", "venv")

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

# Nodes that carry no grant but always read the flow's attached files: creating or
# changing one needs the Files permission behind Read, and deleting one needs nothing.
FILE_NODE_MODELS: tuple[type, ...] = (FileExtractorNode, AudioTranscriptionNode)
