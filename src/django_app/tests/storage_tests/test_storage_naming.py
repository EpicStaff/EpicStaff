import pytest

from tables.services.storage_service.naming import ensure_unique_file_name, split_file_name


@pytest.mark.parametrize(
    "path, existing, expected",
    [
        ("docs/report.pdf", ["docs/other.pdf"], "docs/report.pdf"),
        ("docs/report.pdf", ["docs/report.pdf"], "docs/report #2.pdf"),
        ("docs/report.pdf", ["docs/report.pdf", "docs/report #2.pdf"], "docs/report #3.pdf"),
        ("README", ["README"], "README #2"),
        (".env", [".env"], ".env #2"),
        ("a.tar.gz", ["a.tar.gz"], "a #2.tar.gz"),
        ("my.report.pdf", ["my.report.pdf"], "my.report #2.pdf"),
        ("docs/", ["docs/"], "docs #2/"),
        ("v1.2/", ["v1.2/"], "v1.2 #2/"),
        ("docs/", ["docs"], "docs #2/"),
        ("a/report.pdf", ["b/report.pdf"], "a/report.pdf"),
        ("report #2.pdf", ["report #2.pdf"], "report #3.pdf"),
    ],
)
def test_ensure_unique_file_name(path, existing, expected):
    assert ensure_unique_file_name(path, existing) == expected


@pytest.mark.parametrize(
    "name, expected",
    [("notes.", ("notes.", "")), ("A.TAR.GZ", ("A", ".TAR.GZ")), (".tar.gz", (".tar", ".gz"))],
)
def test_split_file_name(name, expected):
    assert split_file_name(name) == expected
