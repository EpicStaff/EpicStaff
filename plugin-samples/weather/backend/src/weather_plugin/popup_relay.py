"""The relay a popup hands its OAuth result through when the provider has severed its opener.

The framed page opens the provider in a popup, with a `state` of the form `<org id>.<random>`.
When the provider's page sends `Cross-Origin-Opener-Policy`, the popup loses `window.opener`
and cannot post the result back. It then logs itself in (in the organization `state` names),
posts the result here, and the framed page polls for it. Each result is kept for the person
and organization that posted it, so nobody else can read it or replace it.

The results are kept in Weather's database for five minutes, so a restart in between loses
none. An expired result is never handed out, and the hourly purge (`weather_plugin.retention`)
deletes it.
"""

import re
from typing import Annotated, Any

from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from weather_plugin.database import WeatherDatabase

# Equals `patterns.popup_state` of the JS SDK's login protocol (`createPopupState`).
POPUP_STATE_PATTERN = r"^[1-9][0-9]{0,9}\.[A-Za-z0-9_-]{22,64}$"
RESULT_LIFETIME_SECONDS = 300
MAX_PARAMS = 20
MAX_PARAM_NAME_LENGTH = 256
MAX_PARAM_VALUE_LENGTH = 2048

PopupState = Annotated[str, StringConstraints(pattern=POPUP_STATE_PATTERN)]
ParamName = Annotated[str, StringConstraints(max_length=MAX_PARAM_NAME_LENGTH)]
ParamValue = Annotated[str, StringConstraints(max_length=MAX_PARAM_VALUE_LENGTH)]


def organization_id_of(state: PopupState) -> int:
    """Return the organization id a popup state was made for: the number before the dot."""
    return int(state.partition(".")[0])


class RelayedResult(BaseModel):
    """What the popup posts: the provider's `state` and the parameters it redirected with."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    state: PopupState
    params: Annotated[dict[ParamName, ParamValue], Field(max_length=MAX_PARAMS)]


def is_popup_state(value: str) -> bool:
    """Whether `value` has the form of a popup state, so a lookup for it can find anything."""
    return re.fullmatch(POPUP_STATE_PATTERN, value) is not None


class PopupRelayStore:
    """Results posted by popups, each readable once by the person and organization that posted it."""

    def __init__(self, database: WeatherDatabase):
        self._database = database

    async def put(self, org_id: int, user_id: int, state: str, params: dict[str, str]) -> None:
        """Keep `params` for five minutes, replacing what this person posted for `state`."""
        async with self._database.transaction(org_id) as connection:
            await connection.execute(
                "INSERT INTO weather.popup_results (org_id, user_id, state, params, expires_at)"
                " VALUES (%s, %s, %s, %s, now() + make_interval(secs => %s))"
                " ON CONFLICT (org_id, user_id, state)"
                " DO UPDATE SET params = EXCLUDED.params, expires_at = EXCLUDED.expires_at",
                (org_id, user_id, state, Jsonb(params), RESULT_LIFETIME_SECONDS),
            )

    async def take(self, org_id: int, user_id: int, state: str) -> dict[str, Any] | None:
        """Return and forget what this person posted for `state` in this organization, if any.

        An expired result is not returned; it stays for the purge.
        """
        async with self._database.transaction(org_id) as connection:
            cursor = await connection.execute(
                "DELETE FROM weather.popup_results"
                " WHERE user_id = %s AND state = %s AND expires_at > now()"
                " RETURNING params",
                (user_id, state),
            )
            row = await cursor.fetchone()
        return None if row is None else row["params"]
