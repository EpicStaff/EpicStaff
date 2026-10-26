"""How long a suspended plugin keeps its data in an organization (`PLUGINS_GRACE_PERIOD_DAYS`)."""

from datetime import timedelta

from django.conf import settings

from plugins.configuration.limits import positive_integer

MAX_GRACE_PERIOD_DAYS = 3650


def grace_period_days(value: object) -> int | None:
    """Return `value` as a number of days when it is a whole number from 1 to 3650, else None."""
    days = positive_integer(value)
    return days if days is not None and days <= MAX_GRACE_PERIOD_DAYS else None


def grace_period() -> timedelta:
    """The deployment's grace period.

    The plugins.E011 start-up check refuses a value outside 1-3650 while plugins are on, so
    this never sees one then.
    """
    return timedelta(days=grace_period_days(settings.PLUGINS_GRACE_PERIOD_DAYS))
