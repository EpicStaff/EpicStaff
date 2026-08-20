from typing import List, Dict, Any
from django.db import models
from django.db import transaction
from django.core.files.uploadedfile import UploadedFile
from loguru import logger

from tables.models import SourceCollection, DocumentMetadata, DocumentContent
from tables.constants.knowledge_constants import (
    MAX_FILE_SIZE,
    ALLOWED_FILE_TYPES,
)
from tables.exceptions import (
    DocumentUploadException,
    FileSizeExceededException,
    InvalidFileTypeException,
    CollectionNotFoundException,
    NoFilesProvidedException,
    DocumentNotFoundException,
    InvalidCollectionIdException,
)


class DocumentManagementService:
    """
    Service for handling document upload operations.

    Responsibilities:
    - Validate uploaded files (size, type)
    - Create DocumentMetadata and DocumentContent records
    - Handle bulk operations
    - Update collection status
    """

    @staticmethod
    def validate_file(uploaded_file: UploadedFile) -> Dict[str, Any]:
        """
        Validate a single uploaded file.

        Args:
            uploaded_file: Django UploadedFile object

        Returns:
            dict: Validated file metadata

        Raises:
            FileSizeExceededException: If file size exceeds limit
            InvalidFileTypeException: If file type is not allowed
        """
        file_name = uploaded_file.name
        file_size = uploaded_file.size

        # Validate file size
        if file_size > MAX_FILE_SIZE:
            max_size_mb = MAX_FILE_SIZE / (1024 * 1024)
            raise FileSizeExceededException(file_name, max_size_mb)

        # Extract and validate file extension
        file_type = file_name.split(".")[-1].lower() if "." in file_name else ""

        if file_type not in ALLOWED_FILE_TYPES:
            raise InvalidFileTypeException(file_name, file_type)

        return {"file_name": file_name, "file_size": file_size, "file_type": file_type}

    @staticmethod
    def validate_files_batch(
        uploaded_files: List[UploadedFile],
    ) -> List[Dict[str, Any]]:
        """
        Validate multiple uploaded files.

        Args:
            uploaded_files: List of Django UploadedFile objects

        Returns:
            list: List of validated file metadata dictionaries

        Raises:
            NoFilesProvidedException: If no files provided
            FileSizeExceededException: If any file exceeds size limit
            InvalidFileTypeException: If any file has invalid type
        """
        if not uploaded_files:
            raise NoFilesProvidedException()

        validated_files = []
        errors = []

        for idx, uploaded_file in enumerate(uploaded_files):
            try:
                validated_data = DocumentManagementService.validate_file(uploaded_file)
                validated_files.append(
                    {"index": idx, "uploaded_file": uploaded_file, **validated_data}
                )
            except (FileSizeExceededException, InvalidFileTypeException) as e:
                errors.append(
                    {"index": idx, "file_name": uploaded_file.name, "error": str(e)}
                )

        # If there are any validation errors, raise exception with all errors
        if errors:
            error_messages = [f"[{e['index']}] {e['error']}" for e in errors]
            raise DocumentUploadException(("\n".join(error_messages)))

        return validated_files

    @staticmethod
    def get_collection(collection_id: int) -> SourceCollection:
        """
        Get source collection by ID.

        Args:
            collection_id: ID of the source collection

        Returns:
            SourceCollection: The source collection instance

        Raises:
            CollectionNotFoundException: If collection not found
        """
        try:
            return SourceCollection.objects.get(collection_id=collection_id)
        except SourceCollection.DoesNotExist:
            raise CollectionNotFoundException(collection_id)

    @staticmethod
    def create_document_metadata(
        collection: SourceCollection,
        document_content: DocumentContent,
        file_name: str,
        file_type: str,
        file_size: int,
    ) -> DocumentMetadata:
        """
        Create DocumentMetadata record.

        Args:
            collection: SourceCollection instance
            file_name: Name of the file
            file_type: Type of the file
            file_size: Size of the file in bytes

        Returns:
            DocumentMetadata: Created document metadata instance
        """
        return DocumentMetadata.objects.create(
            source_collection=collection,
            document_content=document_content,
            file_name=file_name,
            file_type=file_type,
            file_size=file_size,
        )

    @staticmethod
    def create_document_content(uploaded_file: UploadedFile) -> DocumentContent:
        """
        Create DocumentContent record with binary file content.

        Args:
            document_metadata: DocumentMetadata instance
            uploaded_file: Django UploadedFile object

        Returns:
            DocumentContent: Created document content instance
        """
        # Read file content as bytes
        file_content = uploaded_file.read()

        return DocumentContent.objects.create(content=file_content)

    @staticmethod
    @transaction.atomic
    def upload_file(
        collection_id: int, uploaded_file: UploadedFile
    ) -> DocumentMetadata:
        """
        Upload a single file to a collection.

        Args:
            collection_id: ID of the source collection
            uploaded_file: Django UploadedFile object

        Returns:
            DocumentMetadata: Created document metadata instance

        Raises:
            CollectionNotFoundException: If collection not found
            FileSizeExceededException: If file size exceeds limit
            InvalidFileTypeException: If file type is not allowed
        """
        # Validate file
        validated_data = DocumentManagementService.validate_file(uploaded_file)

        # Get collection
        collection = DocumentManagementService.get_collection(collection_id)

        # Create content
        document_content = DocumentManagementService.create_document_content(
            uploaded_file=uploaded_file
        )

        # Create metadata
        document_metadata = DocumentManagementService.create_document_metadata(
            collection=collection,
            document_content=document_content,
            file_name=validated_data["file_name"],
            file_type=validated_data["file_type"],
            file_size=validated_data["file_size"],
        )

        logger.info(
            f"Successfully uploaded file '{validated_data['file_name']}' "
            f"to collection {collection_id}"
        )

        return document_metadata

    @staticmethod
    @transaction.atomic
    def upload_files_batch(
        collection_id: int, uploaded_files: List[UploadedFile]
    ) -> List[DocumentMetadata]:
        """
        Upload multiple files to a collection in a single transaction.

        Args:
            collection_id: ID of the source collection
            uploaded_files: List of Django UploadedFile objects

        Returns:
            list: List of created DocumentMetadata instances

        Raises:
            CollectionNotFoundException: If collection not found
            NoFilesProvidedException: If no files provided
            FileSizeExceededException: If any file exceeds size limit
            InvalidFileTypeException: If any file has invalid type
        """
        # Validate all files first
        validated_files = DocumentManagementService.validate_files_batch(uploaded_files)

        # Get collection
        collection = DocumentManagementService.get_collection(collection_id)

        # Update collection status to uploading
        collection.status = SourceCollection.SourceCollectionStatus.UPLOADING
        collection.save(update_fields=["status", "updated_at"])

        created_documents = []

        try:
            for validated_file in validated_files:
                # Create content
                document_content = DocumentManagementService.create_document_content(
                    uploaded_file=validated_file["uploaded_file"],
                )
                # Create metadata
                document_metadata = DocumentManagementService.create_document_metadata(
                    collection=collection,
                    document_content=document_content,
                    file_name=validated_file["file_name"],
                    file_type=validated_file["file_type"],
                    file_size=validated_file["file_size"],
                )

                created_documents.append(document_metadata)

            logger.info(
                f"Successfully uploaded {len(created_documents)} files "
                f"to collection {collection_id}"
            )

        except Exception as e:
            logger.error(
                f"Error uploading files to collection {collection_id}: {str(e)}"
            )
            raise

        # Collection status will be updated automatically by DocumentMetadata.save()

        return created_documents

    @staticmethod
    @transaction.atomic
    def delete_document(document_id: int) -> Dict[str, Any]:
        """
        Delete a single document metadata.
        If DocumentContent has no other references, it will be deleted too.

        Args:
            document_id: ID of the document to delete

        Returns:
            dict: Information about deleted document

        Raises:
            DocumentNotFoundException: If document not found
        """
        try:
            document = DocumentMetadata.objects.get(document_id=document_id)
        except DocumentMetadata.DoesNotExist:
            raise DocumentNotFoundException(document_id)

        file_name = document.file_name
        collection_id = (
            document.source_collection.collection_id
            if document.source_collection
            else None
        )

        content = document.document_content
        document.delete()

        if content and not content.metadata_records.exists():
            content.delete()
            logger.info(f"Deleted dangling content for document '{file_name}'")

        logger.info(f"Successfully deleted document '{file_name}' (ID: {document_id})")

        return {
            "document_id": document_id,
            "file_name": file_name,
            "collection_id": collection_id,
        }

    @staticmethod
    @transaction.atomic
    def delete_documents_batch(document_ids: List[int]) -> Dict[str, Any]:
        """
        Delete multiple documents in a single transaction.
        DocumentContent instances with no remaining references are deleted too.

        Args:
            document_ids: List of document IDs to delete

        Returns:
            dict: Summary of deletion operation

        Raises:
            DocumentNotFoundException: If any document not found
        """
        if not document_ids:
            return {"deleted_count": 0, "document_ids": [], "errors": []}

        # Fetch all documents
        documents = DocumentMetadata.objects.filter(
            document_id__in=document_ids
        ).select_related("source_collection", "document_content")

        found_ids = [doc.document_id for doc in documents]
        missing_ids = list(set(document_ids) - set(found_ids))

        # Raise error if any documents not found
        if missing_ids:
            logger.warning(f"Can not find and delete documents with IDs: {missing_ids}")

        # Store info before deletion
        deleted_info = [
            {
                "document_id": doc.document_id,
                "file_name": doc.file_name,
                "collection_id": (
                    doc.source_collection.collection_id
                    if doc.source_collection
                    else None
                ),
            }
            for doc in documents
        ]

        content_ids = [
            doc.document_content_id for doc in documents if doc.document_content_id
        ]

        # Delete all documents
        _, details = documents.delete()
        deleted_count = details.get(DocumentMetadata._meta.label, 0)

        # Delete dangling content
        dangling_content = (
            DocumentContent.objects.filter(id__in=content_ids)
            .annotate(ref_count=models.Count("metadata_records"))
            .filter(ref_count=0)
        )

        dangling_count = dangling_content.count()
        if dangling_count > 0:
            dangling_content.delete()
            logger.info(f"Deleted {dangling_count} dangling content records")

        logger.info(f"Successfully deleted {deleted_count} documents: {found_ids}")

        return {
            "deleted_count": deleted_count,
            "documents": deleted_info,
        }

    @staticmethod
    def get_documents_list(collection_id: str = None) -> models.QuerySet:
        """
        Get list of documents, optionally filtered by collection.
        """
        queryset = DocumentMetadata.objects.select_related("source_collection")

        if collection_id:
            try:
                collection_id_int = int(collection_id)
            except (ValueError, TypeError):
                raise InvalidCollectionIdException(collection_id)

            collection_exists = SourceCollection.objects.filter(
                collection_id=collection_id_int
            ).exists()

            if not collection_exists:
                logger.warning(f"Collection {collection_id_int} not found")
                raise CollectionNotFoundException(collection_id_int)

            queryset = queryset.filter(source_collection_id=collection_id_int)
            logger.info(f"Filtering documents by collection {collection_id_int}")

        return queryset
