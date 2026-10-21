"""Run admission: the checks every run passes before it starts.

Every path that starts work on an organization's flows, agents, voice channels or stored
code calls `assert_run_admitted` before it writes or publishes anything: no session row, no
result row, no Redis message. Interactive callers let the refusal propagate, so the caller
gets a 409 envelope; triggers have no caller to tell and log it with
`log_trigger_refusal_once`.

Other apps add reasons to refuse a run without `tables` importing them: implement
`RunAdmissionCheck`, raise a subclass of `RunAdmissionRefusedError`, and register the check
in the app's `ready()`.

A run that is built before it is handed over (a flow session) is asked again just before the
handover with `assert_still_admitted`, so a cause that appeared while it was built still
refuses it. Each check gets back what it found the first time, so the re-check is cheap.

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
    """What a run is about to start, in the organization it runs in.

    The kind and ids are converted on creation: an id given as text would otherwise match
    no row, and every check would admit the run.
    """

    kind: RunKind
    subject_id: int
    organization_id: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", RunKind(self.kind))
        object.__setattr__(self, "subject_id", int(self.subject_id))
        object.__setattr__(self, "organization_id", int(self.organization_id))


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

    def check(self, subject: RunSubject) -> object:
        """Refuse the run by raising a `RunAdmissionRefusedError` subclass.

        Returns what a re-check of the same run may reuse, or None.
        """
        ...

    def recheck(self, subject: RunSubject, first_look: object) -> None:
        """Refuse the run if it must be refused now; `first_look` is what `check` returned."""
        ...


@dataclass(frozen=True)
class RunAdmission:
    """A run admitted once, with what each check found, for `assert_still_admitted`."""

    subject: RunSubject
    first_looks: tuple[tuple[RunAdmissionCheck, object], ...]


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


def assert_run_admitted(subject: RunSubject) -> RunAdmission:
    """Run every registered check against `subject`.

    Call it before the run writes or publishes anything.

    Returns:
        What the checks found, for `assert_still_admitted` just before the run is handed over.

    Raises:
        RunAdmissionRefusedError: The first check that refuses the run; the checks after it
            do not run.
    """
    first_looks = []
    for check in _registered_checks:
        first_looks.append((check, check.check(subject)))
    return RunAdmission(subject=subject, first_looks=tuple(first_looks))


def assert_still_admitted(admission: RunAdmission) -> None:
    """Ask the checks of `admission` again, each with what it found the first time.

    Call it just before the run is handed over, to refuse a run whose cause appeared while
    the run was being built.

    Raises:
        RunAdmissionRefusedError: The first check that now refuses the run.
    """
    for check, first_look in admission.first_looks:
        check.recheck(admission.subject, first_look)


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
