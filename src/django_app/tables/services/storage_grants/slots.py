from dataclasses import dataclass
from enum import Enum

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


class StorageUse(Enum):
    """How a slot comes to touch storage, which decides whether an unconfigured slot is locked.

    SWITCH: the node has a `use_storage` switch (with the slot's prefix).
    ALWAYS: the node reads storage whenever it runs.
    TOOLS: the node touches storage through the Python tools it uses that have storage on.
    """

    SWITCH = "switch"
    ALWAYS = "always"
    TOOLS = "tools"


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
        storage_use: How the slot touches storage. A slot that is not configured runs
            with every action, so it is locked like a granted one when it touches storage.
        actions: The actions the node has a box for. File Extractor and Audio to Text only read.
    """

    prefix: str = ""
    steering_fields: tuple[str, ...] = ()
    code_fields: tuple[str, ...] = ()
    storage_use: StorageUse = StorageUse.SWITCH
    actions: tuple[StorageAction, ...] = tuple(action for action, _ in GRANT_ACTION_NAMES)

    @property
    def use_storage_field(self) -> str:
        """The node's storage switch, for a `StorageUse.SWITCH` slot."""
        if self.storage_use is not StorageUse.SWITCH:
            raise ValueError("Only a slot with a storage switch has a use_storage field.")
        return f"{self.prefix}use_storage"

    @property
    def flag_names(self) -> tuple[str, ...]:
        """The columns holding the slot's actions, in the order read, write, delete."""
        return tuple(
            f"{self.prefix}storage_grant_{name}"
            for action, name in GRANT_ACTION_NAMES
            if action in self.actions
        )


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
    FileExtractorNode: (
        GrantSlot(
            steering_fields=("input_map",),
            storage_use=StorageUse.ALWAYS,
            actions=(StorageAction.READ,),
        ),
    ),
    AudioTranscriptionNode: (
        GrantSlot(
            steering_fields=("input_map",),
            storage_use=StorageUse.ALWAYS,
            actions=(StorageAction.READ,),
        ),
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
