"""The data migration that brings stored venv libraries under today's rules.

Earlier releases stored a library name only canonicalized, so a row can hold a version
bound inside the name (`numpy>=1`), with its dots turned into dashes by the
canonicalization (`numpy>=1-26`), or an entry no rule accepts now. After the migration
every entry left in a row must read as a `Library`, and a row as a `Venv`, or the
mapper fails every list that touches the row; whatever cannot be kept is listed as
dropped.
"""

import importlib

import pytest

from manager.domain.models import Library, Venv

migration = importlib.import_module(
    "manager.infrastructure.database.venvs.migrations.venvs_2026_11_19t12_00_00_000000"
)


def stored(name, specification="", version=None, is_custom=False):
    return {
        "name": name,
        "description": None,
        "specification": specification,
        "version": version,
        "is_custom": is_custom,
    }


@pytest.mark.parametrize(
    ("entry", "expected_name", "expected_specification"),
    [
        pytest.param(stored("numpy>=1"), "numpy", ">=1", id="lower-bound"),
        pytest.param(
            stored("pydantic>=2,<3"), "pydantic", ">=2,<3", id="both-bounds-kept-in-order"
        ),
        pytest.param(stored("pydantic<3,>=2"), "pydantic", "<3,>=2", id="order-as-written"),
        pytest.param(
            stored("requests==2-31-0"), "requests", "==2.31.0", id="dots-restored-in-a-pin"
        ),
        pytest.param(stored("numpy>=1-26"), "numpy", ">=1.26", id="dots-restored"),
        pytest.param(stored("requests[socks]>=2"), "requests[socks]", ">=2", id="extras-kept"),
        pytest.param(stored("numpy(>=1)"), "numpy", ">=1", id="parenthesised"),
        pytest.param(stored("six~=1-16"), "six", "~=1.16", id="compatible-release"),
        pytest.param(
            stored("numpy>=1", "<2"), "numpy", ">=1,<2", id="joined-with-the-specification"
        ),
    ],
)
def test_a_bound_in_the_name_moves_to_the_specification(
    entry, expected_name, expected_specification
):
    libraries, dropped = migration._migrate_libraries([entry])

    assert dropped == []
    assert [(lib["name"], lib["specification"]) for lib in libraries] == [
        (expected_name, expected_specification)
    ]
    Library(**libraries[0])


@pytest.mark.parametrize(
    "entry",
    [
        pytest.param(stored("numpy", ">=1"), id="name-and-specification"),
        pytest.param(stored("requests[socks]", ">=2"), id="extras"),
        pytest.param(
            stored("est-test-lib", ">=0.1.0", version="0.1.0", is_custom=True), id="custom"
        ),
        pytest.param(stored("six", ">=1.0, <2"), id="spaced-specification"),
        pytest.param(stored("pandas", ">=2", version="2.2.3"), id="pinned"),
    ],
)
def test_an_entry_valid_today_is_left_exactly_as_stored(entry):
    libraries, dropped = migration._migrate_libraries([entry])

    assert (libraries, dropped) == ([entry], [])


@pytest.mark.parametrize(
    "entry",
    [
        pytest.param(stored("pkg @ https://example.com/pkg.whl"), id="direct-url"),
        pytest.param(stored("numpy;python_version<'3'"), id="marker"),
        pytest.param(stored("-e /etc"), id="editable-path"),
        pytest.param(stored("/etc"), id="path"),
        pytest.param(stored("six\n-i http://evil.example/simple"), id="injected-option"),
        pytest.param(stored("numpy", "===/etc"), id="arbitrary-equality-on-a-path"),
        pytest.param(
            stored("numpy", ">=1, === -r/etc/passwd"), id="arbitrary-equality-on-an-option"
        ),
        pytest.param(stored("numpy", "===1.0\n-r x"), id="arbitrary-equality-then-a-line"),
        pytest.param(stored("numpy", ">=1,\n<2"), id="line-break-in-specification"),
        pytest.param(stored("numpy", ">=1\t<2"), id="tab-in-place-of-a-comma"),
        pytest.param(stored("acme[x]", is_custom=True), id="custom-with-extras"),
        pytest.param(stored("not a name"), id="unreadable"),
    ],
)
def test_an_entry_that_cannot_be_kept_is_dropped_by_its_stored_name(entry):
    libraries, dropped = migration._migrate_libraries([stored("pandas", ">=2"), entry])

    assert libraries == [stored("pandas", ">=2")]
    assert dropped == [entry["name"]]


