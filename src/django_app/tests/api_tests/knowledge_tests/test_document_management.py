"""
Tests for Document Management operations
"""

import pytest
from django.core.exceptions import SuspiciousFileOperation
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework import status

from tables.models.knowledge_models import DocumentMetadata


@pytest.mark.django_db
class TestDocumentList:
    """Tests for listing documents."""

    def test_list_all_documents(self, auth_client, multiple_documents):
        """Test listing all documents."""
        url = reverse("document-list")
        response = auth_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 3
        assert all("document_id" in item for item in data)
        assert all("file_name" in item for item in data)

    def test_list_documents_empty(self, auth_client):
        """Test listing when no documents exist."""
        url = reverse("document-list")
        response = auth_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    def test_list_documents_filtered_by_collection(
        self, auth_client, source_collection, multiple_documents
    ):
        """Test filtering documents by collection."""
        url = reverse("document-list")
        response = auth_client.get(
            url, {"collection_id": source_collection.collection_id}
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 3


@pytest.mark.django_db
class TestDocumentRetrieve:
    """Tests for retrieving a single document."""

    def test_retrieve_document(self, auth_client, document_metadata):
        """Test retrieving a document by ID."""
        url = reverse("document-detail", args=[document_metadata.document_id])
        response = auth_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["document_id"] == document_metadata.document_id
        assert data["file_name"] == document_metadata.file_name
        assert data["file_type"] == document_metadata.file_type
        assert "collection_name" in data

    def test_retrieve_nonexistent_document(self, auth_client):
        """Test retrieving a document that doesn't exist."""
        url = reverse("document-detail", args=[99999])
        response = auth_client.get(url)

        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestDocumentUpload:
    """Tests for uploading documents."""

    def test_upload_single_document(
        self, auth_client, source_collection, test_pdf_file
    ):
        """Test uploading a single document."""
        url = reverse("document-upload", args=[source_collection.collection_id])
        data = {"files": [test_pdf_file]}

        response = auth_client.post(url, data, format="multipart")

        assert response.status_code == status.HTTP_201_CREATED
        response_data = response.json()
        assert "documents" in response_data
        assert len(response_data["documents"]) == 1
        assert response_data["documents"][0]["file_name"] == "test.pdf"

    def test_upload_multiple_documents(
        self, auth_client, source_collection, test_pdf_file, test_txt_file
    ):
        """Test uploading multiple documents at once."""
        url = reverse("document-upload", args=[source_collection.collection_id])
        data = {"files": [test_pdf_file, test_txt_file]}

        response = auth_client.post(url, data, format="multipart")

        assert response.status_code == status.HTTP_201_CREATED
        response_data = response.json()
        assert len(response_data["documents"]) == 2

    def test_upload_to_nonexistent_collection(self, auth_client, test_pdf_file):
        """Test uploading to a collection that doesn't exist."""
        url = reverse("document-upload", args=[99999])
        data = {"files": [test_pdf_file]}

        response = auth_client.post(url, data, format="multipart")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_upload_file_exceeding_size_limit(
        self, auth_client, source_collection, large_file
    ):
        """Test uploading a file that exceeds size limit."""
        url = reverse("document-upload", args=[source_collection.collection_id])
        data = {"files": [large_file]}

        response = auth_client.post(url, data, format="multipart")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "exceeds" in response.json()["error"].lower()

    def test_upload_invalid_file_type(
        self, auth_client, source_collection, invalid_file_type
    ):
        """Test uploading a file with invalid extension."""
        url = reverse("document-upload", args=[source_collection.collection_id])
        data = {"files": [invalid_file_type]}

        response = auth_client.post(url, data, format="multipart")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "invalid type" in response.json()["error"].lower()

    def test_upload_without_files(self, auth_client, source_collection):
        """Test uploading without providing files."""
        url = reverse("document-upload", args=[source_collection.collection_id])
        data = {"files": []}

        response = auth_client.post(url, data, format="multipart")

        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestDocumentDelete:
    """Tests for deleting documents."""

    def test_delete_single_document(self, auth_client, document_metadata):
        """Test deleting a single document."""
        document_id = document_metadata.document_id
        url = reverse("document-detail", args=[document_id])

        response = auth_client.delete(url)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["document_id"] == document_id

        # Verify deletion
        assert not DocumentMetadata.objects.filter(document_id=document_id).exists()

    def test_delete_nonexistent_document(self, auth_client):
        """Test deleting a document that doesn't exist."""
        url = reverse("document-detail", args=[99999])
        response = auth_client.delete(url)

        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestDocumentBulkDelete:
    """Tests for bulk deleting documents."""

    def test_bulk_delete_documents(self, auth_client, multiple_documents):
        """Test bulk deleting multiple documents."""
        url = reverse("document-bulk-delete")
        document_ids = [doc.document_id for doc in multiple_documents]
        data = {"document_ids": document_ids}

        response = auth_client.post(url, data, format="json")

        assert response.status_code == status.HTTP_200_OK
        response_data = response.json()
        assert len(response_data["deleted_documents"]) == 3

        # Verify deletion
        for doc_id in document_ids:
            assert not DocumentMetadata.objects.filter(document_id=doc_id).exists()

    def test_bulk_delete_with_empty_list(self, auth_client):
        """Test bulk delete with empty document_ids."""
        url = reverse("document-bulk-delete")
        data = {"document_ids": []}

        response = auth_client.post(url, data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_bulk_delete_removes_duplicate_ids(self, auth_client, document_metadata):
        """Test bulk delete removes duplicate IDs."""
        url = reverse("document-bulk-delete")
        doc_id = document_metadata.document_id
        data = {"document_ids": [doc_id, doc_id, doc_id]}

        response = auth_client.post(url, data, format="json")

        assert response.status_code == status.HTTP_200_OK
        response_data = response.json()
        # Should only delete once
        assert len(response_data["deleted_documents"]) == 1

    def test_bulk_delete_with_some_missing_documents(
        self, auth_client, document_metadata
    ):
        """Test bulk delete with some nonexistent document IDs."""
        url = reverse("document-bulk-delete")
        data = {"document_ids": [document_metadata.document_id, 99999, 99998]}

        response = auth_client.post(url, data, format="json")

        # Should delete existing documents and log warnings for missing ones
        assert response.status_code == status.HTTP_200_OK
        response_data = response.json()
        assert len(response_data["deleted_documents"]) == 1


@pytest.mark.django_db
class TestCollectionDocuments:
    """Tests for listing documents in a specific collection."""

    def test_list_collection_documents(
        self, auth_client, source_collection, multiple_documents
    ):
        """Test listing all documents in a collection."""
        url = reverse("collection-documents", args=[source_collection.collection_id])
        response = auth_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["collection_id"] == source_collection.collection_id
        assert data["collection_name"] == source_collection.collection_name
        assert data["document_count"] == 3
        assert len(data["documents"]) == 3

    def test_list_documents_for_empty_collection(self, auth_client, empty_collection):
        """Test listing documents for a collection with no documents."""
        url = reverse("collection-documents", args=[empty_collection.collection_id])
        response = auth_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["document_count"] == 0
        assert data["documents"] == []

    def test_list_documents_for_nonexistent_collection(self, auth_client):
        """Test listing documents for a collection that doesn't exist."""
        url = reverse("collection-documents", args=[99999])
        response = auth_client.get(url)

        assert response.status_code == status.HTTP_404_NOT_FOUND


# A stored file_name is joined to a directory when the knowledge service writes
# the document to disk for GraphRAG indexing, so a path would let that write
# land outside the input folder. Uploads cannot express these names — Django
# basenames every UploadedFile.name — so they are written to the model directly.
PATH_FILE_NAMES = [
    "../../../../etc/cron.d/evil.txt",
    "a/../../../evil.txt",
    "sub/dir.txt",
    "/etc/passwd",
    "..\\..\\win.ini",
    "C:evil.txt",
    "..",
    ".",
]


@pytest.mark.django_db
class TestDocumentFileNameValidation:
    """Tests that a file_name carrying a path is refused on write."""

    @pytest.mark.parametrize("file_name", PATH_FILE_NAMES)
    def test_save_rejects_path_as_file_name(
        self, source_collection, document_content, file_name
    ):
        """A name with a path component is refused and nothing is stored."""
        document = DocumentMetadata(
            source_collection=source_collection,
            document_content=document_content,
            file_name=file_name,
            file_type="txt",
            file_size=1,
        )

        with pytest.raises(SuspiciousFileOperation) as exc_info:
            document.save()

        assert repr(file_name) in str(exc_info.value)
        assert not DocumentMetadata.objects.exists()

    @pytest.mark.parametrize("file_name", ["report.txt", "..hidden.txt", ""])
    def test_save_accepts_plain_file_name(
        self, source_collection, document_content, file_name
    ):
        """A plain file name — including a blank one — is stored unchanged."""
        document = DocumentMetadata.objects.create(
            source_collection=source_collection,
            document_content=document_content,
            file_name=file_name,
            file_type="txt",
            file_size=1,
        )

        document.refresh_from_db()
        assert document.file_name == file_name

    def test_uploaded_file_name_never_contains_a_path(
        self, auth_client, source_collection
    ):
        """An upload whose filename is a path stores a bare name, never a path."""
        url = reverse("document-upload", args=[source_collection.collection_id])
        traversal_file = SimpleUploadedFile(
            name="../../../../etc/cron.d/evil.txt",
            content=b"x",
            content_type="text/plain",
        )

        response = auth_client.post(
            url, {"files": [traversal_file]}, format="multipart"
        )

        assert response.status_code == status.HTTP_201_CREATED
        stored_names = list(
            DocumentMetadata.objects.values_list("file_name", flat=True)
        )
        assert stored_names == ["evil.txt"]
