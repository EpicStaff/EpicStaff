"""Behavior of the manager's domain models."""

import pytest
from pydantic import ValidationError

from manager.domain.enums import VenvStatus
from manager.domain.models import Library, Venv
from tests.builders import make_library, make_venv


@pytest.mark.parametrize("specification", ["", ">=2.0", ">=1.0,<2", "==1.2.3", "~=1.4"])
def test_library_accepts_valid_version_specifications(specification):
    assert make_library(specification=specification).specification == specification


@pytest.mark.parametrize("specification", ["=>2.0", "2.0", ">>1.0"])
def test_library_rejects_invalid_version_specifications(specification):
    with pytest.raises(ValidationError):
        make_library(specification=specification)


@pytest.mark.parametrize("version", ["1.2.3", "1", "2!1.0rc1.post1.dev2", "1.0b2"])
def test_library_accepts_valid_versions(version):
    assert make_library(specification="", version=version).version == version


@pytest.mark.parametrize("version", ["01.2", "v1.2", "1.2.3.", "latest"])
def test_library_rejects_invalid_versions(version):
    with pytest.raises(ValidationError):
        make_library(specification="", version=version)


def test_library_rejects_an_empty_name():
    with pytest.raises(ValidationError):
        Library(name="")


def test_venv_rename_changes_the_name():
    venv = make_venv(name="old")
    venv.rename("new")
    assert venv.name == "new"


@pytest.mark.parametrize("name", ["data", "Data Science", "data_science", "py311-base"])
def test_venv_accepts_a_name_of_letters_digits_spaces_hyphens_and_underscores(name):
    assert make_venv(name=name).name == name


@pytest.mark.parametrize("name", ["", "data.science", "data/science", "venv!", "venv\u00e9"])
def test_venv_rejects_a_name_with_any_other_character(name):
    with pytest.raises(ValidationError):
        make_venv(name=name)


def test_venv_rename_rejects_a_name_with_any_other_character():
    venv = make_venv(name="old")
    with pytest.raises(ValidationError):
        venv.rename("new!")


def test_venv_set_libs_returns_the_venv_to_declared_and_clears_the_error():
    venv = make_venv(status=VenvStatus.FAILED, error="uv blew up")
    libs = [make_library(name="pandas")]

    venv.set_libs(libs)

    assert venv.libs == libs
    assert venv.status is VenvStatus.DECLARED
    assert venv.error is None


def test_venv_mark_as_processing_keeps_a_previous_error():
    venv = make_venv(status=VenvStatus.FAILED, error="uv blew up")
    venv.mark_as_processing()
    assert venv.status is VenvStatus.PROCESSING
    assert venv.error == "uv blew up"


def test_venv_mark_as_completed_clears_the_error():
    venv = make_venv(status=VenvStatus.PROCESSING, error="stale")
    venv.mark_as_completed()
    assert venv.status is VenvStatus.COMPLETED
    assert venv.error is None


def test_venv_mark_as_failed_records_the_exception_text():
    venv = make_venv(status=VenvStatus.PROCESSING)
    venv.mark_as_failed(RuntimeError("uv pip sync failed"))
    assert venv.status is VenvStatus.FAILED
    assert venv.error == "uv pip sync failed"


def test_venv_id_cannot_be_reassigned():
    venv = Venv(id=1, name="default")
    with pytest.raises(ValidationError):
        venv.id = 2


@pytest.mark.parametrize(
    ("specification", "version"),
    [
        (">=2.0", "2.1.0"),
        (">=1.0,<2", "1.9.9"),
        ("==1.2.3", "1.2.3"),
        ("~=1.4", "1.4.2"),
        ("", "0.0.1"),
        (">=1.0", "2.0b1"),
        (">=2.0", "2.1.0+cu118"),
    ],
)
def test_library_accepts_a_version_that_satisfies_its_specification(specification, version):
    assert make_library(specification=specification, version=version).version == version


@pytest.mark.parametrize(
    ("specification", "version"),
    [
        (">=2.0", "1.9.0"),
        ("<2", "2.0"),
        ("==1.2.3", "1.2.4"),
        ("~=1.4", "2.0"),
    ],
)
def test_library_rejects_a_version_outside_its_specification(specification, version):
    with pytest.raises(ValidationError):
        make_library(specification=specification, version=version)


