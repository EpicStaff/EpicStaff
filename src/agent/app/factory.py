"""
Layer 5 — RunnerFactory: maps ``RunType`` to a ``(Runner, Emitter)`` pair.

This is one of the two orthogonal axes in the architecture: the factory
selects *how* the work is orchestrated (Runner) while also wiring the
output transport (Emitter) that matches the runner's declared
``emitter_mode``.  The pairing here is the seam where a future per-request
streaming override can slot in without touching Runner or Emitter code.

``RunnerDependencies`` (resolver + loop) is injected at factory construction
time and forwarded to every runner instance so runners have direct access to
their collaborators.
"""

from __future__ import annotations

from app.emitters.base import Emitter
from app.emitters.redis_batch import RedisStreamBatchEmitter
from app.emitters.redis_tool_events import RedisStreamToolEventEmitter
from app.enums import EmitterMode, RunType
from app.exceptions import UnknownRunTypeError
from app.runners.base import Runner
from app.runners.deps import RunnerDependencies
from shared.models.agent_service import AgentRequest
from shared.redis_streams import RedisStreamClient


class RunnerFactory:
    """Registry that pairs ``RunType`` values with ``Runner`` subclasses.

    ``main.py`` constructs one factory with shared ``RunnerDependencies``,
    calls ``register`` for each known runner class, then passes the factory
    to ``RequestHandler``.  At request time ``build`` is called with the
    fully-hydrated ``AgentRequest``.

    Invariant: a ``RunType`` must be registered before any request carrying
    that type arrives; unregistered types raise ``UnknownRunTypeError`` which
    is caught by ``RequestHandler`` and routed to ``emitter.on_error``.
    """

    def __init__(self, deps: RunnerDependencies) -> None:
        self._deps = deps
        self._registry: dict[RunType, type[Runner]] = {}

    def register(self, run_type: RunType, runner_cls: type[Runner]) -> None:
        """Register a ``Runner`` subclass for the given ``run_type``.

        Calling ``register`` a second time for the same ``run_type``
        silently replaces the previous entry.
        """
        self._registry[run_type] = runner_cls

    def build(
        self,
        request: AgentRequest,
        redis_client: RedisStreamClient,
        result_stream: str,
    ) -> tuple[Runner, Emitter]:
        """Build a ``Runner`` and its matching ``Emitter`` for ``request``.

        Looks up the runner class by ``request.run_type``, instantiates it
        with the shared deps, then delegates to ``_build_emitter`` using the
        runner's declared ``emitter_mode``.

        Raises:
            UnknownRunTypeError: if no runner is registered for
                ``request.run_type``.
        """
        runner_cls = self._registry.get(request.run_type)

        if runner_cls is None:
            raise UnknownRunTypeError(
                f"No runner registered for run_type '{request.run_type}'"
            )

        runner = runner_cls(self._deps)
        emitter = self._build_emitter(
            runner_cls.emitter_mode, redis_client, result_stream, request.correlation_id
        )
        return runner, emitter

    def _build_emitter(
        self,
        mode: EmitterMode,
        redis_client: RedisStreamClient,
        result_stream: str,
        correlation_id: str,
    ) -> Emitter:
        if mode == EmitterMode.BATCH:
            return RedisStreamBatchEmitter(redis_client, result_stream, correlation_id)

        if mode == EmitterMode.TOOL_EVENTS:
            return RedisStreamToolEventEmitter(
                redis_client, result_stream, correlation_id
            )

        raise NotImplementedError(f"Emitter mode '{mode}' is not yet implemented")
