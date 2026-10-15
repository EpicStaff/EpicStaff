from packaging.requirements import InvalidRequirement, Requirement
from rest_framework import serializers


def validate_python_library_spec(value: str) -> None:
    """Accept only a plain PEP 508 requirement, as pip would receive it.

    Each entry is installed by the sandbox with `pip install`, so a path, a
    `file://` URL, a VCS URL or a direct `name @ url` reference would let a
    caller reach the sandbox filesystem or an arbitrary host. Only a named
    requirement with optional extras and version specifiers passes.

    Raises:
        serializers.ValidationError: The entry is not a named requirement, or
            carries a direct URL reference, or contains whitespace.
    """
    entry = value.strip()
    if not entry:
        raise serializers.ValidationError("Library entry must not be empty.")

    # PythonCode.libraries is stored space-separated, so an entry with inner
    # whitespace (markers, spaced specifiers) would be split into broken parts.
    if any(character.isspace() for character in entry):
        raise serializers.ValidationError(
            f"Library '{entry}' must not contain whitespace. "
            "Write it as a single token, for example 'requests>=2,<3'."
        )

    try:
        requirement = Requirement(entry)
    except InvalidRequirement as error:
        raise serializers.ValidationError(
            f"Library '{entry}' is not a valid pip requirement: {error}. "
            "Use a package name with optional extras and version specifiers, "
            "for example 'requests', 'requests==2.31.0' or 'requests>=2,<3'."
        ) from error

    if requirement.url is not None:
        raise serializers.ValidationError(
            f"Library '{entry}' points at a URL or path. Only packages from the "
            "package index are allowed; direct references, file paths, "
            "'file://' and VCS URLs are not."
        )
