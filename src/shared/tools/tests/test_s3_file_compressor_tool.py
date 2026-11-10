"""s3_file_compressor_tool: archive a storage file or folder back into storage.

Each case seeds the in-memory S3 fake, runs the tool and opens the archive bytes
it wrote to check the members an agent would get when extracting it.
"""

import io
import json
import tarfile
import zipfile
from datetime import UTC, datetime

import pytest
from conftest import TEST_BUCKET, load_tool, seed, storage_module

tool = load_tool("s3_file_compressor_tool")


def _zip_members(fake_client, path: str) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(fake_client.objects[path]["Body"])) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def _tar_members(fake_client, path: str) -> dict[str, bytes]:
    with tarfile.open(fileobj=io.BytesIO(fake_client.objects[path]["Body"])) as archive:
        return {member.name: archive.extractfile(member).read() for member in archive.getmembers()}


def _seed_reports(fake_client) -> None:
    seed(fake_client, "reports/summary.txt", "summary")
    seed(fake_client, "reports/2026/q1.csv", "a,b\n1,2\n")
    fake_client.put_object(Bucket=TEST_BUCKET, Key="reports/logo.png", Body=b"\x89PNG\x00\xff")


REPORTS_MEMBERS = {
    "summary.txt": b"summary",
    "2026/q1.csv": b"a,b\n1,2\n",
    "logo.png": b"\x89PNG\x00\xff",
}
# Tar formats keep a folder's files under a top-level directory named after the folder.
REPORTS_TAR_MEMBERS = {f"reports/{name}": content for name, content in REPORTS_MEMBERS.items()}


def test_folder_to_zip_holds_every_file_relative_to_the_folder(patched_storage, fake_client):
    _seed_reports(fake_client)

    result = tool.main(input_path="reports", output_path="archives/reports.zip")

    assert _zip_members(fake_client, "archives/reports.zip") == REPORTS_MEMBERS
    archive_size = len(fake_client.objects["archives/reports.zip"]["Body"])
    assert result == (
        f"Compressed 3 file(s) from 'reports' into 'archives/reports.zip' ({archive_size} bytes)."
    )


@pytest.mark.parametrize("archive_format", ["tar", "tar.gz", "tar.bz2", "tar.xz"])
def test_folder_to_tar_variants_round_trip(patched_storage, fake_client, archive_format):
    _seed_reports(fake_client)
    output_path = f"out/reports.{archive_format}"

    result = tool.main(input_path="reports/", output_path=output_path, format=archive_format)

    assert result.startswith("Compressed 3 file(s)")
    assert _tar_members(fake_client, output_path) == REPORTS_TAR_MEMBERS


def test_nested_folder_to_tar_sits_under_its_own_base_name(patched_storage, fake_client):
    _seed_reports(fake_client)

    tool.main(input_path="reports/2026", output_path="q.tar", format="tar")

    assert _tar_members(fake_client, "q.tar") == {"2026/q1.csv": b"a,b\n1,2\n"}


@pytest.mark.parametrize(
    ("archive_format", "read_members"),
    [("zip", _zip_members), ("tar.gz", _tar_members)],
)
def test_single_file_is_archived_under_its_base_name(
    patched_storage, fake_client, archive_format, read_members
):
    seed(fake_client, "docs/notes/today.txt", "hello")
    output_path = f"today.{archive_format}"

    result = tool.main(
        input_path="docs/notes/today.txt", output_path=output_path, format=archive_format
    )

    assert result.startswith("Compressed 1 file(s)")
    assert read_members(fake_client, output_path) == {"today.txt": b"hello"}


@pytest.mark.parametrize(
    ("archive_format", "read_members", "expected_members"),
    [
        ("zip", _zip_members, REPORTS_MEMBERS),
        ("tar", _tar_members, REPORTS_TAR_MEMBERS),
    ],
)
def test_leading_slash_input_still_yields_relative_member_names(
    patched_storage, fake_client, archive_format, read_members, expected_members
):
    _seed_reports(fake_client)
    output_path = f"out/reports.{archive_format}"

    tool.main(input_path="/reports", output_path=output_path, format=archive_format)

    assert read_members(fake_client, output_path) == expected_members


def test_file_sharing_a_prefix_with_a_folder_is_archived_alone(patched_storage, fake_client):
    seed(fake_client, "reports", "the file")
    seed(fake_client, "reports2/other.txt", "not part of it")

    result = tool.main(input_path="reports", output_path="out.zip")

    assert result.startswith("Compressed 1 file(s)")
    assert _zip_members(fake_client, "out.zip") == {"reports": b"the file"}


STORED_MODIFIED_TIME = datetime(2024, 3, 5, 10, 20, 30, tzinfo=UTC)


