from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class NodeRef:
    """Reference to a node, either by real DB id or by temp_id."""

    is_temp: bool
    value: str | int


@dataclass(frozen=True, slots=True)
class ParsedNodeRef:
    """Result of parsing a node reference from payload data."""

    error: dict | str | None = None
    ref: NodeRef | None = None


@dataclass(slots=True)
class BuildSaveableResult:
    """Result of building a saveable from validated data."""

    error: dict | None = None
    inner_saveable: Any = None
    deferred_saveable: Any = None


@dataclass(slots=True)
class NodeListValidationResult:
    """Result of validating all items in one node list."""

    errors: list = field(default_factory=list)
    node_saveables: list = field(default_factory=list)
    deferred_saveables: list = field(default_factory=list)
    real_routing_node_ids: set[int] = field(default_factory=set)


@dataclass(slots=True)
class EdgeListValidationResult:
    """Result of validating all items in an edge list."""

    errors: list = field(default_factory=list)
    saveables: list = field(default_factory=list)
    real_node_ids: set[int] = field(default_factory=set)
