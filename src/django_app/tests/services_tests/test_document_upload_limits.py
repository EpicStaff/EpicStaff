"""A knowledge document batch is capped in total size, not only per file.

DocumentManagementService already rejected any single file over MAX_FILE_SIZE
(12MB) but summed nothing, so a batch of individually-legal files was unbounded:
create_document_content reads every one of them into memory and stores it as a
DocumentContent blob in one transaction.

The total cap is the same MAX_UPLOAD_TOTAL_BYTES the storage upload path uses,
so both upload surfaces answer to one knob.
"""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

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
