import abc

from application.commands import GetIndexEstimate
from application.orchestrators.base import AbstractOrchestrator
from application.results import IndexEstimateResult


class AbstractEstimateOrchestrator(
    AbstractOrchestrator[GetIndexEstimate, IndexEstimateResult], abc.ABC
):
    """Abstract base for estimating the token usage and cost of indexing a RAG's documents.

    Read-only: implementations must not call providers or write to the database.
    """
