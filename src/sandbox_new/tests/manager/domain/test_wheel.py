"""Behavior of the wheel model: what a version stands for, where its files live, and
how it moves between states.

The keys are the load-bearing part. They are what the reaper deletes and what a
download reads, so their shape is a stored fact rather than an implementation detail --
change it and every file already in the object store becomes unreachable.
"""

import pytest
from pydantic import ValidationError

from manager.domain.enums import WheelStatus
from manager.domain.models import Wheel

SHA256 = "a" * 64


def make_wheel(**overrides) -> Wheel:
    fields = {
        "id": 2,
        "library_id": 1,
        "source_filename": "my-library-1.0.0.tar.gz",
        "upload_sha256": SHA256,
    }
    return Wheel(**(fields | overrides))


def test_a_wheel_must_stand_for_a_file():
    """A row exists because something was uploaded; one naming no file describes nothing."""
    with pytest.raises(ValidationError):
        Wheel(id=2, library_id=1, upload_sha256=SHA256)


@pytest.mark.parametrize(
    ("source_filename", "wheel_filename"),
    [
        ("my-library-1.0.0.tar.gz", None),
        (None, "my_library-1.0.0-py3-none-any.whl"),
        ("my-library-1.0.0.tar.gz", "my_library-1.0.0-py3-none-any.whl"),
    ],
    ids=["archive to build", "wheel uploaded ready", "archive already built"],
)
def test_a_wheel_may_name_a_source_a_built_file_or_both(source_filename, wheel_filename):
    wheel = make_wheel(source_filename=source_filename, wheel_filename=wheel_filename)

    assert (wheel.source_filename, wheel.wheel_filename) == (source_filename, wheel_filename)


def test_each_file_is_stored_under_a_key_built_from_the_two_ids():
    wheel = make_wheel(wheel_filename="my_library-1.0.0-py3-none-any.whl")

    assert wheel.source_key == "1/2/source/my-library-1.0.0.tar.gz"
    assert wheel.wheel_key == "1/2/wheel/my_library-1.0.0-py3-none-any.whl"


@pytest.mark.parametrize(
    ("sent", "kept"),
    [
        ("../../etc/passwd", "passwd"),
        ("/etc/passwd", "passwd"),
        ("nested/dir/my-library-1.0.0.tar.gz", "my-library-1.0.0.tar.gz"),
    ],
    ids=["traversal", "absolute", "nested"],
)
def test_a_key_keeps_only_the_last_part_of_the_name_a_client_sent(sent, kept):
    """A key is a path. The name reaches the model straight from an upload, so a name
    carrying directories of its own would otherwise address another library's files."""
    assert make_wheel(source_filename=sent).source_key == f"1/2/source/{kept}"


def test_a_key_is_absent_for_as_long_as_its_file_is():
    """An archive has no wheel until a build makes one, and the reaper reads both keys."""
    wheel = make_wheel(wheel_filename=None)

    assert wheel.wheel_key is None
    assert wheel.source_key is not None


def test_completing_records_the_built_file_and_drops_an_earlier_failure():
    wheel = make_wheel()
    wheel.mark_as_failed(RuntimeError("the first attempt blew up"))

    wheel.mark_as_completed("1.0.0", "my_library-1.0.0-py3-none-any.whl")

    assert wheel.status is WheelStatus.COMPLETED
    assert wheel.version == "1.0.0"
    assert wheel.wheel_filename == "my_library-1.0.0-py3-none-any.whl"
    assert wheel.error is None


def test_failing_records_the_reason_in_words():
    """The reason is what a client is told; it is read off the row, not the exception."""
    wheel = make_wheel()

    wheel.mark_as_failed(RuntimeError("Could not build a wheel from this source."))

    assert wheel.status is WheelStatus.FAILED
    assert wheel.error == "Could not build a wheel from this source."


@pytest.mark.parametrize(
    ("transition", "status"),
    [
        ("mark_as_declared", WheelStatus.DECLARED),
        ("mark_as_processing", WheelStatus.PROCESSING),
    ],
)
def test_taking_a_wheel_back_to_work_drops_the_reason_it_failed_before(transition, status):
    """Otherwise a version being built again would still report why the last try failed."""
    wheel = make_wheel()
    wheel.mark_as_failed(RuntimeError("the first attempt blew up"))

    getattr(wheel, transition)()

    assert wheel.status is status
    assert wheel.error is None
