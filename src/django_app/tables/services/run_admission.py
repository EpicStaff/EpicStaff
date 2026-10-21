"""Run admission: the checks every run passes before it starts.

Every path that starts work on an organization's flows, agents, voice channels or stored
code calls `assert_run_admitted` before it writes or publishes anything: no session row, no
result row, no Redis message. Interactive callers let the refusal propagate, so the caller
gets a 409 envelope; triggers have no caller to tell and log it with
`log_trigger_refusal_once`.

Other apps add reasons to refuse a run without `tables` importing them: implement
`RunAdmissionCheck`, raise a subclass of `RunAdmissionRefusedError`, and register the check
in the app's `ready()`.

Adding a run entry point: call `assert_run_admitted` before anything is written. Add a
`RunKind` only when the run starts from a new kind of row, together with its start model in
`run_resources.RUN_START_MODELS`.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from django.core.cache import cache
from utils.exceptions import CustomAPIExeption
from utils.logger import logger

REFUSAL_LOG_SECONDS = 24 * 60 * 60


class RunKind(StrEnum):
    """The kind of row a run starts from; `RunSubject.subject_id` is that row's id."""

    FLOW = "flow"  # a Graph
    REALTIME = "realtime"  # an AgentDefinition
    VOICE_CHANNEL = "voice_channel"  # a RealtimeChannel
    CODE = "code"  # a PythonCode


@dataclass(frozen=True)
class RunSubject:
    """What a run is about to start, in the organization it runs in."""

    kind: RunKind
    subject_id: int
    organization_id: int


class RunAdmissionRefusedError(CustomAPIExeption):
    """A run was refused before it started.

    Never raised directly: each check raises its own subclass with its own code and message.

    Attributes:
        log_key: Stable text naming the cause of the refusal. Equal for the same cause, so a
            trigger refused for the same reason logs once; a new cause logs again.
    """

    status_code = 409
    default_code = "run_refused"
    default_detail = "This run cannot start."
    log_key: str = ""


class RunAdmissionCheck(Protocol):
    """One reason to refuse a run."""

    def check(self, subject: RunSubject) -> None:
        """Return when the run may start; raise a `RunAdmissionRefusedError` subclass otherwise."""
        ...


_registered_checks: list[RunAdmissionCheck] = []


def register_run_admission_check(check: RunAdmissionCheck) -> None:
    """Add `check` to every run's admission.

    Idempotent per check class, because an app's `ready()` may run more than once: a second
    check of an already registered class is ignored. Checks run in registration order.
    """
    if any(type(registered) is type(check) for registered in _registered_checks):
        return
    _registered_checks.append(check)


def registered_run_admission_checks() -> tuple[RunAdmissionCheck, ...]:
    """Return the registered checks, in the order they run."""
    return tuple(_registered_checks)


def assert_run_admitted(subject: RunSubject) -> None:
    """Run every registered check against `subject`.

    Call it before the run writes or publishes anything.

    Raises:
        RunAdmissionRefusedError: The first check that refuses the run; the checks after it
            do not run.
    """
    for check in _registered_checks:
        check.check(subject)


def log_trigger_refusal_once(
    *, trigger: str, node_id: int, graph_id: int, error: RunAdmissionRefusedError
) -> None:
    """Log a refused trigger run at most once per node and cause in `REFUSAL_LOG_SECONDS`.

    The marker lives in Django's shared cache, so the limit holds across workers. A trigger
    that keeps firing while refused logs again only for a different cause or after the
    period.
    """
    marker = f"run_admission:refusal_logged:{trigger}:{node_id}:{error.log_key}"
    if not cache.add(marker, True, REFUSAL_LOG_SECONDS):
        return
    logger.warning(
        "Run refused: {} trigger node {} of flow {}: {} ({})",
        trigger,
        node_id,
        graph_id,
        str(error.detail),
        error.default_code,
    )
