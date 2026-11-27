"""The `epicstaff_secret(<name>)` marker syntax as django_app reads it, without a database."""

import time

import pytest
from tables.services.secrets.secret_resolver import SecretResolver, extract_secret_marker_names

from tests.sealed_values import consumer_cryptographer


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("epicstaff_secret(name)", {"name"}),
        ("epicstaff_secret(  name  )", {"name"}),
        ("epicstaff_secret(my name)", {"my name"}),
        ("epicstaff_secret(\n name \t)", {"name"}),
        ("epicstaff_secret(a(b)", {"a(b"}),
        ("Bearer epicstaff_secret(one);x=epicstaff_secret( two )", {"one", "two"}),
        ("epicstaff_secret(name) tail)", {"name"}),
        ("epicstaff_secret(name", set()),
        ("epicstaff_secret()", set()),
        ("epicstaff_secret(   )", set()),
        ("epicstaff_secret(open epicstaff_secret(inner)", {"inner"}),
        ("epicstaff_secret(epicstaff_secret(inner)", {"inner"}),
        ("epicstaff_secret( epicstaff_secret(inner)", {"inner"}),
    ],
    ids=[
        "plain",
        "padded",
        "inner-space",
        "padded-newline-tab",
        "open-paren-in-name",
        "two-markers",
        "stops-at-first-close",
        "unclosed",
        "empty",
        "blank",
        "unclosed-before-closed",
        "unclosed-right-before-closed",
        "unclosed-space-before-closed",
    ],
)
def test_marker_names_read_from_a_value(value, expected):
    assert extract_secret_marker_names({"X-Key": value}) == expected


def test_opening_sealed_markers_keeps_the_text_around_them():
    sealed = consumer_cryptographer().encrypt("token-1")
    headers = {"Authorization": f"Bearer epicstaff_secret(  {sealed}  ) tail"}

    assert SecretResolver().open_sealed_markers(headers=headers) == {
        "Authorization": "Bearer token-1 tail"
    }


ADVERSARIAL_VALUES = [
    pytest.param("epicstaff_secret(a" + " " * 50_000, id="name-then-spaces"),
    pytest.param("epicstaff_secret(" + " " * 50_000, id="spaces-only"),
    pytest.param("epicstaff_secret( " * 3_000, id="repeated-unclosed"),
]


@pytest.mark.parametrize("value", ADVERSARIAL_VALUES)
def test_reading_names_from_a_long_unclosed_marker_is_fast(value):
    started = time.perf_counter()
    names = extract_secret_marker_names({"X-Key": value})

    assert time.perf_counter() - started < 1.0
    assert names == set()


@pytest.mark.parametrize("value", ADVERSARIAL_VALUES)
def test_opening_a_long_unclosed_marker_is_fast(value):
    started = time.perf_counter()
    opened = SecretResolver().open_sealed_markers(headers={"X-Key": value})

    assert time.perf_counter() - started < 1.0
    assert opened == {"X-Key": value}
