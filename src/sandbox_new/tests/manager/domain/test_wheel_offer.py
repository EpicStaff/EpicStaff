"""The rule that decides what a venv build can do with one custom library.

Input to output, no doubles: the caller has already read the library's wheels, and this
says whether the build may go ahead, has to wait, or has to fail. Every row of the
behaviour agreed for this feature has a case here.
"""

import pytest

from manager.domain.enums import WheelOffer, WheelStatus
from manager.domain.models import Wheel
from manager.domain.services import offer_wheels


def make_wheel(version: str | None, status: WheelStatus) -> Wheel:
    """A wheel of `acme-core`. A version is only ever set on a completed one."""
    return Wheel(
        library_id=1,
        source_filename="acme-core.tar.gz",
        wheel_filename=f"acme_core-{version}-py3-none-any.whl" if version else None,
        upload_sha256=(version or "none").ljust(64, "0"),
        version=version,
        status=status,
    )


def test_a_built_version_inside_the_specification_lets_the_build_go_ahead():
    offer = offer_wheels([make_wheel("1.4.2", WheelStatus.COMPLETED)], specification=">=1.4")

    assert offer.outcome is WheelOffer.READY
    assert [wheel.version for wheel in offer.wheels] == ["1.4.2"]


def test_every_built_version_is_offered_so_the_resolver_can_choose():
    """Applying the specification is the resolver's job, and it is not done twice.
    Narrowing here as well would put the same rule in two places, where they can drift;
    the wheelhouse is what the library has, and uv decides what of it to install."""
    wheels = [
        make_wheel("1.0.0", WheelStatus.COMPLETED),
        make_wheel("2.0.0", WheelStatus.COMPLETED),
    ]

    offer = offer_wheels(wheels, specification=">=1")

    assert {wheel.version for wheel in offer.wheels} == {"1.0.0", "2.0.0"}


def test_an_empty_specification_is_satisfied_by_any_built_version():
    offer = offer_wheels([make_wheel("1.0.0", WheelStatus.COMPLETED)], specification="")

    assert offer.outcome is WheelOffer.READY


def test_a_matching_built_version_wins_over_one_that_is_still_building():
    """The build does not wait for something it does not need."""
    wheels = [
        make_wheel("1.4.2", WheelStatus.COMPLETED),
        make_wheel(None, WheelStatus.PROCESSING),
    ]

    assert offer_wheels(wheels, specification=">=1.4").outcome is WheelOffer.READY


@pytest.mark.parametrize("status", [WheelStatus.DECLARED, WheelStatus.PROCESSING])
def test_a_version_on_its_way_makes_the_build_wait(status):
    """Not a failure: this service is producing it, and the next tick tries again."""
    assert offer_wheels([make_wheel(None, status)], specification="").outcome is WheelOffer.WAIT


def test_a_newer_version_still_building_makes_the_build_wait():
    """The built 1.0.0 cannot satisfy `>=2`, so the build waits for the one that can
    rather than failing on a version that is minutes away."""
    wheels = [
        make_wheel("1.0.0", WheelStatus.COMPLETED),
        make_wheel(None, WheelStatus.PROCESSING),
    ]

    assert offer_wheels(wheels, specification=">=2").outcome is WheelOffer.WAIT


def test_a_library_with_nothing_built_and_nothing_building_fails_the_build():
    assert offer_wheels([], specification="").outcome is WheelOffer.NOTHING_BUILT


def test_a_library_whose_only_version_failed_to_build_fails_the_build():
    """Nothing is coming: a failed wheel is not retried, so waiting would never end."""
    assert (
        offer_wheels([make_wheel(None, WheelStatus.FAILED)], specification="").outcome
        is WheelOffer.NOTHING_BUILT
    )


def test_built_versions_that_match_nothing_are_left_for_the_resolver_to_refuse():
    """The same answer an ordinary library gets. Our own message is reserved for what
    only this service knows, and "no version matches" is not that."""
    offer = offer_wheels([make_wheel("1.0.0", WheelStatus.COMPLETED)], specification=">=3")

    assert offer.outcome is WheelOffer.READY
    assert [wheel.version for wheel in offer.wheels] == ["1.0.0"]


def test_a_completed_wheel_with_no_version_is_not_offered():
    """A completed wheel always has a version. One without is a broken row, and
    handing it over would put a wheel in the wheelhouse nothing can resolve to."""
    offer = offer_wheels([make_wheel(None, WheelStatus.COMPLETED)], specification="")

    assert offer.outcome is WheelOffer.NOTHING_BUILT
    assert offer.wheels == []


def test_a_prerelease_is_offered_when_the_specification_asks_for_one():
    """uv is given `--generate-hashes` and a plain specification; a version a user
    uploaded as a prerelease is still a version of theirs."""
    offer = offer_wheels([make_wheel("2.0.0rc1", WheelStatus.COMPLETED)], specification=">=1")

    assert offer.outcome is WheelOffer.READY
