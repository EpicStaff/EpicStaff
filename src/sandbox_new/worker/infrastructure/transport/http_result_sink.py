"""Network result sink: posts a finished execution back to the manager.

Every ``send`` ends in exactly one of three outcomes: the result is delivered, a small
fixed replacement failure is delivered in its place, or the process is taken down. The
last one is not a silent loss -- the restart surfaces as a new boot id and the manager
fails the stranded jobs fast -- and it is what keeps "every job ends in a result"
honest when the manager stays unreachable.

How an error is handled depends on what it says:
- 401/403: the token was rotated or wrong; retrying hides it, so the process goes down.
- another 4xx: the manager refused this body, so re-sending the same bytes cannot help;
  the producer still needs an outcome, so a fixed failure is sent in the result's place.
- 5xx and transport errors: retried on a time budget, then the process goes down. The
  budget outlasts the manager's 60 s silence threshold on purpose: a stop kills every
  running execution, so it must never fire on a stall the liveness model itself
  tolerates -- and past the budget the manager has already failed this run's jobs, so
  stopping loses nothing more.
"""

import asyncio
import time
from collections.abc import Callable

from common.contracts import ExecutionResultMessage
from common.runner import terminate_process
from foundation.transport.http import AsyncClient
from foundation.transport.http.errors import (
    ClientError,
    ClientForbiddenError,
    ClientHTTPStatusError,
    ClientUnauthorizedError,
)
from loguru import logger

from worker.application.ports.result_sink import AbstractResultSink
from worker.domain.models import ExecutionResult, StorageMutations
from worker.infrastructure.transport.codec import encode_result

__all__ = ["HttpResultSink"]

_UNDELIVERABLE_MESSAGE = "Sandbox could not deliver the execution result."

# Longer than the manager's HEARTBEAT_SILENCE_SECONDS (60 s): by the time this runs
# out, the manager has declared this run lost and failed its jobs anyway.
_RETRY_BUDGET_SECONDS = 90.0
_MAX_RETRY_DELAY_SECONDS = 10.0


class HttpResultSink(AbstractResultSink):
    def __init__(
        self,
        client: AsyncClient,
        *,
        retry_budget: float = _RETRY_BUDGET_SECONDS,
        retry_delay: float = 2.0,
        stop: Callable[[], None] = terminate_process,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._client = client
        self._retry_budget = retry_budget
        self._retry_delay = retry_delay
        self._stop = stop
        self._clock = clock

    async def send(
        self, result: ExecutionResult, mutations: StorageMutations | None = None
    ) -> None:
        message = encode_result(result, mutations)
        error = await self._post(message.model_dump_json())
        if error is None:
            return
        if isinstance(error, (ClientUnauthorizedError, ClientForbiddenError)):
            logger.critical(
                "The manager refused the worker's token ({}); restarting so the failure is visible",
                type(error).__name__,
            )
            self._stop()
            return
        if isinstance(error, ClientHTTPStatusError) and error.response.status_code < 500:
            logger.critical(
                "Result for execution {} was refused by the manager ({}); "
                "sending a fixed failure in its place",
                result.execution_id,
                type(error).__name__,
            )
            replacement = ExecutionResultMessage(
                execution_id=result.execution_id,
                stderr=_UNDELIVERABLE_MESSAGE,
                returncode=1,
                ran=True,
                session_id=result.session_id,
                reply_to_crew_channel=result.reply_to_crew_channel,
            )
            if await self._post(replacement.model_dump_json()) is None:
                return
        logger.critical(
            "Result for execution {} could not be delivered; restarting so the "
            "manager fails the job fast",
            result.execution_id,
        )
        self._stop()

    async def _post(self, body: str) -> ClientError | None:
        """Deliver one body, retrying what retrying can fix; the caller judges the rest."""
        deadline = self._clock() + self._retry_budget
        attempt = 0
        while True:
            attempt += 1
            try:
                await self._client.request(
                    "POST",
                    "/worker/results",
                    content=body,
                    headers={"Content-Type": "application/json"},
                )
                return None
            except (ClientUnauthorizedError, ClientForbiddenError) as error:
                return error
            except ClientHTTPStatusError as error:
                if error.response.status_code < 500:
                    return error
                last_error: ClientError = error
            except ClientError as error:
                last_error = error
            if self._clock() >= deadline:
                return last_error
            logger.warning("Result delivery failed ({}); retrying", type(last_error).__name__)
            await asyncio.sleep(min(self._retry_delay * attempt, _MAX_RETRY_DELAY_SECONDS))
