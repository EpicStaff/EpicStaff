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
        ["", "==2.31.0", ">=2,<3", "~=1.4", "!=1.2,>=1.0", ">=1.0, <2", ">= 2"],
        ids=[
            "none",
            "pinned",
            "range",
            "compatible",
            "excluded",
            "space-after-the-comma",
            "space-after-the-operator",
        ],
    )
    def test_a_named_requirement_with_a_specifier_set(self, specification):
        serializer = VenvImportSerializer(data=venv([{"name": "requests", "specification": specification}]))

        assert serializer.is_valid(), serializer.errors

    @pytest.mark.parametrize(
        "name",
        [
            "requests",
            "Requests_Toolbelt",
            "zope.interface",
            "a",
            "requests[socks]",
            "requests[socks,security]",
        ],
    )
    def test_a_distribution_name_with_optional_extras_however_it_is_spelled(self, name):
        assert VenvImportSerializer(data=venv([{"name": name}])).is_valid()

    def test_a_library_may_omit_its_specification(self):
        serializer = VenvImportSerializer(data=venv([{"name": "requests"}]))

        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["libs"] == [{"name": "requests", "specification": ""}]

    def test_an_environment_may_declare_no_libraries(self):
        assert VenvImportSerializer(data=venv([])).is_valid()


class TestVersionBoundInAnOlderExportsName:
    """Released versions accepted `numpy>=1` as a library name, so their export files
    carry it; the import moves the bound to the specification instead of refusing."""

    @pytest.mark.parametrize(
        ("name", "expected_name", "expected_specification"),
        [
            ("numpy>=1", "numpy", ">=1"),
            ("requests>=2", "requests", ">=2"),
            ("pydantic>=2,<3", "pydantic", ">=2,<3"),
            ("requests==2.31.0", "requests", "==2.31.0"),
            ("requests[socks]>=2", "requests[socks]", ">=2"),
            ("numpy(>=1)", "numpy", ">=1"),
            ("a[x](>=1,<2)", "a[x]", ">=1,<2"),
            ("numpy>=1\n", "numpy", ">=1"),
            ("numpy>=1 ", "numpy", ">=1"),
            (" numpy>=1", "numpy", ">=1"),
        ],
        ids=[
            "lower",
            "lower-other-name",
            "both",
            "pinned",
            "extras",
            "parenthesised",
            "parenthesised-extras-both",
            "trailing-newline",
            "trailing-space",
            "leading-space",
        ],
    )
    @pytest.mark.parametrize(
        "entry",
        [{}, {"specification": ""}, {"specification": " "}, {"specification": "\n"}],
        ids=["omitted", "blank", "space", "newline"],
    )
    def test_is_split_into_name_and_specification(
        self, name, expected_name, expected_specification, entry
    ):
        serializer = VenvImportSerializer(data=venv([{"name": name, **entry}]))

        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["libs"] == [
            {"name": expected_name, "specification": expected_specification}
        ]

    def test_next_to_a_specification_of_its_own_is_refused(self):
        """Two bounds for one library: which one the author meant is not for the
        import to guess."""
        assert "libs" in errors_for(venv([{"name": "numpy>=1", "specification": "<2"}]))

    @pytest.mark.parametrize(
        "name",
        [
            "numpy>=1\n-i http://internal-host:9/simple",
            "numpy>=1,<2\n-r /etc/passwd",
            "numpy>=1\r-e /etc",
            "numpy>=1 --index-url http://evil",
            "numpy >=1",
            "numpy>=1;python_version<'3'",
            "numpy>=1; python_version<'3'",
            "numpy>=1@file:///etc",
            "-e numpy>=1",
            "requests[]>=2",
            "requests[ socks]>=2",
            "numpy>=nonsense",
        ],
        ids=[
            "newline-index-option",
            "newline-requirements-file",
            "carriage-return-editable",
            "trailing-option",
            "space-before-the-bound",
            "marker",
            "spaced-marker",
            "url",
            "leading-option",
            "empty-extras",
            "space-inside-extras",
            "unreadable-bound",
        ],
    )
    def test_that_does_not_split_cleanly_is_refused(self, name):
        assert "libs" in errors_for(venv([{"name": name}]))


