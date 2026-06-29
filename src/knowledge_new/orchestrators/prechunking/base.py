import abc

from models import PrechunkRequest, PrechunkResponse
from orchestrators.base import AbstractOrchestrator


class AbstractPrechunker(AbstractOrchestrator[PrechunkRequest, PrechunkResponse], abc.ABC):
    """Abstract base for producing preview chunks for a single document."""
