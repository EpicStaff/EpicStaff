"""The forecast runs Weather started, and what a person sees of one.

Which person started which run is kept in Weather's database, so a run started before a
restart is still found after it, by the same person in the same organization only. A run is
kept for 7 days: the hourly purge (`weather_plugin.retention`) deletes older ones.
"""

from typing import Annotated, Any, Literal

from epicstaff_plugin.client import FlowSession
from pydantic import BaseModel, ConfigDict, StringConstraints, ValidationError

from weather_plugin.database import WeatherDatabase

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
    """The runs Weather started, each visible only to its person in its organization."""

    def __init__(self, database: WeatherDatabase):
        self._database = database

    async def add(self, org_id: int, user_id: int, session_id: int, city: str) -> None:
        """Record that the person started this run."""
        async with self._database.transaction(org_id) as connection:
            await connection.execute(
                "INSERT INTO weather.forecast_runs (org_id, user_id, session_id, city)"
                " VALUES (%s, %s, %s, %s)",
                (org_id, user_id, session_id, city),
            )

    async def started_by(self, org_id: int, user_id: int, session_id: int) -> bool:
        """Whether this person started the run in this organization."""
        async with self._database.transaction(org_id) as connection:
            cursor = await connection.execute(
                "SELECT 1 FROM weather.forecast_runs WHERE session_id = %s AND user_id = %s",
                (session_id, user_id),
            )
            return await cursor.fetchone() is not None


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
