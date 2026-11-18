"""A virtual environment as it travels in an import/export file.

The environment itself lives in the sandbox service and only its binding lives
here, so there is no model to serialize against. `libs` is carried in the shape
the sandbox's own create schema takes, which is what the import posts back to it.
No installed `version`: that field holds the author's pin and the build's own
result at once, so an export resolves a pin into `specification` instead.

What a venv name, a library name or a version specification may hold is the
sandbox's rule, so the values are checked here for shape only and passed on exactly
as the file writes them. A value the sandbox refuses fails the import with the
sandbox's message. That includes files of earlier releases that carry a version bound
in a library name (`numpy>=1`): the sandbox refuses a bound anywhere but in
`specification`, so such a file does not import until it is corrected.
"""

from rest_framework import serializers


class VenvLibraryImportSerializer(serializers.Serializer):
    """One library of an imported venv, checked for shape only.

    What a library name or a version specification may hold is the sandbox's rule, so
    the values are passed on exactly as the file writes them. The sandbox refuses a
    name it would not build, a version bound written into the name included, and the
    import then fails with its message.
    """

    # Not trimmed and not refused when blank: either would be a rule about the value.
    name = serializers.CharField(allow_blank=True, trim_whitespace=False)
    specification = serializers.CharField(
        required=False, allow_blank=True, default="", trim_whitespace=False
    )


class VenvImportSerializer(serializers.Serializer):
    name = serializers.CharField()
    libs = VenvLibraryImportSerializer(many=True)
