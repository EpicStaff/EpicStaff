"""The order of plugin versions: SemVer 2.0 precedence, the same for EpicStaff and for plugins.

A plugin's `version` is a SemVer 2.0 version (`contracts.manifest.SEMVER_PATTERN`). EpicStaff
accepts a package of an installed plugin only when its version is newer than the latest
approved one, and an upgrade hook compares the organization's `previous_version` with the
version that changed what the hook sets up:

    from epicstaff_plugin.versions import is_newer

    if request.previous_version is None or is_newer("0.7.0", request.previous_version):
        ...

Precedence is section 11 of SemVer 2.0:

- major, minor and patch compare as numbers, so `0.10.0` is newer than `0.9.9`;
- a pre-release is older than its release: `1.0.0-alpha < 1.0.0-alpha.1 < 1.0.0-beta < 1.0.0`;
- pre-release identifiers compare one by one: digits only as numbers, anything else in ASCII
  order, and a number before a word; when one list of identifiers starts the other, the
  shorter is older;
- build metadata (`+...`) is ignored, so `0.7.0+2` and `0.7.0` are the same version, and
  neither is newer than the other.
"""

import re

from epicstaff_plugin.contracts.manifest import SEMVER_PATTERN

type PreReleaseIdentifierKey = tuple[int, int] | tuple[int, str]
type VersionKey = tuple[int, int, int, int, tuple[PreReleaseIdentifierKey, ...]]
"""What `version_key` returns: compare keys only with each other, never take them apart."""

_SEMVER = re.compile(SEMVER_PATTERN)
# A release sorts after every pre-release of the same major, minor and patch.
_PRE_RELEASE, _RELEASE = 0, 1
# A numeric pre-release identifier sorts before an alphanumeric one.
_NUMERIC, _ALPHANUMERIC = 0, 1


def version_key(version: str) -> VersionKey:
    """Return a key that sorts versions in SemVer 2.0 precedence.

    Two versions have equal keys exactly when they differ at most in build metadata, so
    `sorted(versions, key=version_key)` orders them oldest first.

    Raises:
        ValueError: `version` is not a SemVer 2.0 version.
    """
    # fullmatch, not match: `$` would also match before a trailing newline.
    match = _SEMVER.fullmatch(version) if isinstance(version, str) else None
    if match is None:
        raise ValueError(f"{version!r} is not a SemVer 2.0 version")
    major, minor, patch, pre_release, _build_metadata = match.groups()
    if pre_release is None:
        return (int(major), int(minor), int(patch), _RELEASE, ())
    identifiers = tuple(_identifier_key(identifier) for identifier in pre_release.split("."))
    return (int(major), int(minor), int(patch), _PRE_RELEASE, identifiers)


def compare_versions(left: str, right: str) -> int:
    """Return -1 when `left` is older than `right`, 0 when it is the same version, 1 when newer.

    Raises:
        ValueError: `left` or `right` is not a SemVer 2.0 version.
    """
    left_key, right_key = version_key(left), version_key(right)
    return (left_key > right_key) - (left_key < right_key)


def is_newer(candidate: str, than: str) -> bool:
    """Return whether `candidate` is a newer version than `than`.

    A version that differs from `than` only in build metadata is not newer.

    Raises:
        ValueError: `candidate` or `than` is not a SemVer 2.0 version.
    """
    return version_key(candidate) > version_key(than)


def _identifier_key(identifier: str) -> PreReleaseIdentifierKey:
    # The pattern allows ASCII only, so isdigit() means the digits 0-9.
    if identifier.isdigit():
        return (_NUMERIC, int(identifier))
    return (_ALPHANUMERIC, identifier)
