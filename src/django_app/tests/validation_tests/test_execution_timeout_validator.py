"""The rules every write of a PythonCode's `execution_timeout` goes through.

Invariant: through the API a value below the minimum is rejected; a value above the
maximum is lowered to the maximum rather than rejected, because the maximum is deployment
configuration that can be lowered after a flow was saved; with no maximum the value is
kept. An import file may come from a deployment or release with other limits, so on import
a value below the minimum is raised to the minimum instead of being rejected.
"""

import pytest
from rest_framework import serializers

from tables.validators.execution_timeout_validator import (
    normalize_execution_timeout,
    normalize_imported_execution_timeout,
)

MAX_SECONDS = 600


@pytest.mark.parametrize(
    ("max_seconds", "requested", "expected"),
    [
        (MAX_SECONDS, 3, 3),
        (MAX_SECONDS, 90, 90),
        (MAX_SECONDS, MAX_SECONDS, MAX_SECONDS),
        (MAX_SECONDS, MAX_SECONDS + 1, MAX_SECONDS),
        (None, 3, 3),
        (None, 10_000_000, 10_000_000),
    ],
    ids=[
        "minimum",
        "within",
        "maximum",
        "above-maximum-is-lowered",
        "no-maximum-minimum",
        "no-maximum-keeps-large",
    ],
)
def test_accepted_values(settings, max_seconds, requested, expected):
    settings.MAX_EXECUTION_TIMEOUT_SECONDS = max_seconds

    assert normalize_execution_timeout(requested) == expected


@pytest.mark.parametrize("max_seconds", [MAX_SECONDS, None], ids=["with-maximum", "no-maximum"])
@pytest.mark.parametrize("requested", [2, 0, -1], ids=["below-minimum", "zero", "negative"])
def test_below_the_minimum_is_rejected(settings, max_seconds, requested):
    settings.MAX_EXECUTION_TIMEOUT_SECONDS = max_seconds

    with pytest.raises(serializers.ValidationError, match="at least 3 seconds"):
        normalize_execution_timeout(requested)


@pytest.mark.parametrize(
    ("max_seconds", "requested", "expected"),
    [
        (MAX_SECONDS, 2, 3),
        (MAX_SECONDS, 0, 3),
        (MAX_SECONDS, 90, 90),
        (MAX_SECONDS, MAX_SECONDS + 1, MAX_SECONDS),
        (None, 0, 3),
        (None, 10_000_000, 10_000_000),
    ],
    ids=[
        "below-minimum-is-raised",
        "zero-is-raised",
        "within",
        "above-maximum-is-lowered",
        "no-maximum-zero-is-raised",
        "no-maximum-keeps-large",
    ],
)
def test_imported_values_are_moved_into_range(settings, max_seconds, requested, expected):
    settings.MAX_EXECUTION_TIMEOUT_SECONDS = max_seconds

    assert normalize_imported_execution_timeout(requested) == expected
