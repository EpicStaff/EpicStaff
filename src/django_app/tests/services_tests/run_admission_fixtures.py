"""Run admission with checks a test controls, so seam tests never depend on a real check.

Star-import into a test module and request `run_admission_checks` (an empty list the test
fills) or `refusing_check` (one check that refuses every run).
"""

from collections.abc import Callable

import pytest

from tables.services import run_admission
from tables.services.run_admission import RunAdmissionRefusedError, RunSubject

REFUSAL_MESSAGE = "This run is refused by the test."
REFUSAL_EXTRA = {"refused_by": {"name": "test check"}}


class RefusedForTestError(RunAdmissionRefusedError):
    default_code = "test_refused"
    default_detail = REFUSAL_MESSAGE

    def __init__(self, log_key: str):
        super().__init__()
        self.log_key = log_key
        self.extra_response_data = REFUSAL_EXTRA


class RecordingCheck:
    """Admits every run and remembers each subject it was asked about, first or again."""

    def __init__(self):
        self.subjects: list[RunSubject] = []

    def check(self, subject: RunSubject) -> None:
        self.subjects.append(subject)

    def recheck(self, subject: RunSubject, first_look: object) -> None:
        self.check(subject)


class RefusingCheck(RecordingCheck):
    """Refuses every run `refuses` picks (all of them by default), for the cause `log_key`."""

    def __init__(
        self,
        refuses: Callable[[RunSubject], bool] = lambda subject: True,
        log_key: str = "test-cause",
    ):
        super().__init__()
        self.refuses = refuses
        self.log_key = log_key

    def check(self, subject: RunSubject) -> None:
        super().check(subject)
        if self.refuses(subject):
            raise RefusedForTestError(self.log_key)


@pytest.fixture
def run_admission_checks(monkeypatch):
    """Replace the registered checks with an empty list the test fills."""
    checks: list = []
    monkeypatch.setattr(run_admission, "_registered_checks", checks)
    yield checks


@pytest.fixture
def refusing_check(run_admission_checks):
    """The only registered check, refusing every run."""
    check = RefusingCheck()
    run_admission_checks.append(check)
    yield check
