"""The forecast runs this process started, and what a person sees of one.

Which person started which run is kept in this process's memory: enough for the sample,
which runs one process, but lost on every restart. This store is for the demo only; a real
plugin keeps it in its database.
"""

from collections import OrderedDict
from typing import Annotated, Any, Literal

from epicstaff_plugin.client import FlowSession
from pydantic import BaseModel, ConfigDict, StringConstraints, ValidationError

# Bounds the memory a burst of runs can take; the oldest run is forgotten first.
MAX_REMEMBERED_RUNS = 1024

ForecastStatus = Literal["pending", "running", "finished", "failed"]


class ForecastDay(BaseModel):
    model_config = ConfigDict(frozen=True)

    date: Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}$")]
    temperature_max: float
    temperature_min: float


class Forecast(BaseModel):
    """What the flow's Python node writes to `variables.forecast`."""

    model_config = ConfigDict(frozen=True)

    city: str
    days: list[ForecastDay]


class ForecastRuns:
    """The runs this process started, each visible only to its person in its organization."""

    def __init__(self) -> None:
        self._owners: OrderedDict[int, tuple[int, int]] = OrderedDict()

    def add(self, session_id: int, user_id: int, org_id: int) -> None:
        self._owners[session_id] = (user_id, org_id)
        while len(self._owners) > MAX_REMEMBERED_RUNS:
            self._owners.popitem(last=False)

    def started_by(self, session_id: int, user_id: int, org_id: int) -> bool:
        return self._owners.get(session_id) == (user_id, org_id)


def forecast_status(session: FlowSession) -> ForecastStatus:
    """Map EpicStaff's session status to the four states the Forecast page shows."""
    if session.status == "pending":
        return "pending"
    if not session.finished:
        return "running"
    return "finished" if session.succeeded else "failed"


def forecast_of(session: FlowSession) -> dict[str, Any] | None:
    """Return the forecast a finished run wrote, or None when it wrote none that fits."""
    if not session.succeeded or session.variables is None:
        return None
    try:
        return Forecast.model_validate(session.variables.get("forecast")).model_dump()
    except ValidationError:
        return None
