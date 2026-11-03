"""What a custom library can give a venv build, decided without touching anything.

A venv names a custom library the way it names any package, with a version
specification. The library's versions are its built wheels, so whether a build can go
ahead is answered here rather than by the resolver: the resolver cannot tell a version
that does not exist from one this service has not finished building yet.
"""

from foundation.base import ValueObject
from packaging.specifiers import SpecifierSet

from manager.domain.enums import WheelOffer, WheelStatus
from manager.domain.models import Wheel

__all__ = ["WheelsOnOffer", "offer_wheels"]

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
