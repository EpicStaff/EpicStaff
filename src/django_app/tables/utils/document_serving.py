import io
import mimetypes
import zipfile

from django.http import HttpResponse
from tables.constants.knowledge_constants import PREVIEW_CONTENT_TYPES
from tables.models import DocumentMetadata
from tables.services.knowledge_services.document_content_storage import DocumentContentStorage


def document_bytes(document: DocumentMetadata) -> bytes:
    """Return the document's stored bytes, or empty bytes for a document without content.

    Raises:
        DocumentContentMissingException: The row points at a file that is gone from storage.
        StorageUnavailable: Object storage could not be reached.
    """
    content = document.document_content
    if content is None:
        return b""
    return DocumentContentStorage.read(content.object_key)


def file_response(
    content: bytes,
    content_type: str,
    filename: str,
    disposition: str = "attachment",
) -> HttpResponse:
    """Serve raw bytes with the given content type and Content-Disposition."""
    response = HttpResponse(content, content_type=content_type)
    response["Content-Disposition"] = f'{disposition}; filename="{filename}"'
    return response


def build_file_response(document: DocumentMetadata) -> HttpResponse:
    """Build an attachment response for a single document."""
    content_type = mimetypes.guess_type(document.file_name)[0] or "application/octet-stream"
    return file_response(document_bytes(document), content_type, document.file_name)


def build_preview_response(document: DocumentMetadata) -> HttpResponse:
    """Build an inline response for a single document"""
    content_type = (
        PREVIEW_CONTENT_TYPES.get(document.file_type)
        or mimetypes.guess_type(document.file_name)[0]
        or "application/octet-stream"
    )
    return file_response(document_bytes(document), content_type, document.file_name, "inline")


def build_archive_response(documents: list, archive_name: str = "documents.zip") -> HttpResponse:
    """Bundle multiple documents into a zip attachment, deduplicating file names."""
    buffer = io.BytesIO()
    used_names: dict[str, int] = {}

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for document in documents:
            archive.writestr(
                unique_archive_name(document.file_name, used_names),
                document_bytes(document),
            )

    return file_response(buffer.getvalue(), "application/zip", archive_name)


def unique_archive_name(name: str, used_names: dict) -> str:
    """Suffix duplicate file names so no archive entry is overwritten."""
    count = used_names.get(name, 0)
    used_names[name] = count + 1
    if count == 0:
        return name

    stem, dot, ext = name.rpartition(".")
    return f"{stem} ({count}){dot}{ext}" if dot else f"{name} ({count})"
