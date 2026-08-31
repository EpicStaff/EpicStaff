"""A knowledge document batch is capped in total size, not only per file.

DocumentManagementService already rejected any single file over MAX_FILE_SIZE
(12MB) but summed nothing, so a batch of individually-legal files was unbounded:
create_document_content reads every one of them into memory and stores it as a
DocumentContent blob in one transaction.

The total cap is the same MAX_UPLOAD_TOTAL_BYTES the storage upload path uses,
so both upload surfaces answer to one knob.
"""

import zipfile
from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from tables.constants.upload_limits import default_upload_limits
from tables.exceptions import DocumentUploadException
from tables.services.knowledge_services.document_management_service import (
    DocumentManagementService,
)


@pytest.fixture
def total_cap(monkeypatch):
    """Shrink the batch total cap so fixtures stay small."""
    monkeypatch.setenv("MAX_UPLOAD_TOTAL_BYTES", "300")


def _file(name: str, size: int) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, b"x" * size)


def _zip_declaring(unpacked: int, name: str = "report.docx") -> SimpleUploadedFile:
    """A small ZIP (DOCX is one) whose single entry unpacks to `unpacked` bytes."""
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr("word/document.xml", b"A" * unpacked)
    return SimpleUploadedFile(name, buffer.getvalue())


def test_rejects_batch_over_total_cap(total_cap):
    """Each file is individually legal; only their sum is not."""
    files = [_file(f"note{i}.txt", 150) for i in range(3)]

    with pytest.raises(DocumentUploadException, match="Total upload size"):
        DocumentManagementService.validate_files_batch(files)


def test_accepts_batch_within_total_cap(total_cap):
    files = [_file(f"note{i}.txt", 150) for i in range(2)]

    validated = DocumentManagementService.validate_files_batch(files)

    assert len(validated) == 2


def test_total_cap_error_names_the_limit(total_cap):
    with pytest.raises(DocumentUploadException) as exc_info:
        DocumentManagementService.validate_files_batch([_file("big.txt", 400)])

    assert "300" in str(exc_info.value)


def test_total_cap_is_reported_alongside_per_file_errors(total_cap):
    """A batch that is both oversized and badly typed reports both problems."""
    files = [_file("note.txt", 200), _file("payload.bin", 200)]

    with pytest.raises(DocumentUploadException) as exc_info:
        DocumentManagementService.validate_files_batch(files)

    message = str(exc_info.value)
    assert "Total upload size" in message
    assert "payload.bin" in message


def test_ordinary_batch_passes_under_shipped_defaults():
    """No env override: the default cap must not reject a normal upload."""
    files = [_file(f"note{i}.txt", 1_000) for i in range(3)]

    assert len(DocumentManagementService.validate_files_batch(files)) == 3


# --- container documents are inspected at upload, not just at extraction ---
#
# A DOCX is a ZIP, so a small upload can hold an enormous unpacked payload.
# Until FileValidator ran here, such a file uploaded cleanly and only failed
# later during indexing -- an async failure for a problem knowable up front.


@pytest.fixture
def small_unpacked_cap(monkeypatch):
    """Shrink the unpacked cap so the fixture stays small."""
    monkeypatch.setenv("MAX_ARCHIVE_UNCOMPRESSED_BYTES", "100000")


def test_rejects_a_docx_that_unpacks_past_the_archive_cap(small_unpacked_cap):
    bomb = _zip_declaring(500_000)
    assert bomb.size < 10_000  # small on the wire, 50x that unpacked

    with pytest.raises(DocumentUploadException, match="unpack|expands"):
        DocumentManagementService.validate_files_batch([bomb])


def test_docx_rejection_is_a_document_upload_exception_not_a_drf_error(
    small_unpacked_cap,
):
    """A bare serializers.ValidationError would escape the view as a 500."""
    bomb = _zip_declaring(500_000)

    with pytest.raises(DocumentUploadException):
        DocumentManagementService.validate_files_batch([bomb])


def test_accepts_an_ordinary_docx():
    ordinary = _zip_declaring(50_000)

    assert len(DocumentManagementService.validate_files_batch([ordinary])) == 1


def test_caps_match_the_knowledge_service():
    """Anything indexing would refuse must be refused at upload instead.

    The knowledge service is a separate container, so these numbers cannot be
    imported from it -- they are asserted on both sides instead. If someone
    changes one service's limit, that service's suite goes red.
    See knowledge/tests/test_extraction_limits.py::test_caps_match_the_upload_path.
    """
    limits = default_upload_limits()

    assert limits.max_file_bytes == 50 * 1024 * 1024
    assert limits.max_archive_uncompressed_bytes == 256 * 1024 * 1024
