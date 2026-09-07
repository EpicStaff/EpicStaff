from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar, Optional

from tables.import_export.enums import NodeType


@dataclass
class _MissingSets:
    """Dataclass that holds all missing deps"""

    subgraphs: set
    llm_configs: set
    webhooks: set
    agent_definitions: set
    surfaces: set
    python_code_tools: set
    mcp_tools: set


class MissingDependencyHandler(ABC):
    node_type: ClassVar[NodeType]
    fk_field: ClassVar[str]
    missing_set_attr: ClassVar[str]
    dependency_label: ClassVar[str]

    def find_missing_id(self, node: dict, missing_sets: _MissingSets) -> Optional[int]:
        missing_ids = getattr(missing_sets, self.missing_set_attr)
        ref_id = node.get(self.fk_field)
        return ref_id if ref_id in missing_ids else None

    @abstractmethod
    def handle(self, node: dict, missing_id: int) -> tuple[bool, dict]:
        """Return (should_skip, warning_dict)."""
