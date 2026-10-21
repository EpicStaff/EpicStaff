"""The relay a popup hands its OAuth result through when the provider has severed its opener.

The framed page opens the provider in a popup, with a `state` of the form `<org id>.<random>`.
When the provider's page sends `Cross-Origin-Opener-Policy`, the popup loses `window.opener`
and cannot post the result back. It then logs itself in (in the organization `state` names),
posts the result here, and the framed page polls for it. Each result is kept for the person
and organization that posted it, so nobody else can read it or replace it.

The results live in this process's memory: enough for the sample, which runs one process, but
lost on every restart. This store is for the demo only; a real plugin keeps them in its
database.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

# Equals `patterns.popup_state` of the JS SDK's login protocol (`createPopupState`).
POPUP_STATE_PATTERN = r"^[1-9][0-9]{0,9}\.[A-Za-z0-9_-]{22,64}$"
RESULT_LIFETIME_SECONDS = 300
# Bounds the memory a burst of posted results can take; the oldest result goes first.
MAX_STORED_RESULTS = 256
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


@dataclass(frozen=True)
class _StoredResult:
    params: dict[str, str]
    expires_at: float


class PopupRelayStore:
    """Results posted by popups, each readable once by the person and organization that posted it.

    Not thread-safe: the app's routes are coroutines, which run on one event loop.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._results: dict[tuple[int, int, str], _StoredResult] = {}

    def put(self, user_id: int, org_id: int, state: str, params: dict[str, str]) -> None:
        """Keep `params` for five minutes, replacing what this person posted for `state`."""
        self._drop_expired()
        key = (user_id, org_id, state)
        self._results.pop(key, None)
        while len(self._results) >= MAX_STORED_RESULTS:
            del self._results[next(iter(self._results))]
        self._results[key] = _StoredResult(
            params=dict(params), expires_at=self._clock() + RESULT_LIFETIME_SECONDS
        )

    def take(self, user_id: int, org_id: int, state: str) -> dict[str, str] | None:
        """Return and forget what this person posted for `state` in this organization, if any."""
        self._drop_expired()
        stored = self._results.pop((user_id, org_id, state), None)
        return stored.params if stored else None

    def _drop_expired(self) -> None:
        now = self._clock()
        for key in [key for key, stored in self._results.items() if stored.expires_at <= now]:
            del self._results[key]
