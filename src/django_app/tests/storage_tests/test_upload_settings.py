from pathlib import Path

import pytest
import yaml
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from django_app.spectacular_hooks import add_stream_upload_postprocessing_hook
from src.shared import humanize
from tables.constants.storage_constants import UPLOAD_STREAM_PATH
from tables.validators.upload_settings_validator import (
    parse_minio_duration,
    validate_upload_settings,
)

ENV_SCHEMA = Path(__file__).resolve().parents[3] / "env.yaml"


def test_new_settings_present():
    assert settings.ORG_STORAGE_QUOTA > 0
    assert settings.MAX_ARCHIVE_FILE_SIZE > 0
    assert settings.UPLOAD_PART_SIZE >= 5 * 1024 * 1024
    assert settings.UPLOAD_MAX_CONCURRENCY >= 1


def test_stream_endpoint_is_in_the_schema():
    result = add_stream_upload_postprocessing_hook({}, None, None, True)
    operation = result["paths"][UPLOAD_STREAM_PATH]["post"]
    assert operation["requestBody"]["content"]["application/octet-stream"]
    assert {"filename", "path"} == {p["name"] for p in operation["parameters"]}


def test_the_stream_endpoint_schema_documents_the_per_file_size_limit():
    operation = add_stream_upload_postprocessing_hook({}, None, None, True)["paths"][
        UPLOAD_STREAM_PATH
    ]["post"]

    assert "DJANGO_MAX_STREAM_UPLOAD_FILE_SIZE" in operation["description"]
    assert "upload_too_large" in operation["responses"]["413"]["description"]


MIB = 1024 * 1024
HOUR = 3600.0


def _validate(**overrides):
    values = {
        "part_size": 16 * MIB,
        "storage_quota": 50 * 1024 * MIB,
        "max_stream_file_size": None,
        "max_archive_file_size": 50 * MIB,
        "max_concurrency": 4,
        "per_org_limit": 4,
        "slot_timeout": 30.0,
        "idle_timeout": 120.0,
        "max_duration": 5 * HOUR,
        "stale_uploads_expiry": 6 * HOUR,
    } | overrides
    validate_upload_settings(**values)


def _shipped_default(name: str) -> str:
    """The default env.yaml ships for `name`, as the generated .env line holds it."""
    for group in yaml.safe_load(ENV_SCHEMA.read_text())["groups"].values():
        variable = group.get("vars", {}).get(name)
        if variable is not None:
            return str(variable["default"])
    raise KeyError(name)


def _shipped_byte_size_or_none(name: str) -> int | None:
    raw = _shipped_default(name)
    return None if raw.lower() == "none" else humanize.to_byte_size(raw)


def test_shipped_upload_defaults():
    # Read from env.yaml, not settings: a developer's .env may override any of these.
    assert _shipped_default("DJANGO_UPLOAD_MAX_CONCURRENCY") == "4"
    assert _shipped_default("DJANGO_UPLOAD_MAX_CONCURRENCY_PER_ORG") == "4"
    assert humanize.to_time(_shipped_default("DJANGO_UPLOAD_SLOT_TIMEOUT")) == 30
    assert humanize.to_time(_shipped_default("DJANGO_UPLOAD_IDLE_TIMEOUT")) == 120
    assert humanize.to_time(_shipped_default("DJANGO_UPLOAD_MAX_DURATION")) == 5 * HOUR
    assert _shipped_default("MINIO_STALE_UPLOADS_EXPIRY") == "6h"
    assert _shipped_byte_size_or_none("DJANGO_MAX_STREAM_UPLOAD_FILE_SIZE") == 2 * 1024 * MIB
    assert _shipped_byte_size_or_none("DJANGO_MAX_ARCHIVE_FILE_SIZE") == 50 * MIB


def test_the_shipped_defaults_pass_validation():
    _validate(
        part_size=humanize.to_byte_size(_shipped_default("DJANGO_UPLOAD_PART_SIZE")),
        storage_quota=humanize.to_byte_size(_shipped_default("DJANGO_ORG_STORAGE_QUOTA")),
        max_stream_file_size=_shipped_byte_size_or_none("DJANGO_MAX_STREAM_UPLOAD_FILE_SIZE"),
        max_archive_file_size=_shipped_byte_size_or_none("DJANGO_MAX_ARCHIVE_FILE_SIZE"),
        max_concurrency=int(_shipped_default("DJANGO_UPLOAD_MAX_CONCURRENCY")),
        per_org_limit=int(_shipped_default("DJANGO_UPLOAD_MAX_CONCURRENCY_PER_ORG")),
        slot_timeout=humanize.to_time(_shipped_default("DJANGO_UPLOAD_SLOT_TIMEOUT")),
        idle_timeout=humanize.to_time(_shipped_default("DJANGO_UPLOAD_IDLE_TIMEOUT")),
        max_duration=humanize.to_time(_shipped_default("DJANGO_UPLOAD_MAX_DURATION")),
        stale_uploads_expiry=parse_minio_duration(
            "MINIO_STALE_UPLOADS_EXPIRY", _shipped_default("MINIO_STALE_UPLOADS_EXPIRY")
        ),
    )


