import abc

from application.commands import (
    GetEntityDetail,
    GetGraphVisualization,
    GetRelationshipDetail,
)
from application.orchestrators.base import AbstractOrchestrator
from application.results import (
    EntityDetailResult,
    GraphVisualizationResult,
    RelationshipDetailResult,
)


class AbstractGraphVisualizationOrchestrator(
    AbstractOrchestrator[GetGraphVisualization, GraphVisualizationResult], abc.ABC
):
    """Read the graph index output and return entities and relationships."""


class AbstractEntityDetailOrchestrator(
    AbstractOrchestrator[GetEntityDetail, EntityDetailResult], abc.ABC
):
    """Return the description of a single entity from the graph index output."""


class AbstractRelationshipDetailOrchestrator(
    AbstractOrchestrator[GetRelationshipDetail, RelationshipDetailResult], abc.ABC
):
    """Return the description of a single relationship from the graph index output."""
