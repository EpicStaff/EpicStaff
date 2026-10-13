"""Behavior of the venv row mapper.

Piccolo can hand back a JSONB column as a list or as a string depending on its
configuration, so both shapes are covered.
"""

from types import SimpleNamespace

from manager.domain.enums import VenvStatus
from manager.infrastructure.database.venvs.mappers import VenvMapper
from tests.builders import make_library


def make_row(**overrides):
    fields = {
        "id": 1,
        "name": "default",
        "libs": [],
        "hash": "1abc",
        "status": "completed",
        "error": None,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def test_to_domain_reads_libraries_given_as_a_list():
    venv = VenvMapper.to_domain(
        make_row(libs=[{"name": "pandas", "specification": ">=2.0", "version": None}])
    )

    assert [(lib.name, lib.specification) for lib in venv.libs] == [("pandas", ">=2.0")]
    assert venv.status is VenvStatus.COMPLETED


def test_to_domain_reads_libraries_given_as_a_json_string():
    venv = VenvMapper.to_domain(
        make_row(libs='[{"name": "pandas", "specification": ">=2.0", "version": null}]')
    )

    assert [lib.name for lib in venv.libs] == ["pandas"]


def test_to_domain_treats_a_null_libraries_column_as_empty():
    assert VenvMapper.to_domain(make_row(libs=None)).libs == []


def test_to_domain_carries_the_error_text():
    assert VenvMapper.to_domain(make_row(status="failed", error="uv blew up")).error == "uv blew up"


def test_dump_libs_round_trips_through_to_domain():
    libs = [make_library(name="pandas", specification=">=2.0", version="2.1.0")]

    venv = VenvMapper.to_domain(make_row(libs=VenvMapper.dump_libs(libs)))

    assert venv.libs == libs
