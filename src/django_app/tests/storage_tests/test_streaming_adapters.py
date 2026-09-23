import io
import zipfile

import pytest
from rest_framework import serializers

from tables.constants.upload_limits import UploadLimits
from tables.services.storage_service.archive_limits import (
    ArchiveExtractionGuard,
    ArchiveLimitExceeded,
)
from tables.validators.file_upload_validator import FileValidator
from tests.storage_tests.in_memory_backend import InMemoryStorageBackend


def _limits(**over):
    base = dict(
        max_file_bytes=1000,
        max_total_bytes=1000,
        max_archive_entries=100,
        max_archive_uncompressed_bytes=1000,
    )
    base.update(over)
    return UploadLimits(**base)


def _zip(members: dict[str, bytes]) -> io.BytesIO:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    buf.seek(0)
    return buf


# --- validate_name ---


def test_validate_name_blocks_exe():
    v = FileValidator(limits=_limits())
    with pytest.raises(serializers.ValidationError):
        v.validate_name("evil.exe")


def test_validate_name_blocks_unsupported_archive():
    v = FileValidator(limits=_limits())
    with pytest.raises(serializers.ValidationError):
        v.validate_name("a.rar")


def test_validate_name_ok():
    FileValidator(limits=_limits()).validate_name("ok.txt")


# --- iter_archive_members_streaming + guard ---


def test_stream_members_happy():
    backend = InMemoryStorageBackend(organization_prefix="")
    guard = ArchiveExtractionGuard(max_entries=100, max_total_bytes=1000)
    archive = _zip({"a.txt": b"hello", "sub/b.txt": b"world"})
    got = {}
    for name, reader in backend.iter_archive_members_streaming(archive, guard):
        got[name] = reader.read()
    assert got == {"a.txt": b"hello", "sub/b.txt": b"world"}


def test_stream_members_guard_trips_on_oversize_member():
    backend = InMemoryStorageBackend(organization_prefix="")
    guard = ArchiveExtractionGuard(max_entries=100, max_total_bytes=8)
    archive = _zip({"big.txt": b"0123456789"})
    with pytest.raises(ArchiveLimitExceeded):
        for _name, reader in backend.iter_archive_members_streaming(archive, guard):
            while reader.read(4):
                pass
