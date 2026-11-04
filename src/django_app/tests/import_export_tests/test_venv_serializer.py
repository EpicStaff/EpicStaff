"""What an import file may declare as a library.

An import file is untrusted input and the sandbox installs every entry it carries,
so this is a trust boundary. The rule used to live on `PythonCode.libraries`; it
moved here with the libraries themselves.

Pure input-to-output: no database, no doubles.
"""

import pytest

from tables.import_export.serializers.venv import VenvImportSerializer


def venv(libs: list[dict], name: str = "scraper-venv") -> dict:
    return {"name": name, "libs": libs}


def errors_for(data: dict) -> dict:
    serializer = VenvImportSerializer(data=data)
    assert not serializer.is_valid(), f"expected a refusal, got {serializer.validated_data}"
    return serializer.errors


class TestAcceptedLibraries:
    @pytest.mark.parametrize(
        "specification",
        ["", "==2.31.0", ">=2,<3", "~=1.4", "!=1.2,>=1.0"],
        ids=["none", "pinned", "range", "compatible", "excluded"],
    )
    def test_a_named_requirement_with_a_specifier_set(self, specification):
        serializer = VenvImportSerializer(data=venv([{"name": "requests", "specification": specification}]))

        assert serializer.is_valid(), serializer.errors

    def test_a_library_may_omit_its_specification(self):
        serializer = VenvImportSerializer(data=venv([{"name": "requests"}]))

        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["libs"] == [{"name": "requests", "specification": ""}]

    def test_an_environment_may_declare_no_libraries(self):
        assert VenvImportSerializer(data=venv([])).is_valid()


class TestRefusedLibraries:
    @pytest.mark.parametrize(
        "name",
        [
            "/proc/self",
            "/",
            "file:///etc",
            "../../etc/passwd",
            "requests @ https://evil.example.com/a.whl",
            "git+https://example.com/repo.git",
            "",
        ],
        ids=["path", "root", "file-url", "traversal", "direct-reference", "vcs-url", "empty"],
    )
    def test_anything_that_is_not_a_plain_package_name(self, name):
        """pip would read these as a path or a URL, which is a way out of the index."""
        assert "libs" in errors_for(venv([{"name": name}]))

    def test_a_specifier_set_the_resolver_cannot_read(self):
        """Checked apart from the name: concatenated, `httpx` + `nonsense` parses as
        a package called `httpxnonsense` and reaches the sandbox as one."""
        assert "libs" in errors_for(venv([{"name": "httpx", "specification": "nonsense"}]))

    @pytest.mark.parametrize(
        "specification",
        ["==1.0\nmalicious-pkg", ">= 2"],
        ids=["newline-injection", "inner-space"],
    )
    def test_whitespace_inside_a_specification(self, specification):
        """The sandbox feeds the requirements to `uv pip compile` on stdin, one per
        line, so a newline here would smuggle in a second requirement."""
        assert "libs" in errors_for(venv([{"name": "httpx", "specification": specification}]))

    def test_an_environment_without_a_name(self):
        assert "name" in errors_for({"libs": []})

    def test_an_environment_with_a_blank_name(self):
        assert "name" in errors_for(venv([], name=""))


class TestEnvironmentName:
    """The sandbox refuses any other name, and it would do so mid-import, after
    earlier environments of the same file were already created upstream."""

    @pytest.mark.parametrize("name", ["Tool #2-venv", "Інструмент", "x" * 256])
    def test_a_name_the_sandbox_would_refuse(self, name):
        assert "name" in errors_for(venv([], name=name))

    @pytest.mark.parametrize("name", ["My_tool 2-venv", "x" * 255])
    def test_letters_digits_spaces_underscores_and_hyphens(self, name):
        serializer = VenvImportSerializer(data=venv([], name=name))

        assert serializer.is_valid(), serializer.errors
