"""The order a library's versions are listed in.

Input to output, no doubles. What matters is that a version is placed by what it means
and not by how it is spelled, and that one still being decided is not buried under the
versions that came before it.
"""

from manager.domain.enums import WheelStatus
from manager.domain.models import Wheel
from manager.domain.services import order_by_version


def make_wheel(id: int, version: str | None, status: WheelStatus = WheelStatus.COMPLETED) -> Wheel:
    """A wheel of `acme-core`. A version is only ever set on a completed one."""
    return Wheel(
        id=id,
        library_id=1,
        source_filename="acme-core.tar.gz",
        wheel_filename=f"acme_core-{version}-py3-none-any.whl" if version else None,
        upload_sha256=str(id).ljust(64, "0"),
        version=version,
        status=status,
    )


def versions(wheels: list[Wheel]) -> list[str | None]:
    return [wheel.version for wheel in wheels]


def test_the_newest_version_comes_first():
    ordered = order_by_version([make_wheel(1, "1.0.0"), make_wheel(2, "2.1.0"), make_wheel(3, "1.4.2")])

    assert versions(ordered) == ["2.1.0", "1.4.2", "1.0.0"]


def test_a_version_is_placed_by_what_it_means_and_not_by_its_spelling():
    ordered = order_by_version([make_wheel(1, "1.9.0"), make_wheel(2, "1.10.0")])

    assert versions(ordered) == ["1.10.0", "1.9.0"]


def test_a_prerelease_sits_below_the_release_it_leads_to():
    ordered = order_by_version([make_wheel(1, "2.0.0"), make_wheel(2, "2.0.0rc1")])

    assert versions(ordered) == ["2.0.0", "2.0.0rc1"]


def test_a_version_still_being_decided_is_listed_above_every_number():
    building = make_wheel(3, None, WheelStatus.PROCESSING)

    ordered = order_by_version([make_wheel(1, "1.0.0"), building, make_wheel(2, "2.0.0")])

    assert versions(ordered) == [None, "2.0.0", "1.0.0"]


def test_the_newest_upload_comes_first_among_those_without_a_version():
    ordered = order_by_version(
        [
            make_wheel(1, None, WheelStatus.FAILED),
            make_wheel(2, None, WheelStatus.PROCESSING),
        ]
    )

    assert [wheel.id for wheel in ordered] == [2, 1]


def test_a_version_that_is_not_pep_440_is_listed_with_the_undecided_ones():
    ordered = order_by_version([make_wheel(1, "1.0.0"), make_wheel(2, "not-a-version")])

    assert versions(ordered) == ["not-a-version", "1.0.0"]


def test_the_list_passed_in_is_left_as_it_was():
    wheels = [make_wheel(1, "1.0.0"), make_wheel(2, "2.0.0")]

    order_by_version(wheels)

    assert versions(wheels) == ["1.0.0", "2.0.0"]
