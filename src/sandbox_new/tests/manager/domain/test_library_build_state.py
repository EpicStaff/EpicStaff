"""The rule that reduces a custom library's versions to one status.

Input to output, no doubles: the caller has already read the library's wheels, and
this says what a reader of the library list is shown about them.
"""

from manager.domain.enums import WheelStatus
from manager.domain.models import Wheel
from manager.domain.services import summarize_wheels


def make_wheel(status: WheelStatus, error: str | None = None) -> Wheel:
    """A version of `acme-core` in `status`, with no file name worth reading."""
    return Wheel(
        library_id=1,
        source_filename="acme-core.tar.gz",
        upload_sha256="0" * 64,
        status=status,
        error=error,
    )


def test_a_library_without_versions_has_no_status():
    state = summarize_wheels([])

    assert state.status is None
    assert state.error is None


def test_a_library_whose_versions_are_all_built_is_completed():
    state = summarize_wheels([make_wheel(WheelStatus.COMPLETED)])

    assert state.status is WheelStatus.COMPLETED


def test_a_failed_version_is_reported_with_its_error():
    state = summarize_wheels([make_wheel(WheelStatus.FAILED, error="no setup.py")])

    assert state.status is WheelStatus.FAILED
    assert state.error == "no setup.py"


def test_a_failure_is_reported_although_another_version_built():
    """The library works, but a version of it did not arrive, and nobody is told that
    anywhere else: the failed build is not retried and stays until it is removed."""
    state = summarize_wheels([make_wheel(WheelStatus.COMPLETED), make_wheel(WheelStatus.FAILED)])

    assert state.status is WheelStatus.FAILED


def test_a_failure_is_reported_ahead_of_a_build_still_running():
    """The running one answers itself in a moment; the failed one does not."""
    state = summarize_wheels([make_wheel(WheelStatus.PROCESSING), make_wheel(WheelStatus.FAILED)])

    assert state.status is WheelStatus.FAILED


def test_a_version_being_built_is_reported_ahead_of_one_still_queued():
    state = summarize_wheels([make_wheel(WheelStatus.DECLARED), make_wheel(WheelStatus.PROCESSING)])

    assert state.status is WheelStatus.PROCESSING


def test_a_queued_version_is_reported_when_nothing_is_building_yet():
    state = summarize_wheels([make_wheel(WheelStatus.COMPLETED), make_wheel(WheelStatus.DECLARED)])

    assert state.status is WheelStatus.DECLARED


def test_a_building_version_carries_no_error():
    state = summarize_wheels([make_wheel(WheelStatus.PROCESSING)])

    assert state.error is None
