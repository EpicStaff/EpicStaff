"""The one HTTP client every producer uses to hand code to the sandbox.

Submission is HTTP (`POST /executions`, answered 202); the result itself arrives on the
producer's own Redis channel, which this client never touches. What it adds is the
guarantee that a producer never waits forever: a full sandbox is retried for a bounded
budget, and a pending result is checked against the sandbox every
`STATUS_POLL_INTERVAL_SECONDS` so an execution the sandbox lost is reported, not awaited.
"""

import asyncio
import math
import random
from asyncio import sleep
from collections.abc import Awaitable, Callable
from time import monotonic
from urllib.parse import quote

import httpx

from foundation.clients.sandbox.errors import (
    SandboxError,
    SandboxExecutionLostError,
    SandboxOverloadedError,
    SandboxResultTimeoutError,
    SandboxUnreachableError,
)
from foundation.clients.sandbox.schemas import ExecutionRequest
from foundation.transport.http.client import AsyncClient
from foundation.transport.http.errors import (
    ClientBadGatewayError,
    ClientConnectionError,
    ClientError,
    ClientGatewayTimeoutError,
    ClientHTTPStatusError,
    ClientNotFoundError,
    ClientTimeoutError,
    ClientUnavailableError,
)

__all__ = [
    "BACKOFF_BASE_SECONDS",
    "BACKOFF_CAP_SECONDS",
    "MAX_STATUS_FAILURES",
    "STATUS_POLL_INTERVAL_SECONDS",
    "SandboxClient",
]

# How long a pending result may stay silent before the sandbox is asked whether it still has it.
STATUS_POLL_INTERVAL_SECONDS = 30.0
# Consecutive failed status checks after which the sandbox counts as unreachable.
MAX_STATUS_FAILURES = 3
# First upper bound of the jittered wait between submit retries; doubles every retry.
BACKOFF_BASE_SECONDS = 0.5
# The jittered wait between submit retries never draws from a wider range than this.
BACKOFF_CAP_SECONDS = 10.0

# Beyond this exponent the bound is far past the cap; stops `2**attempt` overflowing a float.
_MAX_BACKOFF_EXPONENT = 32

# No answer, so the sandbox may or may not have accepted the request.
_UNANSWERED_ERRORS = (
    ClientTimeoutError,
    ClientConnectionError,
    ClientBadGatewayError,
    ClientGatewayTimeoutError,
)