@pytest.mark.parametrize(
    ("given", "stored"),
    [
        ("zope.interface", "zope-interface"),
        ("Pillow", "pillow"),
        ("ruamel_yaml", "ruamel-yaml"),
        ("typing--extensions", "typing-extensions"),
        ("requests", "requests"),
    ],
)
def test_library_stores_the_name_the_way_the_index_normalizes_it(given, stored):
    assert make_library(name=given).name == stored


def test_library_description_is_optional():
    assert make_library().description is None
    assert make_library(description="HTTP for humans").description == "HTTP for humans"


@pytest.mark.parametrize(
    ("specification", "version", "expected"),
    [
        (">=2.0", None, "requests>=2.0"),
        ("", None, "requests"),
        (">=2.0", "2.31.0", "requests==2.31.0"),
        ("", "2.31.0", "requests==2.31.0"),
    ],
)
def test_library_requirement_pins_an_explicit_version_and_falls_back_to_the_specification(
    specification, version, expected
):
    assert make_library(specification=specification, version=version).requirement == expected


def test_venv_apply_resolved_versions_stamps_each_library():
    venv = make_venv(
        libs=[
            make_library(name="pandas", specification=">=2.0"),
            make_library(name="numpy", specification=""),
        ]
    )

    venv.apply_resolved_versions({"pandas": "2.2.3", "numpy": "1.26.4"})

    assert [(lib.name, lib.version) for lib in venv.libs] == [
        ("pandas", "2.2.3"),
        ("numpy", "1.26.4"),
    ]


@pytest.mark.parametrize(
    ("declared_specification", "declared_version", "expected_specification"),
    [
        # Only a name: uv picks a release, and the stamped `>=` becomes the guard rail
        # the user's later version edits are held to.
        ("", None, ">=2.2.3"),
        # A version and no specification: the guard rail is built from what went in.
        ("", "2.2.3", ">=2.2.3"),
        # The user's own specification is their statement of intent; the build keeps it.
        (">=2.0", None, ">=2.0"),
        (">=2.0", "2.2.3", ">=2.0"),
        ("!=2.1,>=2.0,<=2.3", "2.2.3", "!=2.1,>=2.0,<=2.3"),
    ],
    ids=["name-only", "version-only", "specification-only", "both", "complex-specification"],
)
def test_venv_apply_resolved_versions_fills_a_missing_specification_only(
    declared_specification, declared_version, expected_specification
):
    venv = make_venv(
        libs=[
            make_library(
                name="pandas", specification=declared_specification, version=declared_version
            )
        ]
    )

    venv.apply_resolved_versions({"pandas": "2.2.3"})

    assert venv.libs[0].specification == expected_specification
    assert venv.libs[0].version == "2.2.3"


def test_venv_apply_resolved_versions_stamps_a_specification_the_version_satisfies():
    """The stamped default must not contradict the version it was built from, or the
    next edit of the row would be rejected by the library's own validator."""
    venv = make_venv(libs=[make_library(name="pandas", specification="")])

    venv.apply_resolved_versions({"pandas": "2.2.3"})

    assert Library(**venv.libs[0].model_dump()).version == "2.2.3"


def test_venv_apply_resolved_versions_matches_a_name_given_in_another_spelling():
    venv = make_venv(libs=[make_library(name="zope.interface", specification="")])

    venv.apply_resolved_versions({"zope-interface": "7.1"})

    assert venv.libs[0].version == "7.1"


def test_venv_apply_resolved_versions_leaves_an_unresolved_library_untouched():
    venv = make_venv(libs=[make_library(name="pandas", specification=">=2.0", version="2.1.0")])

    venv.apply_resolved_versions({})

    assert venv.libs[0].version == "2.1.0"


def test_venv_apply_resolved_versions_keeps_the_other_library_fields():
    venv = make_venv(
        libs=[make_library(name="pandas", specification=">=2.0", description="dataframes")]
    )

    venv.apply_resolved_versions({"pandas": "2.2.3"})

    assert venv.libs[0].description == "dataframes"
    assert venv.libs[0].specification == ">=2.0"


