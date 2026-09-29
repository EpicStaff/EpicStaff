"""`PythonCodeSerializer.libraries` accepts only plain PEP 508 requirements.

Every entry is handed to `pip install` inside the sandbox, so a path, a
`file://` URL, a VCS URL or a direct `name @ url` reference must never reach
storage.
"""

import pytest
from rest_framework import serializers

from tables.models.python_models import PythonCode
from tables.serializers.model_serializers.python_serializers import PythonCodeSerializer
from tables.validators.python_libraries_validator import validate_python_library_spec

REJECTED_ENTRIES = [
    "/proc/self",
    "/",
    "/etc/passwd",
    "./local-package",
    "..",
    "file:///etc",
    "file:///proc/self/environ",
    "git+https://github.com/psf/requests",
    "hg+https://example.com/repo",
    "name @ https://example.com/evil.whl",
    "requests @ file:///etc/passwd",
    "-r requirements.txt",
    "--index-url=http://evil.example.com/simple",
    "",
    "   ",
]

ACCEPTED_ENTRIES = [
    "requests",
    "requests==2.31.0",
    "requests>=2,<3",
    "requests[security]>=2.0",
    "python-dateutil~=2.8",
    "Django!=5.0.1",
]


def _payload(libraries: list[str]) -> dict:
    return {
        "code": "def main(**kwargs):\n    return 1\n",
        "entrypoint": "main",
        "libraries": libraries,
        "global_kwargs": {},
    }


class TestValidatePythonLibrarySpec:
    @pytest.mark.parametrize("entry", REJECTED_ENTRIES)
    def test_rejects_anything_that_is_not_a_named_requirement(self, entry):
        with pytest.raises(serializers.ValidationError):
            validate_python_library_spec(entry)

    @pytest.mark.parametrize("entry", ACCEPTED_ENTRIES)
    def test_accepts_standard_pip_requirement_specs(self, entry):
        assert validate_python_library_spec(entry) is None

    def test_rejects_inner_whitespace_because_storage_is_space_separated(self):
        with pytest.raises(serializers.ValidationError) as error:
            validate_python_library_spec("requests >= 2")

        assert "whitespace" in str(error.value)

    def test_the_error_names_the_offending_entry(self):
        with pytest.raises(serializers.ValidationError) as error:
            validate_python_library_spec("/proc/self")

        assert "/proc/self" in str(error.value)


@pytest.mark.django_db
class TestPythonCodeSerializerLibraries:
    @pytest.mark.parametrize("entry", ["/proc/self", "/", "file:///etc", "name @ https://x.io/a"])
    def test_serializer_rejects_the_entry(self, entry):
        serializer = PythonCodeSerializer(data=_payload([entry]))

        assert not serializer.is_valid()
        assert "libraries" in serializer.errors

    def test_one_bad_entry_rejects_the_whole_list(self):
        serializer = PythonCodeSerializer(data=_payload(["requests", "/proc/self"]))

        assert not serializer.is_valid()
        assert "libraries" in serializer.errors

    def test_valid_specs_are_accepted_and_stored_space_separated(self):
        serializer = PythonCodeSerializer(data=_payload(["requests==2.31.0", "numpy>=1,<2"]))

        assert serializer.is_valid(), serializer.errors
        python_code = serializer.save()

        python_code.refresh_from_db()
        assert python_code.libraries == "requests==2.31.0 numpy>=1,<2"
        assert python_code.get_libraries_list() == ["requests==2.31.0", "numpy>=1,<2"]

    def test_empty_list_is_accepted(self):
        serializer = PythonCodeSerializer(data=_payload([]))

        assert serializer.is_valid(), serializer.errors
        assert serializer.save().libraries == ""

    def test_existing_records_with_unvalidated_libraries_are_still_readable(self):
        """No retroactive validation: reading a stored row never re-validates."""
        python_code = PythonCode.objects.create(
            code="def main(**kwargs):\n    return 1\n",
            entrypoint="main",
            libraries="/proc/self requests",
        )

        representation = PythonCodeSerializer(python_code).data

        assert representation["libraries"] == ["/proc/self", "requests"]
