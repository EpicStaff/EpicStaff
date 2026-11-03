"""Behavior of the custom library model.

Its one rule is its name. Everything built on top assumes two things about it: that one
distribution cannot be stored under two spellings, and that the stored spelling is the
one a wheel filename parses to -- the uniqueness check, the delete-and-reupload cycle
and the name match on every upload all compare canonical names.
"""

import pytest
from packaging.utils import parse_wheel_filename
from pydantic import ValidationError

from manager.domain.models import CustomLibrary

# Spellings a package index treats as one name, and the one it settles on.
EQUIVALENT_SPELLINGS = [
    ("my-library", "my-library"),
    ("My_Library", "my-library"),
    ("MY.LIBRARY", "my-library"),
    ("my..lib", "my-lib"),
    ("zope.interface", "zope-interface"),
    ("a", "a"),
    ("pkg1", "pkg1"),
]

NOT_DISTRIBUTION_NAMES = ["", "my lib", "-leading", "trailing-", "_under", "lib/../etc", "péché"]


@pytest.mark.parametrize(("written", "stored"), EQUIVALENT_SPELLINGS)
def test_a_name_is_stored_as_a_package_index_would_write_it(written, stored):
    assert CustomLibrary(name=written).name == stored


@pytest.mark.parametrize("name", NOT_DISTRIBUTION_NAMES)
def test_a_name_that_no_distribution_could_have_is_refused(name):
    """Refused rather than stored: a name no wheel can carry makes a library that
    nothing can ever be uploaded to, because every upload is matched against it."""
    with pytest.raises(ValidationError):
        CustomLibrary(name=name)


@pytest.mark.parametrize(("written", "stored"), EQUIVALENT_SPELLINGS)
def test_a_rename_is_held_to_the_same_spelling_rule(written, stored):
    library = CustomLibrary(name="before")
    library.rename(written)
    assert library.name == stored


@pytest.mark.parametrize("name", NOT_DISTRIBUTION_NAMES)
def test_a_rename_to_a_name_no_distribution_could_have_is_refused(name):
    library = CustomLibrary(name="before")
    with pytest.raises(ValidationError):
        library.rename(name)
    assert library.name == "before"


@pytest.mark.parametrize(("written", "stored"), EQUIVALENT_SPELLINGS)
def test_a_stored_name_is_what_a_wheel_filename_parses_to(written, stored):
    """The point of the rule above: an upload is accepted by comparing the stored name
    with the name inside the wheel, so a name that cannot come out of a wheel filename
    would be a library nothing matches."""
    wheel = f"{stored.replace('-', '_')}-1.0.0-py3-none-any.whl"
    parsed, _, _, _ = parse_wheel_filename(wheel)

    assert parsed == CustomLibrary(name=written).name
