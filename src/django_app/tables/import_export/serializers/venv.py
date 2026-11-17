"""A virtual environment as it travels in an import/export file.

The environment itself lives in the sandbox service and only its binding lives
here, so there is no model to serialize against. `libs` is carried in the shape
the sandbox's own create schema takes, which is what the import posts back to it.
No installed `version`: that field holds the author's pin and the build's own
result at once, so an export resolves a pin into `specification` instead.
"""

from collections.abc import Mapping

from django.core.validators import RegexValidator
from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from rest_framework import serializers

from tables.import_export.constants import VENV_NAME_MAX_LENGTH, VENV_NAME_PATTERN
from tables.validators.python_libraries_validator import validate_python_library_name

# A version bound starts at the first of these: a package name, extras included, holds none.
_VERSION_BOUND_START = frozenset("<>=!~(")


def split_version_bound_from_name(name: str, specification: str) -> tuple[str, str]:
    """Move a version bound written into a library name over to its specification.

    Released versions accepted a library named `numpy>=1` or `requests[socks]>=2`,
    and the sandbox stored it verbatim, so export files from those releases and
    venvs created by them still carry the bound in the name. The name is now held to
    a package name with optional extras, so such an entry is rewritten into name
    `requests[socks]` plus specification `>=2` instead of being refused.

    Only an entry that is unambiguously a plain named requirement is rewritten: one
    that parses as a requirement with a version specifier, has no URL, no marker and
    no whitespace, and has no specification of its own -- with both set, it is not
    clear which bound the author meant. Anything else is returned unchanged, for the
    usual name and specification checks to refuse.
    """
    if specification or any(character.isspace() for character in name):
        return name, specification
    try:
        requirement = Requirement(name)
    except InvalidRequirement:
        return name, specification
    if requirement.url is not None or requirement.marker is not None or not requirement.specifier:
        return name, specification
    bound_start = next(
        index for index, character in enumerate(name) if character in _VERSION_BOUND_START
    )
    bound = name[bound_start:]
    # PEP 508 allows the bound in parentheses, `numpy(>=1)`; the parsed requirement
    # guarantees the closing one. Sliced rather than rebuilt from the parsed
    # specifier, which reorders the clauses the author wrote.
    if bound.startswith("("):
        bound = bound[1:-1]
    return name[:bound_start], bound


class VenvLibraryImportSerializer(serializers.Serializer):
    name = serializers.CharField()
    specification = serializers.CharField(required=False, allow_blank=True, default="")

    def to_internal_value(self, data):
        """Read an entry, first splitting a version bound an older export left in its name.

        Both fields are trimmed before the split, as the fields themselves trim them
        afterwards, so `numpy>=1` with a trailing newline or space is split like
        `numpy>=1`, and an entry reads the same here as in `VenvStrategy._library_key`.
        """
        if isinstance(data, Mapping) and isinstance(data.get("name"), str):
            specification = data.get("specification")
            if isinstance(specification, str):
                specification = specification.strip()
            name, split_specification = split_version_bound_from_name(
                data["name"].strip(), specification or ""
            )
            data = {**data, "name": name}
            if split_specification:
                data["specification"] = split_specification
        return super().to_internal_value(data)

    def validate_name(self, value: str) -> str:
        """Reject anything but a package name with optional extras.

        An import file is untrusted input and the sandbox installs every entry, so
        the same rule a library declared through the API passes applies here.

        Raises:
            serializers.ValidationError: The name is not a package name with optional extras.
        """
        validate_python_library_name(value)
        return value

    def validate_specification(self, value: str) -> str:
        """Reject a specifier set the resolver could not read, or one not on one line.

        Checked apart from the name rather than as one token: concatenated, a
        nonsense specifier parses as part of the package name and reaches the
        sandbox as a package that does not exist.

        A plain space is allowed, as in `>=1.0, <2`: the sandbox accepts it too, and
        `SpecifierSet` reads it as padding. Every other whitespace character is
        refused, the sandbox's own rule: the sandbox feeds the requirements to
        `uv pip compile` on stdin, one per line, and `SpecifierSet` would read a line
        break as padding as well, so it would split the entry and smuggle in a
        second requirement.

        Raises:
            serializers.ValidationError: The value is not a PEP 440 specifier set,
                or it holds whitespace other than a plain space.
        """
        if not value:
            return value
        if any(character.isspace() and character != " " for character in value):
            raise serializers.ValidationError(
                f"Version specification {value!r} must be on one line, with no tabs "
                "or other whitespace than a plain space, for example '>=2, <3'."
            )
        try:
            SpecifierSet(value)
        except InvalidSpecifier as error:
            raise serializers.ValidationError(
                f"'{value}' is not a valid version specification: {error}."
            ) from error
        return value


class VenvImportSerializer(serializers.Serializer):
    # The sandbox's rule, checked here as well: a refused name becomes a 400 on this
    # field instead of an upstream error, the length the sandbox only enforces at its
    # column is caught before it, and converter output can be tested against it.
    name = serializers.CharField(
        max_length=VENV_NAME_MAX_LENGTH,
        validators=[
            RegexValidator(
                VENV_NAME_PATTERN,
                "A venv name may only hold letters, digits, spaces, underscores and hyphens.",
            )
        ],
    )
    libs = VenvLibraryImportSerializer(many=True)
