import io
import tarfile
import zipfile
from io import BytesIO
from unittest.mock import MagicMock

import pytest
from rest_framework.exceptions import ValidationError

from tables.validators.file_upload_validator import FileValidator


@pytest.fixture
def validator():
    return FileValidator()


# --- is_executable_filename ---


def test_blocks_exe_extension(validator):
    assert validator.is_executable_filename("malware.exe") is True


def test_blocks_shell_script_extension(validator):
    assert validator.is_executable_filename("run.sh") is True


def test_blocks_dll_extension(validator):
    assert validator.is_executable_filename("lib.dll") is True


def test_allows_txt_extension(validator):
    assert validator.is_executable_filename("notes.txt") is False


def test_allows_zip_extension(validator):
    assert validator.is_executable_filename("archive.zip") is False


def test_extension_check_is_case_insensitive(validator):
    assert validator.is_executable_filename("VIRUS.EXE") is True


# --- is_unsupported_archive ---


def test_blocks_rar_archive(validator):
    assert validator.is_unsupported_archive("data.rar") is True


def test_blocks_7z_archive(validator):
    assert validator.is_unsupported_archive("data.7z") is True


def test_allows_zip_archive_format(validator):
    assert validator.is_unsupported_archive("data.zip") is False


def test_allows_tar_archive_format(validator):
    assert validator.is_unsupported_archive("data.tar") is False


# --- scan_archive_for_executables ---


def test_scan_finds_executables_in_zip(validator):
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("ok.txt", "safe")
        zf.writestr("evil.sh", "#!/bin/bash")
    buf.seek(0)
    blocked = validator.scan_archive_for_executables(buf)
    assert blocked == ["evil.sh"]


def test_scan_finds_executables_in_tar(validator):
    buf = BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for name, data in [("ok.txt", b"safe"), ("evil.bat", b"@echo off")]:
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tf.addfile(info, BytesIO(data))
    buf.seek(0)
    blocked = validator.scan_archive_for_executables(buf)
    assert blocked == ["evil.bat"]


def test_scan_returns_empty_for_clean_archive(validator):
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("readme.txt", "hello")
        zf.writestr("data.csv", "a,b,c")
    buf.seek(0)
    assert validator.scan_archive_for_executables(buf) == []


def test_scan_returns_empty_for_non_archive(validator):
    buf = BytesIO(b"just plain text, not an archive")
    assert validator.scan_archive_for_executables(buf) == []


def test_scan_resets_file_position(validator):
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("a.txt", "data")
    buf.seek(0)
    validator.scan_archive_for_executables(buf)
    assert buf.tell() == 0


# --- validate ---


def _make_file(name, content=b"data"):
    f = MagicMock()
    f.name = name
    f.read.return_value = content
    f.tell.return_value = 0
    f.seek = MagicMock()
    return f


def test_validate_rejects_unsupported_archive_format(validator):
    with pytest.raises(ValidationError, match="not supported"):
        validator.validate([_make_file("data.rar")])


def test_validate_rejects_executable_file(validator):
    with pytest.raises(ValidationError, match="blocked executable"):
        validator.validate([_make_file("virus.exe")])


def test_validate_rejects_archive_containing_executables(validator):
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("hack.sh", "#!/bin/bash")
    content = buf.getvalue()

    f = MagicMock()
    f.name = "bundle.zip"
    # scan_archive_for_executables reads from file_obj, so we need real BytesIO behavior
    real_buf = BytesIO(content)
    f.tell = real_buf.tell
    f.read = real_buf.read
    f.seek = real_buf.seek

    with pytest.raises(ValidationError, match="executable files"):
        validator.validate([f])


def test_validate_passes_clean_files(validator):
    result = validator.validate([_make_file("report.pdf"), _make_file("data.csv")])
    assert len(result) == 2


def test_validate_aggregates_multiple_violations(validator):
    with pytest.raises(ValidationError) as exc_info:
        validator.validate([_make_file("a.exe"), _make_file("b.rar")])
    error_msg = str(exc_info.value)
    assert "a.exe" in error_msg
    assert "not supported" in error_msg
