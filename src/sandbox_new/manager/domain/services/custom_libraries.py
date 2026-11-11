"""What a custom library can give a venv build, decided without touching anything.

A venv names a custom library the way it names any package, with a version
specification. The library's versions are its built wheels, so whether a build can go
ahead is answered here rather than by the resolver: the resolver cannot tell a version
that does not exist from one this service has not finished building yet.

What a reader of the library list is told about those same versions is decided here
too, so that a build and a listing never disagree about what a status means.
"""

from foundation.base import ValueObject
from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version

from manager.domain.enums import WheelOffer, WheelStatus
from manager.domain.models import LibraryBuildState, Wheel

__all__ = [
    "WheelsOnOffer",
    "offer_wheels",
    "order_by_version",
    "summarize_wheels",
]

# A wheel in one of these is on its way to being usable. One in any other never will be:
# a failed build is not retried, so waiting for it would never end.
_ON_ITS_WAY = (WheelStatus.DECLARED, WheelStatus.PROCESSING)


class WheelsOnOffer(ValueObject):
    """What the build may do, and the wheels it may do it with."""

    outcome: WheelOffer
    wheels: list[Wheel] = []


def offer_wheels(wheels: list[Wheel], specification: str) -> WheelsOnOffer:
    """Decide what a venv build can do with one custom library.

    `READY` carries every built wheel, not only the matching ones: the specification is
    applied by the resolver, which needs the candidates to choose between. Built wheels
    that match nothing are handed over all the same, so that a specification nothing
    satisfies is refused in the words an ordinary library would be refused in.

    Args:
        wheels: Every wheel of the library, whatever its status.
        specification: The version specification the venv declared, possibly empty.

    Returns:
        `READY` with the built wheels, `WAIT` while one that could match is still being
        built, or `NOTHING_BUILT` when the library has no built version and none coming.
    """
    built = [wheel for wheel in wheels if wheel.status is WheelStatus.COMPLETED and wheel.version]
    specifiers = SpecifierSet(specification)

    if any(specifiers.contains(wheel.version, prereleases=True) for wheel in built):
        return WheelsOnOffer(outcome=WheelOffer.READY, wheels=built)

    if any(wheel.status in _ON_ITS_WAY for wheel in wheels):
        return WheelsOnOffer(outcome=WheelOffer.WAIT)

    if not built:
        return WheelsOnOffer(outcome=WheelOffer.NOTHING_BUILT)

    return WheelsOnOffer(outcome=WheelOffer.READY, wheels=built)


def summarize_wheels(wheels: list[Wheel]) -> LibraryBuildState:
    """Say in one status what a reader has to know about a library's versions.

    A failure is reported ahead of a build still running: a failed build is never
    retried, so it stays until someone removes that version, while a running one
    answers itself in a moment.

    Args:
        wheels: Every version of the library, whatever its status.

    Returns:
        The status that stands for the library, carrying the failed version's error
        when there is one, or no status at all when the library has no versions.
    """
    failed = next((wheel for wheel in wheels if wheel.status is WheelStatus.FAILED), None)
    if failed is not None:
        return LibraryBuildState(status=WheelStatus.FAILED, error=failed.error)

    # Building before queued: the one under way is the more precise of the two.
    for status in (WheelStatus.PROCESSING, WheelStatus.DECLARED):
        if any(wheel.status is status for wheel in wheels):
            return LibraryBuildState(status=status)

    if not wheels:
        return LibraryBuildState()
    return LibraryBuildState(status=WheelStatus.COMPLETED)


def order_by_version(wheels: list[Wheel]) -> list[Wheel]:
    """The library's versions as a reader expects them: the newest first.

    Ordered by what a version means rather than by its spelling, so `1.10` comes before
    `1.9`. A version a build has not decided yet goes above all of them: it is the
    upload that just happened, and it is what its uploader is waiting for. A version
    that is not PEP 440 is treated the same way -- there is no place to sort it into.

    Returns:
        A new list. The one passed in is left as it was.
    """
    return sorted(wheels, key=_version_sort_key, reverse=True)


def _version_sort_key(wheel: Wheel) -> tuple[int, Version, int]:
    """Undecided versions in one group, numbered ones in the other, newest id last.

    The filler version is never compared against a real one: the group ahead of it in
    the key already separates the two.
    """
    parsed = _parse_version(wheel.version)
    if parsed is None:
        return (1, Version("0"), wheel.id or 0)
    return (0, parsed, wheel.id or 0)


def _parse_version(version: str | None) -> Version | None:
    if not version:
        return None
    try:
        return Version(version)
    except InvalidVersion:
        return None