class TestRefusedLibraries:
    # The sandbox's own table of refused names, from its domain tests of `Library`,
    # copied whole: both sides hold a name to the same grammar, and a row one side
    # accepts and the other refuses breaks here visibly. Five of its rows are not
    # refused by an import, each covered by a test of its own: surrounding whitespace
    # is trimmed off (`requests\n`, `requests `, `requests[socks]\n`), and a bound in
    # the name is split off for older export files (`requests>=2`, `requests[socks]>=2`).
    @pytest.mark.parametrize(
        "name",
        [
            pytest.param("six\n-i http://internal-host:9/simple", id="newline-index-option"),
            pytest.param("six\n-r /etc/passwd", id="newline-requirements-file"),
            pytest.param(
                "requests\n--index-url https://evil.example/simple", id="newline-long-option"
            ),
            pytest.param("requests\r-e /etc", id="carriage-return-editable"),
            pytest.param("-e /etc", id="editable-option"),
            pytest.param("-r", id="bare-option"),
            pytest.param("/etc", id="absolute-path"),
            pytest.param("./local/path", id="relative-path"),
            pytest.param("foo @ file:///etc", id="direct-reference"),
            pytest.param("git+https://example.com/repo.git", id="vcs-url"),
            pytest.param("requests; python_version<'3'", id="marker"),
            pytest.param("-requests", id="leading-hyphen"),
            pytest.param("requests-", id="trailing-hyphen"),
            pytest.param("requests[socks]\n-i x", id="extras-then-newline-option"),
            pytest.param("requests[ socks]", id="space-inside-extras"),
            pytest.param("requests[socks];python_version<'3'", id="extras-then-marker"),
            pytest.param("requests[]", id="empty-extras"),
            pytest.param("requests[socks,]", id="trailing-comma-in-extras"),
            pytest.param("requests[socks", id="unclosed-extras"),
            pytest.param("requests[-e]", id="option-as-extra"),
            pytest.param("[socks]", id="extras-without-a-name"),
            # Refused by the import alone: earlier rules let these through to pip.
            pytest.param("/proc/self", id="proc-path"),
            pytest.param("/", id="root"),
            pytest.param("file:///etc", id="file-url"),
            pytest.param("../../etc/passwd", id="traversal"),
            pytest.param("requests @ https://evil.example.com/a.whl", id="remote-reference"),
            pytest.param("", id="empty"),
        ],
    )
    def test_anything_that_is_not_a_plain_package_name(self, name):
        """uv would read these as a path, a URL, an option or a second requirement,
        which is a way out of the index; the rest the sandbox refuses as well."""
        assert "libs" in errors_for(venv([{"name": name}]))

    @pytest.mark.parametrize(
        ("name", "expected_name"),
        [
            ("requests\n", "requests"),
            ("requests ", "requests"),
            ("requests[socks]\n", "requests[socks]"),
        ],
    )
    def test_surrounding_whitespace_is_trimmed_off_rather_than_forwarded(
        self, name, expected_name
    ):
        serializer = VenvImportSerializer(data=venv([{"name": name}]))

        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["libs"][0]["name"] == expected_name

    def test_a_specifier_set_the_resolver_cannot_read(self):
        """Checked apart from the name: concatenated, `httpx` + `nonsense` parses as
        a package called `httpxnonsense` and reaches the sandbox as one."""
        assert "libs" in errors_for(venv([{"name": "httpx", "specification": "nonsense"}]))

    @pytest.mark.parametrize(
        "specification",
        [
            "==1.0\nmalicious-pkg",
            ">=1.0,\n<2",
            ">=1.0,\r<2",
            ">=1.0,\t<2",
            ">=1.0,\u2028<2",
            ">=1.0,\u00a0<2",
        ],
        ids=[
            "newline-injection",
            "newline",
            "carriage-return",
            "tab",
            "line-separator",
            "no-break-space",
        ],
    )
    def test_whitespace_other_than_a_plain_space_inside_a_specification(self, specification):
        """The sandbox feeds the requirements to `uv pip compile` on stdin, one per
        line, and `SpecifierSet` reads any whitespace as padding, so a line break here
        would smuggle in a second requirement. Only a plain space is let through, the
        sandbox's own rule."""
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
