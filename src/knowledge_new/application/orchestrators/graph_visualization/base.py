import abc

from application.commands import GetGraphVisualization
from application.orchestrators.base import AbstractOrchestrator
from application.results import GraphVisualizationResult


class AbstractGraphVisualizationOrchestrator(
    AbstractOrchestrator[GetGraphVisualization, GraphVisualizationResult], abc.ABC
):
    """Read the graph index output and return entities, relationships and communities."""
