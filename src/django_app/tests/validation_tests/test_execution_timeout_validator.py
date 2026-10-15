"""`normalize_execution_timeout`: the one rule every write of a PythonCode's
`execution_timeout` goes through (the API serializer and the import serializer).

Invariant: a value below the minimum is rejected; a value above the maximum is lowered
to the maximum rather than rejected, because the maximum is deployment configuration that
can be lowered after a flow was saved or exported; with no maximum the value is kept, up to
the largest the column can hold.
"""

import pytest
from rest_framework import serializers

from tables.validators.execution_timeout_validator import normalize_execution_timeout

MAX_SECONDS = 600
STORABLE_SECONDS = 2_147_483_647


@pytest.mark.parametrize(
    ("max_seconds", "requested", "expected"),
    [
        (MAX_SECONDS, 3, 3),
        (MAX_SECONDS, 90, 90),
        (MAX_SECONDS, MAX_SECONDS, MAX_SECONDS),
        (MAX_SECONDS, MAX_SECONDS + 1, MAX_SECONDS),
        (None, 3, 3),
        (None, 10_000_000, 10_000_000),
        (None, STORABLE_SECONDS, STORABLE_SECONDS),
        (None, STORABLE_SECONDS + 1, STORABLE_SECONDS),
    ],
    ids=[
        "minimum",
        "within",
        "maximum",
        "above-maximum-is-lowered",
        "no-maximum-minimum",
        "no-maximum-keeps-large",
        "no-maximum-keeps-storable",
        "no-maximum-above-storable-is-lowered",
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
