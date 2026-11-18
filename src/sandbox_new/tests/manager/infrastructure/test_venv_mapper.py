"""Behavior of the venv row mapper.

The rows are real ``VenvTable`` instances rather than a hand-rolled double, so a column
the mapper reads but the table does not have fails here instead of in production. Every
column is supplied, which is also what ``RETURNING`` gives the repository, so Piccolo
needs no engine to build one. Piccolo can hand back a JSONB column as a list or as a
string depending on its configuration, so both shapes are covered.
"""

import json
from datetime import UTC, datetime

import pytest

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


# Stored by an earlier release, which let a version specifier into the name.
LEGACY_LIBRARY = {
    "name": "numpy>=1",
    "description": None,
    "specification": "",
    "version": None,
    "is_custom": False,
}
VALID_LIBRARY = {
    "name": "pandas",
    "description": None,
    "specification": ">=2.0",
    "version": None,
    "is_custom": False,
}


def test_to_domain_reads_a_library_the_rules_now_refuse_instead_of_raising():
    """One such row would otherwise fail every list holding it, the build and cleanup
    loops included, for every other venv as well."""
    venv = VenvMapper.to_domain(make_row(libs=[VALID_LIBRARY, LEGACY_LIBRARY]))

    assert [lib.name for lib in venv.libs] == ["pandas", "numpy>=1"]
    assert [lib.rejection is None for lib in venv.libs] == [True, False]
    assert venv.status is VenvStatus.COMPLETED


def test_to_domain_reads_a_refused_library_given_as_a_json_string():
    venv = VenvMapper.to_domain(make_row(libs=json.dumps([LEGACY_LIBRARY])))

    assert venv.libs[0].rejection is not None


def test_a_refused_library_is_written_back_exactly_as_it_was_stored():
    """Renaming the venv, or failing its build, rewrites the row; the entry the user has
    to fix must still be there, unchanged, when they come to fix it."""
    venv = VenvMapper.to_domain(make_row(libs=[VALID_LIBRARY, LEGACY_LIBRARY]))

    assert VenvMapper.dump_libs(venv.libs) == [VALID_LIBRARY, LEGACY_LIBRARY]


@pytest.mark.parametrize(
    "stored",
    [
        pytest.param({**VALID_LIBRARY, "name": "acme[extra]", "is_custom": True}, id="custom-with-extras"),
        pytest.param({**VALID_LIBRARY, "version": "1.0"}, id="pin-outside-specification"),
    ],
)
def test_to_domain_reads_a_row_refused_by_a_whole_library_rule(stored):
    """Rules that look at the whole library run again when the venv takes it in, so a
    row they refuse must still read rather than fail every list holding it."""
    venv = VenvMapper.to_domain(make_row(libs=[VALID_LIBRARY, stored]))

    assert [lib.rejection is None for lib in venv.libs] == [True, False]
    assert VenvMapper.dump_libs(venv.libs) == [VALID_LIBRARY, stored]


def test_to_domain_reads_rejected_libraries_that_name_the_same_package():
    """Rejected libraries never build, so two of them for one package, or one next to
    a valid entry for it, are not a repeat the venv refuses to read."""
    rejected = {**VALID_LIBRARY, "specification": "===2.0"}
    bound_in_name = {**VALID_LIBRARY, "name": "pandas>=1", "specification": ""}

    venv = VenvMapper.to_domain(
        make_row(libs=[VALID_LIBRARY, rejected, rejected, bound_in_name, bound_in_name])
    )

    assert [(lib.name, lib.rejection is None) for lib in venv.libs] == [
        ("pandas", True),
        ("pandas", False),
        ("pandas", False),
        ("pandas>=1", False),
        ("pandas>=1", False),
    ]