def test_two_entries_for_one_package_merge_into_the_first():
    """After the split both read as `numpy`; a venv takes one entry per package, and uv
    built this one by honouring both."""
    libraries, dropped = migration._migrate_libraries(
        [stored("numpy"), stored("pandas"), stored("numpy>=1")]
    )

    assert dropped == []
    assert [(lib["name"], lib["specification"]) for lib in libraries] == [
        ("numpy", ">=1"),
        ("pandas", ""),
    ]


@pytest.mark.parametrize(
    ("entries", "expected_name", "expected_specification"),
    [
        pytest.param(
            [stored("requests", ">=2"), stored("requests[socks]>=2")],
            "requests[socks]",
            ">=2",
            id="extras-added",
        ),
        pytest.param(
            [stored("requests[socks]"), stored("requests[security]<3")],
            "requests[security,socks]",
            "<3",
            id="extras-united",
        ),
        pytest.param(
            [stored("pydantic", ">=2"), stored("pydantic<3")],
            "pydantic",
            ">=2,<3",
            id="specifications-joined",
        ),
        pytest.param(
            [stored("Requests", ">=2"), stored("requests")],
            "requests",
            ">=2",
            id="spellings-of-one-package",
        ),
    ],
)
def test_merged_entries_ask_for_everything_both_asked_for(
    entries, expected_name, expected_specification
):
    libraries, dropped = migration._migrate_libraries(entries)

    assert dropped == []
    assert [(lib["name"], lib["specification"]) for lib in libraries] == [
        (expected_name, expected_specification)
    ]
    Library(**libraries[0])


def test_a_merge_keeps_the_pin_only_while_the_joined_specification_admits_it():
    kept, _ = migration._migrate_libraries(
        [stored("pandas", ">=2", version="2.2.3"), stored("pandas<3")]
    )
    cleared, _ = migration._migrate_libraries(
        [stored("pandas", ">=2", version="2.2.3"), stored("pandas<2-2")]
    )

    assert [lib["version"] for lib in kept] == ["2.2.3"]
    assert [lib["version"] for lib in cleared] == [None]


def test_a_package_both_custom_and_not_cannot_merge():
    """No single entry can say both, so the later one is dropped by its stored name."""
    libraries, dropped = migration._migrate_libraries(
        [stored("acme", is_custom=True), stored("acme>=1")]
    )

    assert libraries == [stored("acme", is_custom=True)]
    assert dropped == ["acme>=1"]


def test_a_pin_outside_the_new_specification_is_cleared():
    """The pin is what a build installed; the next build stamps it again."""
    libraries, dropped = migration._migrate_libraries([stored("pandas>=2", version="1.0")])

    assert dropped == []
    assert libraries == [stored("pandas", ">=2", version=None)]
    Library(**libraries[0])


def test_a_pin_inside_the_new_specification_is_kept():
    libraries, _ = migration._migrate_libraries([stored("pandas>=2", version="2.2.3")])

    assert libraries == [stored("pandas", ">=2", version="2.2.3")]


def test_every_row_left_reads_as_a_venv():
    """The guarantee the mapper relies on once it reads rows strictly again."""
    mixed = [
        stored("numpy>=1-26"),
        stored("pydantic<3,>=2"),
        stored("requests[socks]>=2"),
        stored("pkg @ https://example.com/pkg.whl"),
        stored("numpy"),
        stored("six", "===1.0"),
        stored("scipy", ">=1,"),
        stored("pandas>=2", version="1.0"),
    ]

    libraries, dropped = migration._migrate_libraries(mixed)

    Venv(name="mixed", libs=[Library(**library) for library in libraries])
    assert dropped == ["pkg @ https://example.com/pkg.whl"]


def test_an_empty_venv_stays_empty():
    assert migration._migrate_libraries([]) == ([], [])


