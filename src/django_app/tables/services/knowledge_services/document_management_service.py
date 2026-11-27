import hashlib
import json
from typing import Any

from django.core.files.uploadedfile import UploadedFile
from django.db import models, transaction
from loguru import logger
from rest_framework import serializers
from src.shared.models import UserAction
from tables.constants.knowledge_constants import (
    ALLOWED_FILE_TYPES,
    EDITABLE_FILE_TYPES,
    DocumentContentScope,
)
from tables.constants.upload_limits import default_upload_limits
from tables.exceptions import (
    CollectionNotFoundException,
    ContentHashConflictError,
    DocumentContentMissingException,
    DocumentIndexingInProgressException,
    DocumentNotEditableException,
    DocumentNotFoundException,
    DocumentsNotFoundException,
    FileSizeExceededException,
    InvalidCollectionIdException,
    InvalidFileTypeException,
    NoFilesProvidedException,
    UploadRejectedException,
)
from tables.models import DocumentContent, DocumentMetadata, SourceCollection
from tables.models.knowledge_models import GraphRagDocument, NaiveRag
from tables.services.knowledge_services.collection_last_edit import record_collection_edits
from tables.services.knowledge_services.document_content_storage import DocumentContentStorage
from tables.services.knowledge_services.graph_rag_service import GraphRagService
from tables.services.knowledge_services.naive_rag_service import NaiveRagService
from tables.validators.file_upload_validator import FileValidator
from user_audit.context import mark_request_handled
from user_audit.recorder import record_user_action


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
    def validate_file(uploaded_file: UploadedFile) -> dict[str, Any]:
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
        return DocumentManagementService.validate_file_metadata(
            uploaded_file.name, uploaded_file.size
        )

    @staticmethod
    def validate_file_metadata(file_name: str, file_size: int) -> dict[str, Any]:
        """Check a file's size and extension against the document upload rules.

        Needs no file bytes, so callers holding only metadata (e.g. storage rows)
        can pre-screen files before fetching their content.

        Returns:
            ``{"file_name", "file_size", "file_type"}``.

        Raises:
            FileSizeExceededException: The size is over ``MAX_UPLOAD_FILE_SIZE``.
            InvalidFileTypeException: The extension is not in ``ALLOWED_FILE_TYPES``.
        """
        # Validate file size
        max_file_bytes = default_upload_limits().max_file_bytes
        if file_size > max_file_bytes:
            raise FileSizeExceededException(file_name, max_file_bytes / (1024 * 1024))

        file_type = DocumentManagementService.validate_file_type(file_name)
        return {"file_name": file_name, "file_size": file_size, "file_type": file_type}

    @staticmethod
    def validate_file_type(file_name: str) -> str:
        """Return the file's document type, from its extension.

        Raises:
            InvalidFileTypeException: The extension is not in ``ALLOWED_FILE_TYPES``.
        """
        file_type = file_name.split(".")[-1].lower() if "." in file_name else ""
        if file_type not in ALLOWED_FILE_TYPES:
            raise InvalidFileTypeException(file_name, file_type)
        return file_type

    @staticmethod
    def validate_files_batch(
        uploaded_files: list[UploadedFile],
    ) -> list[dict[str, Any]]:
        """
        Validate multiple uploaded files.

        Args:
            uploaded_files: List of Django UploadedFile objects

        Returns:
            list: List of validated file metadata dictionaries

        Raises:
            NoFilesProvidedException: If no files provided
            UploadRejectedException: If any file is too large or of an invalid
                type, or ``FileValidator`` rejects the batch; the message lists
                every problem
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
                errors.append({"index": idx, "file_name": uploaded_file.name, "error": str(e)})

        try:
            FileValidator().validate(uploaded_files)
        except serializers.ValidationError as e:
            detail = e.detail if isinstance(e.detail, list) else [e.detail]
            errors.extend({"index": None, "file_name": None, "error": str(item)} for item in detail)

        # If there are any validation errors, raise exception with all errors
        if errors:
            error_messages = [
                f"[{e['index']}] {e['error']}" if e["index"] is not None else e["error"]
                for e in errors
            ]
            raise UploadRejectedException("\n".join(error_messages))

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
        except SourceCollection.DoesNotExist as e:
            raise CollectionNotFoundException(collection_id) from e

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
    def create_document_content(uploaded_file: UploadedFile, *, org_id: int) -> DocumentContent:
        """Store the file's bytes in object storage and create the row pointing at them.

        Raises:
            StorageUnavailable: Object storage could not be reached.
        """
        return DocumentContentStorage.create(org_id, uploaded_file.read())

    @staticmethod
    @transaction.atomic
    def upload_files_batch(
        collection_id: int, uploaded_files: list[UploadedFile], *, user: object | None = None
    ) -> list[DocumentMetadata]:
        """
        Upload multiple files to a collection in a single transaction.

        Args:
            collection_id: ID of the source collection
            uploaded_files: List of Django UploadedFile objects
            user: Acting user, recorded as the collection's last editor. Each document is
                recorded as a `created` user action under the collection.

        Returns:
            list: List of created DocumentMetadata instances

        Raises:
            CollectionNotFoundException: If collection not found
            NoFilesProvidedException: If no files provided
            UploadRejectedException: If any file fails validation
        """
        # Validate all files first
        validated_files = DocumentManagementService.validate_files_batch(uploaded_files)

        # Get collection
        collection = DocumentManagementService.get_collection(collection_id)

        # Update collection status to uploading
        collection.status = SourceCollection.SourceCollectionStatus.UPLOADING
        collection.save(update_fields=["status", "updated_at"])

        created_documents = []
        # Object storage is outside this transaction: on failure the files written so far
        # are deleted here, or they would outlive the rows the rollback removes.
        written_object_keys: list[str] = []

        try:
            for validated_file in validated_files:
                document_content = DocumentManagementService.create_document_content(
                    validated_file["uploaded_file"], org_id=collection.org_id
                )
                written_object_keys.append(document_content.object_key)
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
            logger.error(f"Error uploading files to collection {collection_id}: {e!s}")
            DocumentContentStorage.delete(written_object_keys)
            raise

        # Collection status will be updated automatically by DocumentMetadata.save()
        record_collection_edits([collection_id], user)
        for document in created_documents:
            record_user_action(action=UserAction.CREATED, org_id=collection.org_id, target=document)

        return created_documents

    @staticmethod
    @transaction.atomic
    def upload_new_files_batch(
        collection_id: int,
        uploaded_files: list[UploadedFile],
        *,
        org_id: int,
        user: object | None,
    ) -> tuple[list[DocumentMetadata], list[UploadedFile]]:
        """Upload the files the collection does not already hold, skipping the rest.

        A file is a duplicate when the collection already has a document with the
        same file name and size, or when an earlier file in the same batch has
        them. The collection row is locked (``SELECT ... FOR NO KEY UPDATE``)
        before the duplicate check, so two concurrent batches into one collection
        cannot both insert the same file: the second waits and then sees the
        first's rows.

        Args:
            org_id: The caller's organization. A collection of another
                organization is treated as missing, so this method keeps the
                write in the caller's organization without relying on the caller
                to have checked it.
            user: Acting user, recorded as the collection's last editor when any
                file is uploaded. Has no default so a caller cannot omit it
                unnoticed; None records no edit.

        Returns:
            ``(created documents, duplicate files)``. Nothing is written when every
            file is a duplicate.

        Raises:
            CollectionNotFoundException: The collection does not exist, was
                deleted, or belongs to another organization.
            UploadRejectedException: The non-duplicate files failed validation.
        """
        try:
            # no_key: serializes imports into this collection without blocking
            # other transactions inserting rows that reference it by FK.
            collection = SourceCollection.objects.select_for_update(no_key=True).get(
                collection_id=collection_id, org_id=org_id
            )
        except SourceCollection.DoesNotExist as e:
            raise CollectionNotFoundException(collection_id) from e

        taken_name_sizes = set(collection.documents.values_list("file_name", "file_size"))
        new_files: list[UploadedFile] = []
        duplicate_files: list[UploadedFile] = []
        for uploaded_file in uploaded_files:
            name_size = (uploaded_file.name, uploaded_file.size)
            if name_size in taken_name_sizes:
                duplicate_files.append(uploaded_file)
            else:
                new_files.append(uploaded_file)
                taken_name_sizes.add(name_size)

        if not new_files:
            return [], duplicate_files

        # Runs as a savepoint inside this transaction, so the lock is held
        # until every document is written.
        created_documents = DocumentManagementService.upload_files_batch(
            collection_id=collection_id, uploaded_files=new_files, user=user
        )
        return created_documents, duplicate_files

    @staticmethod
    @transaction.atomic
    def delete_document(document_id: int, *, user: object | None = None) -> dict[str, Any]:
        """
        Delete a single document metadata.
        If DocumentContent has no other references, it will be deleted too.

        Args:
            document_id: ID of the document to delete
            user: Acting user, recorded as the collection's last editor

        Returns:
            dict: Information about deleted document

        Raises:
            DocumentNotFoundException: If document not found
        """
        try:
            document = DocumentMetadata.objects.get(document_id=document_id)
        except DocumentMetadata.DoesNotExist as e:
            raise DocumentNotFoundException(document_id) from e

        file_name = document.file_name
        collection_id = (
            document.source_collection.collection_id if document.source_collection else None
        )

        content = document.document_content
        affected_rags = list(
            NaiveRag.objects.filter(naive_rag_configs__document=document).distinct()
        )

        graph_links = GraphRagDocument.objects.filter(document=document).select_related("graph_rag")
        affected_graph_rags: dict[int, tuple] = {}
        for link in graph_links:
            rag = link.graph_rag
            completed = link.status == GraphRagDocument.Status.COMPLETED
            existing = affected_graph_rags.get(rag.graph_rag_id)
            affected_graph_rags[rag.graph_rag_id] = (
                rag,
                (existing[1] if existing else False) or completed,
            )

        document.delete()

        for rag in affected_rags:
            NaiveRagService.sync_rag_status_after_config_removal(rag)
        for rag, indexed_deleted in affected_graph_rags.values():
            GraphRagService.sync_status_after_document_removal(rag, indexed_deleted)

        if content is not None:
            dangling_object_keys = DocumentContentStorage.delete_unreferenced_rows([content.pk])
            DocumentContentStorage.delete_on_commit(dangling_object_keys)
            if dangling_object_keys:
                logger.info(f"Deleted dangling content for document '{file_name}'")

        logger.info(f"Successfully deleted document '{file_name}' (ID: {document_id})")
        record_collection_edits([collection_id], user)

        return {
            "document_id": document_id,
            "file_name": file_name,
            "collection_id": collection_id,
        }

    @staticmethod
    @transaction.atomic
    def delete_documents_batch(
        document_ids: list[int], *, user: object | None = None
    ) -> dict[str, Any]:
        """
        Delete multiple documents in a single transaction.
        DocumentContent instances with no remaining references are deleted too.

        Args:
            document_ids: List of document IDs to delete
            user: Acting user, recorded as the last editor of every affected collection.
                Each deleted document is recorded as a `deleted` user action.

        Returns:
            dict: Summary of deletion operation

        Raises:
            DocumentNotFoundException: If any document not found
        """
        # Each deleted document records itself; a request that deleted none records nothing.
        mark_request_handled()
        if not document_ids:
            return {"deleted_count": 0, "documents": []}

        # Fetch all documents
        documents = DocumentMetadata.objects.filter(document_id__in=document_ids).select_related(
            "source_collection", "document_content"
        )

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
                    doc.source_collection.collection_id if doc.source_collection else None
                ),
            }
            for doc in documents
        ]

        content_ids = [doc.document_content_id for doc in documents if doc.document_content_id]

        affected_rags = list(
            NaiveRag.objects.filter(naive_rag_configs__document_id__in=found_ids).distinct()
        )

        graph_links = GraphRagDocument.objects.filter(document_id__in=found_ids).select_related(
            "graph_rag"
        )
        affected_graph_rags: dict[int, tuple] = {}
        for link in graph_links:
            rag = link.graph_rag
            completed = link.status == GraphRagDocument.Status.COMPLETED
            existing = affected_graph_rags.get(rag.graph_rag_id)
            affected_graph_rags[rag.graph_rag_id] = (
                rag,
                (existing[1] if existing else False) or completed,
            )

        for document in documents:
            if document.source_collection is not None:
                record_user_action(
                    action=UserAction.DELETED,
                    org_id=document.source_collection.org_id,
                    target=document,
                )

        # Delete all documents
        _, details = documents.delete()
        deleted_count = details.get(DocumentMetadata._meta.label, 0)

        collection_ids = {d["collection_id"] for d in deleted_info if d["collection_id"]}
        for collection in SourceCollection.objects.filter(collection_id__in=collection_ids):
            collection.update_collection_status()
        record_collection_edits(collection_ids, user)
        for rag in affected_rags:
            NaiveRagService.sync_rag_status_after_config_removal(rag)
        for rag, indexed_deleted in affected_graph_rags.values():
            GraphRagService.sync_status_after_document_removal(rag, indexed_deleted)

        dangling_object_keys = DocumentContentStorage.delete_unreferenced_rows(content_ids)
        DocumentContentStorage.delete_on_commit(dangling_object_keys)
        if dangling_object_keys:
            logger.info(f"Deleted {len(dangling_object_keys)} dangling content records")

        logger.info(f"Successfully deleted {deleted_count} documents: {found_ids}")

        return {
            "deleted_count": deleted_count,
            "documents": deleted_info,
        }

    @staticmethod
    def get_document_text(document_id: int, *, org_id: int) -> tuple[DocumentMetadata, str]:
        """Return a text document and its current text, read from the file its loaded content row names.

        The document's `content_hash` and the text come from the same content row, so an
        edit started from them can tell whether the file changed meanwhile.

        Raises:
            DocumentNotFoundException: No such document in the organization.
            DocumentNotEditableException: Not an editable type, or the file is not UTF-8 text.
            DocumentContentMissingException: The file is gone from storage.
            StorageUnavailable: Object storage could not be reached.
        """
        document = (
            DocumentMetadata.objects.select_related("source_collection", "document_content")
            .filter(document_id=document_id, source_collection__org_id=org_id)
            .first()
        )
        if document is None:
            raise DocumentNotFoundException(document_id)
        if document.file_type not in EDITABLE_FILE_TYPES:
            raise DocumentNotEditableException(
                f"'{document.file_name}' is not a text document that can be edited."
            )
        if document.document_content is None:
            raise DocumentContentMissingException()
        data = DocumentContentStorage.read(document.document_content.object_key)
        try:
            # utf-8-sig drops a byte order mark, so the editor saves the file without one.
            return document, data.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise DocumentNotEditableException(
                f"'{document.file_name}' is not UTF-8 text, so it cannot be edited."
            ) from error

    @staticmethod
    def update_document_content(
        document_id: int,
        *,
        org_id: int,
        data: bytes,
        scope: DocumentContentScope,
        expected_hash: str,
        user: object | None,
    ) -> DocumentMetadata:
        """Replace a text document's content and outdate the RAGs that indexed it.

        `scope` decides whether documents of other collections that share the file get
        the new version too; copies in the recycle bin never do. When every document on
        the content row gets the new version, the row is edited in place. The
        new version goes under a new key before the database changes, and the old file
        is deleted after the commit only once no document refers to it. Runs its own
        transaction and refuses to run inside another one: if the transaction fails, the
        commit included, the new file is deleted again.

        Returns:
            The document; unchanged when `data` equals its current content.

        Raises:
            DocumentNotFoundException: No such document in the organization.
            DocumentNotEditableException: Not an editable type, not UTF-8 text, or not
                valid JSON for a JSON document.
            FileSizeExceededException: `data` is over the document upload limit.
            DocumentContentMissingException: The current file is gone from storage.
            ContentHashConflictError: The content is no longer the version
                `expected_hash` names.
            DocumentIndexingInProgressException: A document the edit reaches is being indexed.
            StorageUnavailable: Object storage could not be reached.
        """
        new_key: str | None = None
        try:
            with transaction.atomic(durable=True):
                # Documents first, then their content, the order the delete paths lock them
                # in: a concurrent edit of this document waits here and then sees the content
                # it left.
                document = (
                    DocumentMetadata.objects.select_for_update(of=("self",))
                    .select_related("source_collection")
                    .filter(document_id=document_id, source_collection__org_id=org_id)
                    .first()
                )
                if document is None:
                    raise DocumentNotFoundException(document_id)
                DocumentManagementService._validate_edited_text(document, data)
                if document.document_content_id is None:
                    raise DocumentContentMissingException()
                copies = list(
                    DocumentMetadata.all_objects.select_for_update(of=("self",))
                    .filter(
                        document_content_id=document.document_content_id,
                        source_collection__org_id=org_id,
                    )
                    .exclude(document_id=document.document_id)
                    .values_list("document_id", "active", "source_collection__active")
                )
                # A copy in the recycle bin, alone or with its collection, keeps the file it
                # was binned with, so restoring it brings back what was deleted.
                live_copy_ids = [
                    copy_id
                    for copy_id, active, collection_active in copies
                    if active and collection_active
                ]
                content = (
                    DocumentContent.objects.select_for_update()
                    .filter(pk=document.document_content_id)
                    .first()
                )
                if content is None or not DocumentContentStorage.exists(content.object_key):
                    raise DocumentContentMissingException()
                if content.content_hash != expected_hash:
                    raise ContentHashConflictError(
                        "The document was changed after you opened it. "
                        "Load the current version to edit it."
                    )
                new_hash = hashlib.sha256(data).hexdigest()
                if new_hash == content.content_hash:
                    return document

                affected_ids = [document.document_id]
                if scope == DocumentContentScope.ALL_COLLECTIONS:
                    affected_ids += live_copy_ids
                # In place only when every document on the content row gets the new version.
                in_place = len(affected_ids) == len(copies) + 1
                # Naive before graph, each in id order: two edits lock shared RAGs in one order.
                NaiveRagService.lock_rags_of_documents(affected_ids)
                GraphRagService.lock_rags_of_documents(affected_ids)
                indexing_collections = NaiveRagService.indexing_collection_names(
                    affected_ids
                ) | GraphRagService.indexing_collection_names(affected_ids)
                if indexing_collections:
                    raise DocumentIndexingInProgressException(sorted(indexing_collections))

                if in_place:
                    new_key = DocumentContentStorage.write(org_id, data)
                    old_key = content.object_key
                    content.object_key = new_key
                    content.content_hash = new_hash
                    content.save(update_fields=["object_key", "content_hash"])
                    DocumentContentStorage.delete_on_commit([old_key])
                else:
                    new_content = DocumentContentStorage.create(org_id, data)
                    new_key = new_content.object_key
                    DocumentMetadata.all_objects.filter(document_id__in=affected_ids).update(
                        document_content=new_content
                    )
                affected_documents = DocumentMetadata.all_objects.filter(
                    document_id__in=affected_ids
                )
                affected_documents.update(file_size=len(data))
                NaiveRagService.mark_documents_content_changed(affected_ids)
                GraphRagService.mark_documents_content_changed(affected_ids)
                record_collection_edits(
                    affected_documents.values_list("source_collection_id", flat=True), user
                )
                record_user_action(action=UserAction.UPDATED, org_id=org_id, target=document)
        except Exception:
            # The new file lives outside the transaction a failure rolls back, the commit
            # included.
            # TODO: a process killed between the file write and the commit still leaves
            # the file without a row; sweep unreferenced objects once background jobs run
            # on Celery.
            if new_key is not None:
                DocumentContentStorage.delete([new_key])
            raise

        document.refresh_from_db()
        return document

    @staticmethod
    def _validate_edited_text(document: DocumentMetadata, data: bytes) -> None:
        if document.file_type not in EDITABLE_FILE_TYPES:
            raise DocumentNotEditableException(
                f"'{document.file_name}' is not a text document that can be edited."
            )
        max_file_bytes = default_upload_limits().max_file_bytes
        if len(data) > max_file_bytes:
            raise FileSizeExceededException(document.file_name, max_file_bytes / (1024 * 1024))
        try:
            # utf-8-sig: a JSON file saved with a byte order mark is still valid JSON.
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise DocumentNotEditableException("The new text must be UTF-8.") from error
        if document.file_type == DocumentMetadata.DocumentFileType.JSON:
            try:
                json.loads(text)
            except json.JSONDecodeError as error:
                raise DocumentNotEditableException(
                    f"'{document.file_name}' must stay valid JSON."
                ) from error

    @staticmethod
    def get_documents_list(collection_id: str | None = None) -> models.QuerySet:
        """
        Get list of documents, optionally filtered by collection.
        """
        queryset = DocumentMetadata.objects.select_related("source_collection")

        if collection_id:
            try:
                collection_id_int = int(collection_id)
            except (ValueError, TypeError) as e:
                raise InvalidCollectionIdException(collection_id) from e

            collection_exists = SourceCollection.objects.filter(
                collection_id=collection_id_int
            ).exists()

            if not collection_exists:
                logger.warning(f"Collection {collection_id_int} not found")
                raise CollectionNotFoundException(collection_id_int)

            queryset = queryset.filter(source_collection_id=collection_id_int)
            logger.info(f"Filtering documents by collection {collection_id_int}")

        return queryset

    @staticmethod
    def get_documents_with_content(
        document_ids: list[int],
        *,
        org_id: int,
    ) -> list[DocumentMetadata]:
        """
        Fetch an organization's documents by ID with their content rows,
        preserving request order.

        Raises:
            DocumentsNotFoundException: If any requested document is missing or
                belongs to another organization — the two are indistinguishable.
        """
        documents_by_id = (
            DocumentMetadata.objects.select_related("document_content")
            .filter(source_collection__org_id=org_id)
            .in_bulk(document_ids)
        )
        missing_ids = [doc_id for doc_id in document_ids if doc_id not in documents_by_id]
        if missing_ids:
            raise DocumentsNotFoundException(missing_ids)

        return [documents_by_id[doc_id] for doc_id in document_ids]

    @staticmethod
    @transaction.atomic
    def copy_documents_to_collection(
        collection_id: int, document_ids: list[int], *, org_id: int, user: object | None = None
    ) -> tuple[list[DocumentMetadata], list[DocumentMetadata]]:
        """Copy documents into a collection, sharing their binary content.

        Documents already present (by content), duplicate ids and copies into the source
        collection are skipped; `user` last edits the collection when anything was copied.
        Each new copy is recorded as a `copied` user action under the target collection,
        its source's name as the previous name; a copy that skipped everything records
        nothing.
        The target collection and every source document must belong to ``org_id``.
        Returns (copied, skipped).

        Raises:
            CollectionNotFoundException: target collection missing or in another org.
            DocumentsNotFoundException: a source document missing or in another org.
        """
        collection = SourceCollection.objects.filter(
            collection_id=collection_id, org_id=org_id
        ).first()
        if collection is None:
            raise CollectionNotFoundException(collection_id)
        source_documents = DocumentManagementService.get_documents_with_content(
            document_ids, org_id=org_id
        )

        existing_content_ids = set(
            DocumentMetadata.objects.filter(source_collection=collection).values_list(
                "document_content_id", flat=True
            )
        )

        copied_documents: list[DocumentMetadata] = []
        skipped_documents: list[DocumentMetadata] = []
        source_names: list[str] = []
        for source_doc in source_documents:
            if source_doc.document_content_id in existing_content_ids:
                skipped_documents.append(source_doc)
                continue

            copied_documents.append(
                DocumentManagementService.create_document_metadata(
                    collection=collection,
                    document_content=source_doc.document_content,
                    file_name=source_doc.file_name,
                    file_type=source_doc.file_type,
                    file_size=source_doc.file_size,
                )
            )
            source_names.append(source_doc.file_name)
            existing_content_ids.add(source_doc.document_content_id)

        logger.info(
            f"Copied {len(copied_documents)} document(s) into collection "
            f"{collection_id}, skipped {len(skipped_documents)} already present"
        )
        if copied_documents:
            record_collection_edits([collection_id], user)
        for copied, source_name in zip(copied_documents, source_names, strict=True):
            record_user_action(
                action=UserAction.COPIED, org_id=org_id, target=copied, previous_name=source_name
            )
        if not copied_documents:
            mark_request_handled()

        return copied_documents, skipped_documents
