from functools import cache
from typing import Annotated
from zoneinfo import available_timezones

from pydantic import AfterValidator

# Zone names the IANA database keeps only as aliases, mapped to the current name.
_RENAMED_TIME_ZONES = {"Europe/Kiev": "Europe/Kyiv"}


@cache
def _known_time_zones() -> frozenset[str]:
    return frozenset(available_timezones())


def _validate_time_zone_name(name: str) -> str:
    # Membership in the IANA list, not just ZoneInfo(name), so a name the caller made up
    # never resolves to a file path. The list is the system tz database of this service's
    # pinned base image, not the tzdata package. django_app validates the display timezone
    # preference the same way on the same base image, so both accept the same names only
    # while their base images stay the same.
    name = _RENAMED_TIME_ZONES.get(name, name)
    if name not in _known_time_zones():
        raise ValueError("Unknown time zone. Use an IANA name such as Europe/Kyiv.")
    return name


TimeZoneName = Annotated[str, AfterValidator(_validate_time_zone_name)]
"""An IANA time zone name, with renamed legacy names turned into their current one."""
