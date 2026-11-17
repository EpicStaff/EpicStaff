from rest_framework import serializers
from tables.validators.python_libraries_validator import validate_python_library_name


class VenvLibraryWriteSerializer(serializers.Serializer):
    # Not trimmed: the body is forwarded as sent, so what is checked has to be exactly
    # what the sandbox receives, trailing line break included.
    name = serializers.CharField(trim_whitespace=False, validators=[validate_python_library_name])
    is_custom = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs: dict) -> dict:
        """Refuse extras on a stored library, as the sandbox does.

        A stored library is looked up, guarded against deletion and pinned by its bare
        name, so `acme[extra]` would name a library nothing stores, and the check that
        it is this organization's own would be asked about the wrong name.

        Raises:
            serializers.ValidationError: A custom library carries extras.
        """
        bare_name = attrs["name"].partition("[")[0]
        if attrs["is_custom"] and bare_name != attrs["name"]:
            raise serializers.ValidationError(
                f"Custom library {attrs['name']!r} cannot take extras; declare it as {bare_name!r}."
            )
        return attrs


class VenvWriteSerializer(serializers.Serializer):
    """The part of a venv write this side checks before forwarding the body untouched.

    Only the library entries: their names reach `uv pip compile` as requirement lines,
    and a refusal here names the offending entry under `libs` instead of surfacing as
    an upstream error. Every other field is the sandbox's to validate.
    """

    libs = VenvLibraryWriteSerializer(many=True, required=False, allow_null=True)