def test_venv_apply_resolved_versions_does_not_touch_the_build_status():
    venv = make_venv(status=VenvStatus.PROCESSING, libs=[make_library(name="pandas")])

    venv.apply_resolved_versions({"pandas": "2.2.3"})

    assert venv.status is VenvStatus.PROCESSING


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("pydantic", "pydantic"),
        ("Pydantic", "pydantic"),
        ("zope.interface", "zope-interface"),
    ],
)
def test_venv_rejects_the_same_library_declared_twice(first, second):
    with pytest.raises(ValidationError):
        make_venv(
            libs=[
                make_library(name=first, specification="==2.0"),
                make_library(name=second, specification="==2.1"),
            ]
        )


def test_venv_accepts_two_different_libraries():
    venv = make_venv(
        libs=[make_library(name="pydantic"), make_library(name="requests")]
    )

    assert [lib.name for lib in venv.libs] == ["pydantic", "requests"]


def test_venv_set_libs_rejects_a_repeated_library_too():
    venv = make_venv()

    with pytest.raises(ValidationError):
        venv.set_libs([make_library(name="pydantic"), make_library(name="pydantic")])


def test_a_library_is_an_ordinary_one_unless_it_says_otherwise():
    """Entries stored before this field existed read back as ordinary libraries."""
    assert make_library(name="requests").is_custom is False


def test_a_library_can_be_marked_as_one_this_installation_stores_itself():
    assert make_library(name="acme-core", is_custom=True).is_custom is True


def test_stamping_the_built_version_keeps_the_marking():
    """The build rebuilds the entry to record what it installed. Dropping the marking
    there would turn the library into a package index lookup on the next build."""
    library = make_library(name="acme-core", specification=">=1", is_custom=True)

    assert library.with_resolved_version("1.4.2").is_custom is True


def test_waiting_is_not_a_failure_and_drops_the_reason_for_an_earlier_one():
    """`declared` says nothing has happened yet; `waiting` says this service is still
    producing something the venv needs, and the user has nothing to fix."""
    venv = make_venv(name="data")
    venv.mark_as_failed(RuntimeError("the last attempt blew up"))

    venv.mark_as_waiting()

    assert venv.status is VenvStatus.WAITING
    assert venv.error is None


def test_a_venv_uses_only_the_libraries_it_marked_as_custom():
    """An entry naming the same thing without the marking is a package index lookup,
    and has nothing to do with the library stored here."""
    venv = make_venv(
        name="data",
        libs=[
            make_library(name="acme-core", specification=">=1", is_custom=True),
            make_library(name="requests"),
            make_library(name="shadow", specification=">=1"),
        ],
    )

    assert venv.uses_custom_library("acme-core") is True
    assert venv.uses_custom_library("requests") is False
    assert venv.uses_custom_library("shadow") is False
    assert venv.uses_custom_library("never-named") is False


def test_a_venv_pins_a_version_only_once_a_build_has_resolved_one():
    """Before the build there is a specification, which is a range, not a claim on one
    version: the build could still settle on a different one."""
    declared = make_venv(
        name="data",
        libs=[make_library(name="acme-core", specification=">=1", is_custom=True)],
    )
    built = make_venv(
        name="data",
        libs=[
            make_library(name="acme-core", specification=">=1", version="1.4.2", is_custom=True)
        ],
    )

    assert declared.pins_custom_library("acme-core", "1.4.2") is False
    assert built.pins_custom_library("acme-core", "1.4.2") is True
    assert built.pins_custom_library("acme-core", "2.0.0") is False


def test_an_ordinary_entry_pins_nothing_of_the_stored_library():
    """`requests==2.1.0` from the index says nothing about a stored library that
    happens to carry the same name and version."""
    venv = make_venv(
        name="data",
        libs=[make_library(name="acme-core", specification=">=1", version="1.4.2")],
    )

    assert venv.pins_custom_library("acme-core", "1.4.2") is False


def test_a_venv_with_no_libraries_uses_and_pins_nothing():
    venv = make_venv(name="data", libs=[])

    assert venv.uses_custom_library("acme-core") is False
    assert venv.pins_custom_library("acme-core", "1.4.2") is False
