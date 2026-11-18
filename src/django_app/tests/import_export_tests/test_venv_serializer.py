"""What an import file may declare as a venv.

The sandbox owns what a venv name, a library name or a version specification may
hold, so they are checked here for shape only; that they reach the sandbox and its
refusal comes back to the user is pinned through the import endpoint.

Pure input-to-output: no database, no doubles.
"""

import pytest

from tables.import_export.serializers.venv import VenvImportSerializer


def venv(libs: list, name: str = "scraper-venv") -> dict:
    return {"name": name, "libs": libs}


def errors_for(data: dict) -> dict:
    serializer = VenvImportSerializer(data=data)
    assert not serializer.is_valid(), f"expected a refusal, got {serializer.validated_data}"
    return serializer.errors


class TestLibraryShape:
    def test_a_library_may_omit_its_specification(self):
        serializer = VenvImportSerializer(data=venv([{"name": "requests"}]))

        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["libs"] == [{"name": "requests", "specification": ""}]

    def test_an_environment_may_declare_no_libraries(self):
        assert VenvImportSerializer(data=venv([])).is_valid()

    @pytest.mark.parametrize(
        "libs",
        [
            [{"specification": ">=1"}],
            [{"name": None}],
            [{"name": "requests", "specification": None}],
            ["requests"],
            "requests",
        ],
        ids=["no-name", "null-name", "null-specification", "not-an-object", "not-a-list"],
    )
    def test_a_library_that_is_not_a_name_and_an_optional_specification(self, libs):
        assert "libs" in errors_for(venv(libs))


class TestEnvironmentShape:
    def test_an_environment_without_a_name(self):
        assert "name" in errors_for({"libs": []})

    @pytest.mark.parametrize("name", ["Tool #2-venv", "x" * 256])
    def test_a_name_is_passed_on_for_the_sandbox_to_judge(self, name):
        serializer = VenvImportSerializer(data=venv([], name=name))

        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["name"] == name