# A malformed entry must not raise: the migration runs at start-up, and an exception
# there would keep the sandbox from starting at all.
@pytest.mark.parametrize(
    ("entry", "dropped_as"),
    [
        pytest.param("numpy", "numpy", id="not-an-object"),
        pytest.param(None, "None", id="null"),
        pytest.param({"specification": ">=1"}, "{'specification': '>=1'}", id="no-name"),
        pytest.param(
            {"name": 7, "specification": ""}, "{'name': 7, 'specification': ''}", id="name-not-text"
        ),
        pytest.param(stored("numpy", specification=[">=1"]), "numpy", id="specification-not-text"),
    ],
)
def test_a_malformed_entry_is_dropped_instead_of_raising(entry, dropped_as):
    libraries, dropped = migration._migrate_libraries([stored("pandas", ">=2"), entry])

    assert libraries == [stored("pandas", ">=2")]
    assert dropped == [dropped_as]


def test_an_entry_without_a_specification_key_reads_as_unbounded():
    libraries, dropped = migration._migrate_libraries([{"name": "numpy>=1"}])

    assert dropped == []
    assert [(lib["name"], lib["specification"]) for lib in libraries] == [("numpy", ">=1")]


@pytest.mark.parametrize("version", ["latest", "1.0 ", 1.0, "v1"])
def test_a_pin_that_is_not_a_version_is_cleared(version):
    libraries, dropped = migration._migrate_libraries([stored("pandas>=0", version=version)])

    assert dropped == []
    assert libraries[0]["version"] is None
    Library(**libraries[0])


@pytest.mark.parametrize(
    ("entries", "rewritten"),
    [
        pytest.param([stored("numpy>=1-26")], True, id="dots-restored"),
        pytest.param([stored("pandas"), stored("requests==2-31-0")], True, id="one-of-several"),
        pytest.param([stored("numpy>=1")], False, id="bound-without-dashes"),
        pytest.param([stored("scikit-learn", ">=1.0")], False, id="dash-in-a-valid-name"),
        pytest.param([stored("scikit-learn>=1")], False, id="dash-in-the-name-not-the-bound"),
        pytest.param(["numpy>=1-26", None], False, id="malformed"),
        pytest.param([], False, id="empty"),
    ],
)
def test_a_venv_is_rebuilt_only_when_a_bound_had_its_dots_restored(entries, rewritten):
    """uv read `>=1-26` as `>=1.post26`, so what it built may lie outside `>=1.26`."""
    assert migration._a_bound_was_rewritten(entries) is rewritten


# Built and worked under an earlier release, refused now, read by uv the same way once
# rewritten: repaired so the venv keeps working, rather than failed.
@pytest.mark.parametrize(
    ("entry", "expected_specification"),
    [
        pytest.param(stored("numpy", ">=1,"), ">=1", id="trailing-comma"),
        pytest.param(stored("numpy", ",>=1"), ">=1", id="leading-comma"),
        pytest.param(stored("numpy", ">=1,,<2"), ">=1,<2", id="doubled-comma"),
        pytest.param(stored("numpy", ">=1, ,<2"), ">=1,<2", id="blank-clause"),
        pytest.param(stored("numpy", "===1.0"), "==1.0", id="arbitrary-equality-on-a-version"),
        pytest.param(stored("numpy", "<2, ===1.0"), "<2, ==1.0", id="arbitrary-equality-in-a-set"),
        pytest.param(stored("numpy===1-0"), "==1.0", id="arbitrary-equality-in-the-name"),
        pytest.param(stored("numpy", ">=1,\t<2"), ">=1, <2", id="tab-after-a-comma"),
        pytest.param(stored("numpy", ">=1,\u00a0<2"), ">=1, <2", id="non-breaking-space"),
    ],
)
def test_a_specification_uv_read_the_same_way_is_repaired(entry, expected_specification):
    libraries, dropped = migration._migrate_libraries([entry])

    assert dropped == []
    assert [lib["specification"] for lib in libraries] == [expected_specification]
    Library(**libraries[0])


def test_a_repaired_specification_keeps_the_pin_and_needs_no_rebuild():
    """`==1.0` admits exactly what `===1.0` did, so what was built still holds."""
    entries = [stored("numpy", "===1.0", version="1.0")]

    libraries, _ = migration._migrate_libraries(entries)

    assert libraries == [stored("numpy", "==1.0", version="1.0")]
    assert migration._a_bound_was_rewritten(entries) is False
