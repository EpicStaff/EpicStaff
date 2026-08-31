import abc
from typing import Never

from application.commands import RunPrechunk
from application.orchestrators.base import AbstractOrchestrator


class AbstractPrechunkOrchestrator(AbstractOrchestrator[RunPrechunk, Never], abc.ABC):
    """Abstract base for producing preview chunks for a single document."""