def test_part_size_below_the_s3_minimum_fails_startup():
    with pytest.raises(ImproperlyConfigured, match="at least"):
        _validate(part_size=5 * MIB - 1)
    _validate(part_size=5 * MIB, storage_quota=5 * MIB * 10_000)


def test_quota_a_single_file_cannot_fill_within_10000_parts_fails_startup():
    with pytest.raises(ImproperlyConfigured, match="10000 S3 parts"):
        _validate(part_size=16 * MIB, storage_quota=16 * MIB * 10_000 + 1)
    _validate(part_size=16 * MIB, storage_quota=16 * MIB * 10_000)


@pytest.mark.parametrize("max_duration", [6 * HOUR, 7 * HOUR])
def test_max_duration_not_below_the_minio_expiry_fails_startup(max_duration):
    with pytest.raises(ImproperlyConfigured, match="MINIO_STALE_UPLOADS_EXPIRY"):
        _validate(max_duration=max_duration, stale_uploads_expiry=6 * HOUR)


@pytest.mark.parametrize(
    "name", ["max_concurrency", "per_org_limit", "idle_timeout", "max_duration"]
)
@pytest.mark.parametrize("value", [None, 0, -1])
def test_a_limit_that_is_none_or_not_positive_fails_startup(name, value):
    with pytest.raises(ImproperlyConfigured, match="must be a positive value"):
        _validate(**{name: value})


@pytest.mark.parametrize("slot_timeout", [None, 0.5, 30.0])
def test_an_unbounded_or_positive_slot_timeout_passes(slot_timeout):
    _validate(slot_timeout=slot_timeout)


@pytest.mark.parametrize("slot_timeout", [0, -1])
def test_a_slot_timeout_that_is_not_positive_fails_startup(slot_timeout):
    with pytest.raises(ImproperlyConfigured, match="DJANGO_UPLOAD_SLOT_TIMEOUT"):
        _validate(slot_timeout=slot_timeout)


@pytest.mark.parametrize("max_stream_file_size", [None, 1, 500 * MIB])
def test_an_unlimited_or_positive_max_stream_file_size_passes(max_stream_file_size):
    _validate(max_stream_file_size=max_stream_file_size)


@pytest.mark.parametrize("max_stream_file_size", [0, -1])
def test_a_max_stream_file_size_that_is_not_positive_fails_startup(max_stream_file_size):
    with pytest.raises(ImproperlyConfigured, match="DJANGO_MAX_STREAM_UPLOAD_FILE_SIZE"):
        _validate(max_stream_file_size=max_stream_file_size)


@pytest.mark.parametrize("max_archive_file_size", [None, 0, -1])
def test_a_max_archive_file_size_that_is_none_or_not_positive_fails_startup(
    max_archive_file_size,
):
    with pytest.raises(ImproperlyConfigured, match="DJANGO_MAX_ARCHIVE_FILE_SIZE"):
        _validate(max_archive_file_size=max_archive_file_size)


def test_an_org_limit_above_the_worker_slots_fails_startup():
    with pytest.raises(ImproperlyConfigured, match="DJANGO_UPLOAD_MAX_CONCURRENCY_PER_ORG"):
        _validate(max_concurrency=4, per_org_limit=5)
    _validate(max_concurrency=4, per_org_limit=4)
    _validate(max_concurrency=4, per_org_limit=1)


@pytest.mark.parametrize(
    ("raw", "seconds"), [("6h", 6 * HOUR), ("90m", 5400.0), ("30s", 30.0), ("1.5h", 1.5 * HOUR)]
)
def test_a_go_duration_for_minio_is_parsed(raw, seconds):
    assert parse_minio_duration("MINIO_STALE_UPLOADS_EXPIRY", raw) == seconds


@pytest.mark.parametrize("raw", ["21600", "1d", "6H", "6 h", "6h30m", "h", "", None])
def test_a_duration_outside_the_syntax_minio_and_django_share_fails_startup(raw):
    with pytest.raises(ImproperlyConfigured, match="Go duration"):
        parse_minio_duration("MINIO_STALE_UPLOADS_EXPIRY", raw)
