import abc

from application.commands import GetMetrics
from application.orchestrators.base import AbstractOrchestrator
from application.results import MetricsResult


class AbstractMetricsOrchestrator(
    AbstractOrchestrator[GetMetrics, MetricsResult], abc.ABC
):
    """Compute corpus metrics for the RAG named in the command."""
