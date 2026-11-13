"""Network job source: long-polls the manager for the next job.

The pull itself is the worker's capacity signal -- the job consumer only calls ``get``
when the run gate has a slot -- so there is nothing to negotiate: ask, and either a job
comes back (200) or nothing did (204) and we ask again. The client arrives configured
with the manager's base URL, the internal bearer token and this run's boot id in its
default headers.

A transport failure is logged by exception type only and retried after a pause: the
worker has nothing else to do without jobs, and anything already assigned is covered by
the manager's worker-loss detection. The one exception is the manager refusing the
token (401/403): retrying that forever would hide a rotated secret behind a quiet
warning loop, so it takes the process down and the restart loop makes it visible.

Unlike the queue source, wire and domain validation happen in one step here, so a
drifted job is told apart from garbage by whether the body still names an execution.
"""

import asyncio
import json
from collections.abc import Callable

from common.contracts import ExecutionJobMessage
from common.runner import terminate_process
from foundation.transport.http import AsyncClient
from foundation.transport.http.errors import (
    ClientError,
    ClientForbiddenError,
    ClientUnauthorizedError,
)
from loguru import logger
from pydantic import ValidationError

from worker.application.ports.job_source import AbstractJobSource, UndecodableJobError
from worker.domain.models import Job
from worker.infrastructure.transport.codec import decode_job

__all__ = ["HttpJobSource"]

# Above the manager's ~25 s empty long-poll, so an empty poll is a 204, not a timeout.
_POLL_TIMEOUT_SECONDS = 30.0


class HttpJobSource(AbstractJobSource):
    def __init__(
        self,
        client: AsyncClient,
        *,
        retry_delay: float = 2.0,
        stop: Callable[[], None] = terminate_process,
    ):
        self._client = client
        self._retry_delay = retry_delay
        self._stop = stop

    async def get(self) -> Job:
        while True:
            try:
                response = await self._client.request(
                    "GET", "/worker/jobs", timeout=_POLL_TIMEOUT_SECONDS
                )
            except (ClientUnauthorizedError, ClientForbiddenError) as error:
                logger.critical(
                    "The manager refused the worker's token ({}); restarting so the "
                    "failure is visible",
                    type(error).__name__,
                )
                self._stop()
                raise
            except ClientError as error:
                logger.warning("Job pull failed ({}); retrying", type(error).__name__)
                await asyncio.sleep(self._retry_delay)
                continue
            if response.status_code == 204:
                continue
            try:
                message = ExecutionJobMessage.model_validate_json(response.content)
            except ValidationError:
                # `from None` and no error text in the log: both would quote the body,
                # secrets included.
                error = _undecodable(response.content)
                if error is None:
                    logger.error("Job pull returned a body that is not a job; dropped")
                    await asyncio.sleep(self._retry_delay)
                    continue
                raise error from None
            return decode_job(message)


def _undecodable(body: bytes) -> UndecodableJobError | None:
    """The error that fails a drifted job back to its producer.

    None when the body does not even name an execution: there is nothing to fail, and
    the polling loop logs and carries on.
    """
    try:
        fields = json.loads(body)
    except ValueError:
        return None
    if not isinstance(fields, dict) or not isinstance(fields.get("execution_id"), str):
        return None
    session_id = fields.get("session_id")
    return UndecodableJobError(
        fields["execution_id"],
        reply_to_crew_channel=bool(fields.get("reply_to_crew_channel")),
        session_id=session_id if isinstance(session_id, int) else None,
    )
