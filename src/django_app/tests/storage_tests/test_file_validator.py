import io
import tarfile
import zipfile
from io import BytesIO
from unittest.mock import MagicMock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.exceptions import ValidationError

from tables.constants.upload_limits import UploadLimits
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
    f.size = len(content)
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
    # A real upload, so .size/.read/.seek behave as scan_archive_* expects
    f = SimpleUploadedFile("bundle.zip", buf.getvalue())

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


# --- size caps ---
#
# nginx caps a request body at 50M (nginx/templates/default.conf.template) but
# nothing below it bounded a storage upload at all: no per-file cap, no batch
# total. Both are enforced here so one 400 reports every violation at once.


def _upload(name, content=b"data"):
    """Build a real Django upload so .size/.read/.seek behave as in production."""
    return SimpleUploadedFile(name, content)


def _limited(**overrides):
    """Build a validator whose caps are tiny, so fixtures stay small."""
    limits = {
        "max_file_bytes": 1_000,
        "max_total_bytes": 10_000,
        "max_archive_entries": 1_000,
        "max_archive_uncompressed_bytes": 1_000_000,
    }
    limits.update(overrides)
    return FileValidator(limits=UploadLimits(**limits))


def test_validate_rejects_file_over_per_file_cap():
    validator = _limited(max_file_bytes=100)

    with pytest.raises(ValidationError, match="too large"):
        validator.validate([_upload("big.txt", b"x" * 200)])


def test_validate_allows_file_at_per_file_cap():
    validator = _limited(max_file_bytes=100)

    assert len(validator.validate([_upload("ok.txt", b"x" * 100)])) == 1


def test_validate_rejects_batch_over_total_cap():
    """Every file is individually legal; only the total is not."""
    validator = _limited(max_file_bytes=1_000, max_total_bytes=300)
    files = [_upload(f"f{i}.txt", b"x" * 150) for i in range(3)]

    with pytest.raises(ValidationError, match="Total upload size"):
        validator.validate(files)


def test_validate_allows_batch_at_total_cap():
    validator = _limited(max_file_bytes=1_000, max_total_bytes=300)
    files = [_upload(f"f{i}.txt", b"x" * 150) for i in range(2)]

    assert len(validator.validate(files)) == 2


def test_total_size_message_names_the_limit():
    validator = _limited(max_total_bytes=300)

    with pytest.raises(ValidationError) as exc_info:
        validator.validate([_upload("a.txt", b"x" * 400)])

    assert "300" in str(exc_info.value)


# --- archive expansion caps ---
#
# Reads the ZIP central directory / TAR headers only. Both modules bound a
# member read by its declared size (verified: a size patched down truncates the
# read and fails CRC), so declared totals are a sound basis for rejection and
# nothing has to be decompressed to apply these caps.


def _zip_of(entries, compression=zipfile.ZIP_DEFLATED):
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", compression) as zf:
        for name, payload in entries:
            zf.writestr(name, payload)
    buf.seek(0)
    return buf


def test_validate_rejects_zip_with_too_many_entries():
    validator = _limited(max_archive_entries=5)
    buf = _zip_of([(f"f{i}.txt", b"tiny") for i in range(10)])

    with pytest.raises(ValidationError, match="entries"):
        validator.validate([_upload("many.zip", buf.getvalue())])


def test_validate_rejects_zip_over_declared_uncompressed_total():
    validator = _limited(
        max_file_bytes=100_000,
        max_archive_uncompressed_bytes=1_000,
    )
    buf = _zip_of([("a.txt", b"x" * 2_000)], compression=zipfile.ZIP_STORED)

    with pytest.raises(ValidationError, match="expands to"):
        validator.validate([_upload("total.zip", buf.getvalue())])


def test_validate_allows_ordinary_zip():
    validator = _limited(max_file_bytes=100_000)
    buf = _zip_of([("readme.txt", b"hello"), ("data.csv", b"a,b,c")])

    assert len(validator.validate([_upload("bundle.zip", buf.getvalue())])) == 1


def test_expansion_scan_resets_file_position():
    validator = _limited(max_file_bytes=100_000)
    upload = _upload("bundle.zip", _zip_of([("a.txt", b"data")]).getvalue())

    validator.validate([upload])

    assert upload.tell() == 0


def test_non_archive_upload_skips_expansion_checks():
    validator = _limited(max_file_bytes=100_000)
    assert len(validator.validate([_upload("notes.txt", b"just text")])) == 1


def test_validate_rejects_compressed_tar_over_the_decompress_cap():
    """A tar.gz must be inflated through a hard cap before its headers are readable.

    Distinct from the ratio and declared-total cases: those return a reason from
    header data, while this path aborts inside _bounded_decompress before any
    header is parsed, and is the only caller of _ArchiveTooLarge.
    """
    validator = _limited(
        max_file_bytes=10_000_000,
        max_archive_uncompressed_bytes=1_000,
    )
    buf = BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        payload = b"\0" * 500_000
        info = tarfile.TarInfo("zeros.bin")
        info.size = len(payload)
        tf.addfile(info, BytesIO(payload))

    with pytest.raises(ValidationError, match="expands to more than"):
        validator.validate([_upload("big.tar.gz", buf.getvalue())])