class SandboxClient(AsyncClient):
    """Submit executions to the sandbox and watch over the ones awaiting a result.

    Built like any httpx client (`base_url`, `timeout`, ...); `queue_timeout` is the
    total time `submit` keeps retrying a sandbox that is full or unreachable. Zero
    makes a single attempt.

    Raises:
        ValueError: `queue_timeout` is None, negative or not a number.
    """

    def __init__(self, *, queue_timeout: float, **httpx_options) -> None:
        # `not >= 0` rather than `< 0`, so NaN is refused too: it would never expire.
        if queue_timeout is None or not queue_timeout >= 0:
            raise ValueError(f"queue_timeout must be zero or more seconds, got {queue_timeout!r}")
        super().__init__(**httpx_options)
        self.queue_timeout = queue_timeout

    async def submit(
        self,
        request: ExecutionRequest,
        *,
        on_rejected: Callable[[int, float], None] | None = None,
    ) -> None:
        """Hand an execution to the sandbox, retrying while it is full or unreachable.

        Every retry re-posts the same `execution_id`, which the sandbox treats as the
        same execution, so a retry after a lost 202 never runs the code twice. Retries
        stop `queue_timeout` seconds after the first attempt; the attempt in flight at
        that moment may still finish, so the call can outlast the budget by one request
        timeout. When that last attempt went unanswered, the sandbox is asked once whether
        it has the execution after all before the submission counts as failed.

        Args:
            on_rejected: Called each time the sandbox answered 503 and a retry is
                scheduled -- never when the budget is spent -- with the retry's number,
                counting every retry from 1, and the seconds it waits first.

        Raises:
            SandboxOverloadedError: The sandbox was still full when the budget ran out.
            SandboxUnreachableError: The sandbox could not be reached within the budget.
            SandboxError: The sandbox refused the execution; the message is its error body.
        """
        payload = request.model_dump(mode="json")
        deadline = monotonic() + self.queue_timeout
        attempt = 0
        earlier_attempt_unanswered = False
        while True:
            try:
                await self.post("/executions", json=payload)
                return
            except ClientUnavailableError as error:
                # An unanswered attempt may have been accepted just before the sandbox
                # filled up; re-posting would then wait on a 503 for nothing.
                if earlier_attempt_unanswered and await self._is_known(request.execution_id):
                    return
                failure: SandboxError = SandboxOverloadedError(self.queue_timeout)
                requested_wait = _retry_after_seconds(error.response)
            except _UNANSWERED_ERRORS:
                earlier_attempt_unanswered = True
                failure = SandboxUnreachableError()
                requested_wait = 0.0
            except ClientHTTPStatusError as error:
                raise SandboxError(error.response.text) from error

            remaining = deadline - monotonic()
            if remaining <= 0:
                # The last attempt went unanswered, so it may have been accepted after all.
                if isinstance(failure, SandboxUnreachableError) and await self._is_known(
                    request.execution_id
                ):
                    return
                raise failure
            delay = min(max(requested_wait, _backoff_seconds(attempt)), remaining)
            attempt += 1
            if on_rejected is not None and isinstance(failure, SandboxOverloadedError):
                on_rejected(attempt, delay)
            await sleep(delay)

    async def status(self, execution_id: str) -> str:
        """Return the sandbox's status for an execution it still knows.

        Raises:
            SandboxExecutionLostError: The sandbox does not know the execution: it was
                lost on a restart, or its result was published long enough ago to be
                forgotten.
        """
        try:
            response = await self.get(f"/executions/{quote(execution_id, safe='')}")
        except ClientNotFoundError:
            raise SandboxExecutionLostError() from None
        return response.json()["status"]

    async def wait_for_result[T](
        self, execution_id: str, result: Awaitable[T], *, backstop: float | None
    ) -> T:
        """Await `result`, checking every so often that the sandbox still has the execution.

        The first status check happens only after `STATUS_POLL_INTERVAL_SECONDS` without a
        result, so a fast execution costs no extra request. `result` is wrapped in a task
        that is cancelled if this method leaves before it finishes.

        Args:
            result: Completes with the execution's result, typically when the producer's
                Redis listener receives it. Whatever it raises propagates unchanged.
            backstop: Seconds to wait in total before giving up; None waits as long as
                the sandbox keeps reporting the execution.

        Raises:
            SandboxExecutionLostError: The sandbox no longer knows the execution and no
                result arrived.
            SandboxUnreachableError: `MAX_STATUS_FAILURES` status checks in a row failed.
            SandboxResultTimeoutError: `backstop` seconds passed without a result.
        """
        result_task = asyncio.ensure_future(result)
        timeout = asyncio.timeout(backstop)
        try:
            async with timeout:
                return await self._watch(execution_id, result_task)
        except TimeoutError:
            # The result itself may raise TimeoutError; only an expired backstop is ours.
            if timeout.expired():
                raise SandboxResultTimeoutError(backstop) from None
            raise
        finally:
            result_task.cancel()

    async def _watch[T](self, execution_id: str, result_task: asyncio.Future[T]) -> T:
        consecutive_failures = 0
        while True:
            done, _ = await asyncio.wait({result_task}, timeout=STATUS_POLL_INTERVAL_SECONDS)
            if done:
                return result_task.result()
            try:
                await self.status(execution_id)
            except SandboxExecutionLostError:
                # The result and the 404 can arrive together; the result wins.
                if result_task.done():
                    return result_task.result()
                raise
            except (ClientTimeoutError, ClientConnectionError):
                consecutive_failures += 1
            except ClientHTTPStatusError as error:
                if error.response.status_code < 500:
                    raise
                consecutive_failures += 1
            else:
                consecutive_failures = 0
            if consecutive_failures >= MAX_STATUS_FAILURES:
                raise SandboxUnreachableError()

    async def _is_known(self, execution_id: str) -> bool:
        try:
            await self.status(execution_id)
        except ClientError:
            return False
        return True


def _retry_after_seconds(response: httpx.Response) -> float:
    """Return the `Retry-After` delay in seconds, or 0 when it is absent or not a number.

    Only the delay-seconds form is read: the sandbox never sends an HTTP date.
    """
    try:
        seconds = float(response.headers.get("Retry-After", ""))
    except ValueError:
        return 0.0
    return seconds if math.isfinite(seconds) and seconds > 0 else 0.0


def _backoff_seconds(attempt: int) -> float:
    """Exponential backoff with full jitter."""
    exponent = min(attempt, _MAX_BACKOFF_EXPONENT)
    return random.uniform(0, min(BACKOFF_CAP_SECONDS, BACKOFF_BASE_SECONDS * 2**exponent))
