import random

import pytest
from pydantic import TypeAdapter, ValidationError

import epicstaff_plugin.versions
from epicstaff_plugin.contracts import versions
from epicstaff_plugin.contracts.manifest import Version
from epicstaff_plugin.contracts.versions import compare_versions, is_newer, version_key

# SemVer 2.0, section 11, oldest first.
SEMVER_EXAMPLES = [
    "1.0.0-alpha",
    "1.0.0-alpha.1",
    "1.0.0-alpha.beta",
    "1.0.0-beta",
    "1.0.0-beta.2",
    "1.0.0-beta.11",
    "1.0.0-rc.1",
    "1.0.0",
    "2.0.0",
    "2.1.0",
    "2.1.1",
]
# Text that is not a SemVer 2.0 version, and values that are not text.
NOT_SEMVER = [
    "",
    "1",
    "1.0",
    "1.0.0.0",
    "01.0.0",
    "1.00.0",
    "1.0.00",
    "1.0.0-01",
    "1.0.0-",
    "1.0.0+",
    "1.0.0-alpha..1",
    "1.0.0-al pha",
    "1.0.0+build+2",
    "v1.0.0",
    " 1.0.0",
    "1.0.0 ",
    "1.0.0\n",
    "-1.0.0",
    "١.0.0",
    "1.0.0-β",
    "1.0.0-alpha_1",
    None,
    100,
    b"1.0.0",
]


def test_the_semver_examples_sort_in_their_order():
    shuffled = SEMVER_EXAMPLES[:]
    random.Random(7).shuffle(shuffled)

    assert sorted(shuffled, key=version_key) == SEMVER_EXAMPLES


@pytest.mark.parametrize(
    ("older", "newer"),
    list(zip(SEMVER_EXAMPLES, SEMVER_EXAMPLES[1:], strict=False)),
)
def test_each_example_is_newer_than_the_one_before(older, newer):
    assert is_newer(newer, older)
    assert not is_newer(older, newer)
    assert compare_versions(older, newer) == -1
    assert compare_versions(newer, older) == 1


@pytest.mark.parametrize(
    ("older", "newer"),
    [
        ("0.9.9", "0.10.0"),
        ("1.9.0", "1.10.0"),
        ("1.0.9", "1.0.10"),
        ("0.6.0", "0.7.0"),
        ("0.7.0", "0.7.1"),
        ("18446744073709551615.0.0", "18446744073709551616.0.0"),
    ],
)
def test_major_minor_and_patch_compare_as_numbers(older, newer):
    assert is_newer(newer, older)
    assert not is_newer(older, newer)


@pytest.mark.parametrize(
    ("older", "newer"),
    [
        ("1.0.0-beta.2", "1.0.0-beta.11"),
        ("1.0.0-999", "1.0.0-0a"),
        ("1.0.0-1", "1.0.0-alpha"),
        ("1.0.0-alpha.1", "1.0.0-alpha.a"),
        ("1.0.0-Alpha", "1.0.0-alpha"),
        ("1.0.0-a-b", "1.0.0-a0"),
        ("1.0.0-alpha", "1.0.0-alpha-1"),
        ("1.0.0-rc.1", "1.0.0-rc.1.0"),
        ("0.7.0-rc.1", "0.7.0"),
        ("0.6.0", "0.7.0-rc.1"),
    ],
    ids=[
        "digits as numbers",
        "a digit-led word is a word",
        "a number before a word",
        "a number before a word, later on",
        "words in ASCII order",
        "hyphen before digits",
        "a word before a longer word",
        "fewer identifiers first",
        "a pre-release before its release",
        "a pre-release after the release before",
    ],
)
def test_pre_release_identifiers_compare_one_by_one(older, newer):
    assert compare_versions(older, newer) == -1
    assert compare_versions(newer, older) == 1


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("0.7.0+2", "0.7.0"),
        ("0.7.0+build.5", "0.7.0+build.6"),
        ("1.0.0-rc.1+exp.sha.5114f85", "1.0.0-rc.1"),
        ("1.0.0", "1.0.0"),
    ],
)
def test_build_metadata_is_ignored(left, right):
    assert compare_versions(left, right) == 0
    assert version_key(left) == version_key(right)
    assert not is_newer(left, right)
    assert not is_newer(right, left)


def test_a_newer_version_is_newer_whatever_the_build_metadata_says():
    assert is_newer("0.7.1", "0.7.0+999")
    assert not is_newer("0.7.0+999", "0.7.1")


@pytest.mark.parametrize("text", NOT_SEMVER)
def test_text_that_is_not_semver_is_refused(text):
    with pytest.raises(ValueError, match="is not a SemVer 2.0 version"):
        version_key(text)
    with pytest.raises(ValueError, match="is not a SemVer 2.0 version"):
        compare_versions("1.0.0", text)
    with pytest.raises(ValueError, match="is not a SemVer 2.0 version"):
        is_newer(text, "1.0.0")


def test_the_order_takes_exactly_the_versions_a_manifest_takes():
    manifest_version = TypeAdapter(Version)
    for text in [*SEMVER_EXAMPLES, "0.7.0+2", "1.0.0-rc.1+exp.sha.5114f85"]:
        assert manifest_version.validate_python(text) == text
        version_key(text)
    for text in NOT_SEMVER:
        if isinstance(text, str):
            with pytest.raises(ValidationError):
                manifest_version.validate_python(text)


def test_plugins_import_the_same_functions_from_epicstaff_plugin_versions():
    assert epicstaff_plugin.versions.version_key is versions.version_key
    assert epicstaff_plugin.versions.compare_versions is versions.compare_versions
    assert epicstaff_plugin.versions.is_newer is versions.is_newer
    assert set(epicstaff_plugin.versions.__all__) == {"VersionKey", "compare_versions", "is_newer", "version_key"}
