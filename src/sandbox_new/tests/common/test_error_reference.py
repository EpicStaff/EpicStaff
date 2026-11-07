"""The reference that ties a failure the user sees to the log line explaining it.

Lives in foundation, which has no test suite of its own; sandbox_new is one of its users.
"""

import re

import pytest
from foundation.utils.error_reference import (
    REFERENCE_PATTERN,
    log_with_reference,
    trusted_reference,
)
from loguru import logger


@pytest.fixture
def error_records():
    """Every ERROR record logged during the test, with its formatted line."""
    records: list[tuple[dict, str]] = []
    sink_id = logger.add(
        lambda message: records.append((message.record, str(message))), level="ERROR"
    )
    yield records
    logger.remove(sink_id)


def test_each_failure_gets_a_new_reference():
    first = log_with_reference("First failure")
    second = log_with_reference("Second failure")

    assert re.fullmatch(REFERENCE_PATTERN, first)
    assert re.fullmatch(REFERENCE_PATTERN, second)
    assert first != second


def test_a_reference_minted_earlier_is_logged_and_returned(error_records):
    returned = log_with_reference("Run failed", reference="0123456789ab")

    assert returned == "0123456789ab"
    ((record, _),) = error_records
    assert record["message"].startswith("(reference: 0123456789ab) ")


def test_the_log_line_opens_with_the_reference_and_carries_it_as_an_extra(error_records):
    reference = log_with_reference("Run of graph {} failed in {where}", 42, where="crew")

    ((record, _),) = error_records
    assert record["level"].name == "ERROR"
    assert record["message"] == f"(reference: {reference}) Run of graph 42 failed in crew"
    assert record["extra"]["reference"] == reference


def test_the_traceback_is_logged_only_when_the_exception_is_given(error_records):
    try:
        raise RuntimeError("the provider said no")
    except RuntimeError as error:
        log_with_reference("Call failed", exception=error)
    log_with_reference("Call failed without a traceback")

    ((with_exception, with_line), (without_exception, without_line)) = error_records
    assert with_exception["exception"] is not None
    assert "RuntimeError: the provider said no" in with_line
    assert without_exception["exception"] is None
    assert "Traceback" not in without_line


def test_raw_text_with_braces_in_a_field_is_logged_as_it_is(error_records):
    raw = "KeyError: '{api_key}' missing in {}"

    reference = log_with_reference("Tool failed: {error}", error=raw)

    ((record, _),) = error_records
    assert record["message"] == f"(reference: {reference}) Tool failed: {raw}"


def test_the_log_record_names_the_caller(error_records):
    log_with_reference("Failed")

    ((record, _),) = error_records
    assert record["function"] == "test_the_log_record_names_the_caller"


def test_an_expected_failure_is_logged_at_the_level_given():
    records: list[dict] = []
    sink_id = logger.add(lambda message: records.append(message.record), level="DEBUG")
    try:
        reference = log_with_reference("Agent hit its time limit", level="WARNING")
    finally:
        logger.remove(sink_id)

    (record,) = records
    assert record["level"].name == "WARNING"
    assert record["message"] == f"(reference: {reference}) Agent hit its time limit"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0123456789ab", "0123456789ab"),
        ("<b>x</b>", None),
        ("0123456789AB", None),
        ("0123456789abc", None),
        ("0123456789a", None),
        ("0123456789ab\n", None),
        (123456789012, None),
        (None, None),
    ],
    ids=["well-formed", "markup", "uppercase", "too-long", "too-short", "trailing-newline", "not-a-string", "none"],
)
def test_only_a_well_formed_reference_is_trusted(value, expected):
    assert trusted_reference(value) == expected
