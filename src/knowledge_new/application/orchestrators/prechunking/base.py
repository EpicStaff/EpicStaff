import abc

from application.orchestrators.base import AbstractOrchestrator
from domain.models import PrechunkRequest, PrechunkResponse


class AbstractPrechunker(AbstractOrchestrator[PrechunkRequest, PrechunkResponse], abc.ABC):
    """Abstract base for producing preview chunks for a single document."""