@pytest.mark.parametrize("input_path", ["data", "data/a.txt"])
def test_zip_member_keeps_the_stored_modified_time(patched_storage, fake_client, input_path):
    seed(fake_client, "data/a.txt", "x")
    fake_client.objects["data/a.txt"]["LastModified"] = STORED_MODIFIED_TIME

    tool.main(input_path=input_path, output_path="out.zip")

    with zipfile.ZipFile(io.BytesIO(fake_client.objects["out.zip"]["Body"])) as archive:
        assert archive.getinfo("a.txt").date_time == (2024, 3, 5, 10, 20, 30)


@pytest.mark.parametrize("input_path", ["data", "data/a.txt"])
def test_tar_member_keeps_the_stored_modified_time(patched_storage, fake_client, input_path):
    seed(fake_client, "data/a.txt", "x")
    fake_client.objects["data/a.txt"]["LastModified"] = STORED_MODIFIED_TIME

    tool.main(input_path=input_path, output_path="out.tar", format="tar")

    with tarfile.open(fileobj=io.BytesIO(fake_client.objects["out.tar"]["Body"])) as archive:
        assert [member.mtime for member in archive.getmembers()] == [1709634030]


def test_member_without_a_stored_modified_time_gets_the_current_time(patched_storage, fake_client):
    seed(fake_client, "data/a.txt", "x")
    fake_client.objects["data/a.txt"]["LastModified"] = None
    before = int(datetime.now(UTC).timestamp())

    tool.main(input_path="data", output_path="out.tar", format="tar")

    with tarfile.open(fileobj=io.BytesIO(fake_client.objects["out.tar"]["Body"])) as archive:
        (member,) = archive.getmembers()
    assert before <= member.mtime <= int(datetime.now(UTC).timestamp())


@pytest.mark.parametrize(
    ("input_path", "archive_format", "expected_output"),
    [
        ("docs/today.txt", "zip", "docs/today.zip"),
        ("docs/today.txt", "tar.xz", "docs/today.tar.xz"),
        ("reports", "zip", "reports.zip"),
        ("reports/2026/", "tar", "reports/2026.tar"),
        ("reports/.", "zip", "reports.zip"),
        ("reports/2026/./", "tar.gz", "reports/2026.tar.gz"),
        ("/docs/today.txt", "zip", "docs/today.zip"),
    ],
)
def test_default_output_path_sits_next_to_the_input(
    patched_storage, fake_client, input_path, archive_format, expected_output
):
    seed(fake_client, "docs/today.txt", "hello")
    seed(fake_client, "reports/2026/q1.csv", "a,b")

    result = tool.main(input_path=input_path, format=archive_format)

    assert f"into '{expected_output}'" in result
    assert expected_output in fake_client.objects


def test_existing_output_is_kept_when_overwrite_is_false(patched_storage, fake_client):
    seed(fake_client, "a.txt", "new")
    seed(fake_client, "a.zip", "old archive")

    result = tool.main(input_path="a.txt")

    assert "already exists" in result
    assert fake_client.objects["a.zip"]["Body"] == b"old archive"


def test_existing_output_is_replaced_when_overwrite_is_true(patched_storage, fake_client):
    seed(fake_client, "a.txt", "new")
    seed(fake_client, "a.zip", "old archive")

    result = tool.main(input_path="a.txt", overwrite=True)

    assert result.startswith("Compressed 1 file(s)")
    assert _zip_members(fake_client, "a.zip") == {"a.txt": b"new"}


@pytest.mark.parametrize(
    ("output_path", "archive_format"),
    [("a.tar.gz", "zip"), ("a.zip", "tar"), ("a.tar.gz", "tar"), ("a", "tar.xz")],
)
def test_output_path_with_the_wrong_extension_is_refused(
    patched_storage, fake_client, output_path, archive_format
):
    seed(fake_client, "a.txt", "x")

    result = tool.main(input_path="a.txt", output_path=output_path, format=archive_format)

    assert f"must end with '.{archive_format}'" in result
    assert output_path not in fake_client.objects


def test_unsupported_format_is_refused(patched_storage, fake_client):
    seed(fake_client, "a.txt", "x")

    result = tool.main(input_path="a.txt", format="rar")

    assert "not supported" in result
    assert "zip, tar, tar.gz, tar.bz2, tar.xz" in result
    assert set(fake_client.objects) == {"a.txt"}


def test_missing_input_is_reported(patched_storage, fake_client):
    result = tool.main(input_path="nowhere/file.txt")

    assert result == "Input not found: nowhere/file.txt."
    assert fake_client.objects == {}


def test_empty_folder_is_refused(patched_storage, fake_client):
    seed(fake_client, "empty/.keep", "")

    result = tool.main(input_path="empty")

    assert result == "Folder 'empty' contains no files to compress."
    assert "empty.zip" not in fake_client.objects


def test_storage_root_is_refused(patched_storage, fake_client):
    seed(fake_client, "a.txt", "x")

    result = tool.main(input_path="/")

    assert "storage root cannot be compressed" in result
    assert set(fake_client.objects) == {"a.txt"}


