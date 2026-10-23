"""Behavior of the venv row mapper.

The rows are real ``VenvTable`` instances rather than a hand-rolled double, so a column
the mapper reads but the table does not have fails here instead of in production. Every
column is supplied, which is also what ``RETURNING`` gives the repository, so Piccolo
needs no engine to build one. Piccolo can hand back a JSONB column as a list or as a
string depending on its configuration, so both shapes are covered.
"""

from datetime import UTC, datetime

from manager.domain.enums import VenvStatus
from manager.infrastructure.database.venvs.mappers import VenvMapper
from manager.infrastructure.database.venvs.tables import VenvTable
from tests.builders import make_library


def make_row(**overrides):
    fields = {
        "id": 1,
        "name": "default",
        "libs": [],
        "hash": "1abc",
        "status": "completed",
        "error": None,
        "created_at": datetime(2026, 10, 14, 11, 17, 37, tzinfo=UTC),
        "updated_at": datetime(2026, 10, 14, 12, 0, 0, tzinfo=UTC),
    }
    fields.update(overrides)
    return VenvTable(**fields)


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
    libs = [
        make_library(
            name="pandas", description="dataframes", specification=">=2.0", version="2.1.0"
        )
    ]

    venv = VenvMapper.to_domain(make_row(libs=VenvMapper.dump_libs(libs)))

    assert venv.libs == libs


def test_to_domain_carries_the_database_timestamps():
    venv = VenvMapper.to_domain(make_row())

    assert venv.created_at == datetime(2026, 10, 14, 11, 17, 37, tzinfo=UTC)
    assert venv.updated_at == datetime(2026, 10, 14, 12, 0, 0, tzinfo=UTC)
