import re

from rest_framework import serializers

_DISTRIBUTION_NAME = r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?"
# The sandbox's own rule for a venv library name, kept identical to it: a distribution
# name, optionally followed by extras that are distribution names themselves. Only
# ever used with `fullmatch`; `$` would also match before a trailing newline.
_LIBRARY_NAME_RE = re.compile(
    rf"{_DISTRIBUTION_NAME}(?:\[{_DISTRIBUTION_NAME}(?:,{_DISTRIBUTION_NAME})*\])?"
)


def validate_python_library_name(value: str) -> None:
    """Accept only a distribution name with optional extras, the way the sandbox stores one.

    The sandbox writes each library as one line of the requirements `uv pip compile`
    reads on stdin, so a name carrying a line break, a leading `-`, a path or a URL
    would add a requirement, an index or a local project of the caller's choosing.
    Markers and version specifiers are refused as well: the version goes in the
    library's own `specification`, and the sandbox refuses the rest the same way.

    A regex rather than `packaging`'s name validation: how strict that is differs
    between packaging releases, and this side and the sandbox pin different ones.

    Raises:
        serializers.ValidationError: The value is not a distribution name with
            optional extras.
    """
    if _LIBRARY_NAME_RE.fullmatch(value) is None:
        raise serializers.ValidationError(
            f"Library name {value!r} is not a package name. Use letters, digits and "
            "'.', '_' or '-' between them, optionally followed by extras in brackets, "
            "for example 'requests' or 'requests[socks,security]'; put a version in "
            "the specification."
        )