@pytest.mark.parametrize("org_prefix", [None, "org-7"])
def test_archive_inside_the_input_folder_does_not_include_itself(
    patched_storage, fake_client, monkeypatch, org_prefix
):
    key_prefix = ""
    if org_prefix:
        monkeypatch.setenv("STORAGE_ORG_PREFIX", org_prefix)
        key_prefix = f"{org_prefix}/"
    seed(fake_client, f"{key_prefix}project/main.py", "print(1)")
    seed(fake_client, f"{key_prefix}project/project.zip", "previous archive")

    result = tool.main(input_path="project", output_path="project/project.zip", overwrite=True)

    assert result.startswith("Compressed 1 file(s)")
    assert _zip_members(fake_client, f"{key_prefix}project/project.zip") == {"main.py": b"print(1)"}


def test_folder_holding_only_its_own_archive_is_refused(patched_storage, fake_client):
    seed(fake_client, "project/project.zip", "previous archive")

    result = tool.main(input_path="project", output_path="project/project.zip", overwrite=True)

    assert "contains no files to compress" in result
    assert fake_client.objects["project/project.zip"]["Body"] == b"previous archive"


def test_file_compressed_onto_itself_is_refused(patched_storage, fake_client):
    seed(fake_client, "bundle.zip", "original")

    result = tool.main(input_path="bundle.zip", output_path="bundle.zip", overwrite=True)

    assert result == "output_path must differ from input_path."
    assert fake_client.objects["bundle.zip"]["Body"] == b"original"


def test_file_whose_default_output_is_itself_asks_for_an_output_path(patched_storage, fake_client):
    seed(fake_client, "data.zip", "original")

    result = tool.main(input_path="data.zip", overwrite=True)

    assert result == (
        "The default output path 'data.zip' is the input file itself. "
        "Pass an explicit output_path that differs from input_path."
    )
    assert fake_client.objects["data.zip"]["Body"] == b"original"


@pytest.mark.parametrize(("input_size", "accepted"), [(10, True), (11, False)])
def test_input_size_limit_boundary(patched_storage, fake_client, monkeypatch, input_size, accepted):
    monkeypatch.setattr(storage_module, "MAX_LINE_READ_BYTES", 10)
    seed(fake_client, "data/a.txt", "x" * (input_size - 4))
    seed(fake_client, "data/b.txt", "yyyy")

    result = tool.main(input_path="data")

    assert ("data.zip" in fake_client.objects) is accepted
    if not accepted:
        assert "compression limit" in result


def test_size_limit_is_the_shared_50_megabyte_read_limit():
    # The boundary test above patches this constant, so the tool reads it; this pins the
    # 50 MB figure the tool description promises.
    assert storage_module.MAX_LINE_READ_BYTES == 50 * 1024 * 1024


@pytest.mark.parametrize(("file_count", "accepted"), [(3, True), (4, False)])
def test_file_count_limit_boundary(patched_storage, fake_client, monkeypatch, file_count, accepted):
    monkeypatch.setattr(tool, "_MAX_FILES", 3)
    for index in range(file_count):
        seed(fake_client, f"many/file{index}.txt", "x")

    result = tool.main(input_path="many")

    assert ("many.zip" in fake_client.objects) is accepted
    if not accepted:
        assert result == (
            "Input 'many' holds 4 files, over the 3-file compression limit. "
            "Narrow input_path to a subfolder with fewer files."
        )


def test_file_count_limit_is_one_thousand():
    assert tool._MAX_FILES == 1000


@pytest.mark.parametrize(
    ("input_path", "allowed_paths", "expected_result"),
    [
        (
            "reports",
            ["archives/"],
            (
                "Access denied: walk on 'reports' is not within this flow's allowed files. "
                "Allowed paths: [archives/]. Specify one of these (root/'' listing is not available)."
            ),
        ),
        ("../etc", None, "Path escapes the target folder: '../etc'"),
        ("reports/../../etc", None, "Path escapes the target folder: 'reports/../../etc'"),
    ],
)
def test_input_outside_reach_is_refused(
    patched_storage, fake_client, monkeypatch, input_path, allowed_paths, expected_result
):
    if allowed_paths is not None:
        monkeypatch.setenv("STORAGE_ALLOWED_PATHS", json.dumps(allowed_paths))
    seed(fake_client, "reports/a.txt", "x")

    result = tool.main(input_path=input_path, output_path="archives/out.zip")

    assert result == expected_result
    assert set(fake_client.objects) == {"reports/a.txt"}


def test_output_outside_allowed_files_is_refused(patched_storage, fake_client, monkeypatch):
    monkeypatch.setenv("STORAGE_ALLOWED_PATHS", json.dumps(["reports/"]))
    seed(fake_client, "reports/a.txt", "x")

    result = tool.main(input_path="reports", output_path="elsewhere/reports.zip")

    assert "Access denied" in result
    assert "elsewhere/reports.zip" not in fake_client.objects
