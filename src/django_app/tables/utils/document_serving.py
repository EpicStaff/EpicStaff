import io
import mimetypes
import zipfile

from django.http import HttpResponse

from tables.constants.knowledge_constants import PREVIEW_CONTENT_TYPES
from tables.models import DocumentMetadata


def document_bytes(document: DocumentMetadata) -> bytes:
    """Return the binary payload of a document, or empty bytes if absent."""
    content = document.document_content
    if content is None or content.content is None:
        return b""
    return bytes(content.content)


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
    content_type = (
        mimetypes.guess_type(document.file_name)[0] or "application/octet-stream"
    )
    return file_response(document_bytes(document), content_type, document.file_name)


def build_preview_response(document: DocumentMetadata) -> HttpResponse:
    """
    Build an inline response for a single document so the browser can render it
    in place (preview) instead of downloading it. DOCX has no native browser
    preview and will still be downloaded by the browser regardless of this header.
    """
    content_type = (
        PREVIEW_CONTENT_TYPES.get(document.file_type)
        or mimetypes.guess_type(document.file_name)[0]
        or "application/octet-stream"
    )
    return file_response(
        document_bytes(document), content_type, document.file_name, "inline"
    )


def build_archive_response(
    documents: list, archive_name: str = "documents.zip"
) -> HttpResponse:
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
