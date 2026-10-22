"""A virtual environment as it travels in an import/export file.

The environment itself lives in the sandbox service and only its binding lives
here, so there is no model to serialize against. `libs` is carried in the shape
the sandbox's own create schema takes, which is what the import posts back to it.
No installed `version`: that field holds the author's pin and the build's own
result at once, so an export resolves a pin into `specification` instead.
"""

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from rest_framework import serializers

from tables.validators.python_libraries_validator import validate_python_library_spec


class VenvLibraryImportSerializer(serializers.Serializer):
    name = serializers.CharField()
    specification = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_name(self, value: str) -> str:
        """Reject a name pip would read as a path or a URL.

        An import file is untrusted input and the sandbox runs `pip install` on
        every entry, so the same rule a library declared through the API passes
        applies here.

        Raises:
            serializers.ValidationError: The name is not a plain named requirement.
        """
        validate_python_library_spec(value)
        return value

    def validate_specification(self, value: str) -> str:
        """Reject a specifier set the resolver could not read, or one with whitespace.

        Checked apart from the name rather than as one token: concatenated, a
        nonsense specifier parses as part of the package name and reaches the
        sandbox as a package that does not exist.

        Whitespace is refused because the sandbox feeds the requirements to
        `uv pip compile` on stdin, one per line: a newline here would split the
        entry and smuggle in a second requirement.

        Raises:
            serializers.ValidationError: The value is not a PEP 440 specifier set,
                or it contains whitespace.
        """
        if not value:
            return value
        if any(character.isspace() for character in value):
            raise serializers.ValidationError(
                f"Version specification '{value}' must not contain whitespace. "
                "Write it as a single token, for example '>=2,<3'."
            )
        try:
            SpecifierSet(value)
        except InvalidSpecifier as error:
            raise serializers.ValidationError(
                f"'{value}' is not a valid version specification: {error}."
            ) from error
        return value


class VenvImportSerializer(serializers.Serializer):
    name = serializers.CharField()
    libs = VenvLibraryImportSerializer(many=True)
