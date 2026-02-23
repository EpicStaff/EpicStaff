from rest_framework.exceptions import APIException
from tables.constants.knowledge_constants import (
    ALLOWED_FILE_TYPES,
)


class CustomAPIExeption(APIException):
    """
    A custom API exception class with dynamic status code support.

    Extends the `APIException` class provided by Django REST Framework and adds
    the ability to dynamically set a `status_code` when the exception is raised.

    Inherit from this to create custom API exceptions"""

    def __init__(self, detail=None, code=None, status_code=None):
        if status_code is not None:
            self.status_code = status_code
        super().__init__(detail=detail, code=code)


class ToolConfigSerializerError(CustomAPIExeption):
    status_code = 400
    default_detail = "Error occured in ToolConfigSerializer"
    default_code = "tool_config_serializer_error"


class GraphEntryPointException(CustomAPIExeption):
    status_code = 400
    default_detail = "No node connected to start node"


class UploadSourceCollectionSerializerValidationError(CustomAPIExeption):
    status_code = 400
    default_detail = "ValidationError occured in UploadSourceCollectionSerializer"


class CrewMemoryValidationError(CustomAPIExeption):
    status_code = 400
    default_detail = "ValidationError occured in CrewMemoryValidator -> ConverterService during asigning memory_llm or embedder"


class TaskValidationError(CustomAPIExeption):
    status_code = 400
    default_detail = "ValidationError occured in TaskValidator -> ConverterService during validate crews' tasks"


class TaskSerializerError(CustomAPIExeption):
    status_code = 400
    default_detail = "SerializerError occured during Task serialization"


class AgentSerializerError(CustomAPIExeption):
    status_code = 400
    default_detail = "SerializerError occurred during Agent serialization"


class EndNodeValidationError(CustomAPIExeption):
    status_code = 400
    default_detail = "ValidationError occured in session_manager_service"


class FileNodeValidationError(CustomAPIExeption):
    status_code = 400
    default_detail = "FileExtractorNode requires input arguments"


class InvalidTaskOrderError(CustomAPIExeption):
    status_code = 409
    default_detail = "A task cannot be placed before its context dependency. Please reorder the tasks or delete context."
    default_code = "invalid_context_task_order"


class SubGraphValidationError(CustomAPIExeption):
    status_code = 400
    default_detail = (
        "ValidationError occured in SubGraphValidator during subgraph validation"
    )


class BuiltInToolModificationError(CustomAPIExeption):
    """
    Exception raised when someone tries to modify a built-in PythonCodeTool.
    """

    def __init__(self, detail="Unable to remove built-in tools", code=None):
        super().__init__(detail=detail, code=code, status_code=400)


class RegisterTelegramTriggerError(CustomAPIExeption):
    status_code = 400
    default_detail = "Error occurred while registering Telegram trigger"


class PythonCodeToolConfigSerializerError(CustomAPIExeption):
    """
    Exception raised when someone tries to modify a built-in PythonCodeToolConfig.
    """

    def __init__(
        self,
        detail="ValidationError occured in PythonCodeToolConfigSerializer",
        code=None,
    ):
        super().__init__(detail=detail, code=code, status_code=400)


class DocumentUploadException(CustomAPIExeption):
    """Base exception for document upload errors."""

    pass


class FileSizeExceededException(DocumentUploadException):
    """Raised when file size exceeds the allowed limit."""

    def __init__(self, file_name, max_size_mb):
        self.file_name = file_name
        self.max_size_mb = max_size_mb
        super().__init__(
            f"File '{file_name}' exceeds the maximum allowed size of {max_size_mb}MB"
        )


class InvalidFileTypeException(DocumentUploadException):
    """Raised when file type is not allowed."""

    def __init__(self, file_name, file_extension):
        self.file_name = file_name
        self.file_extension = file_extension
        super().__init__(
            f"File '{file_name}' has invalid type '.{file_extension}'. "
            f"Allowed types: {', '.join(ALLOWED_FILE_TYPES)}"
        )


class CollectionNotFoundException(DocumentUploadException):
    """Raised when source collection is not found."""

    def __init__(self, collection_id):
        self.collection_id = collection_id
        super().__init__(f"Source collection with id {collection_id} not found")


class NoFilesProvidedException(DocumentUploadException):
    """Raised when no files are provided for upload."""

    def __init__(self):
        super().__init__("No files provided for upload")


class DocumentNotFoundException(DocumentUploadException):
    """Raised when document is not found."""

    def __init__(self, document_id):
        self.document_id = document_id
        super().__init__(f"Document with id {document_id} not found")


class InvalidCollectionIdException(DocumentUploadException):
    """Raised when collection_id parameter is invalid."""

    def __init__(self, collection_id_value):
        self.collection_id_value = collection_id_value
        super().__init__(
            f"Invalid collection_id: '{collection_id_value}'. Must be a valid integer."
        )


class InvalidFieldType(CustomAPIExeption):
    """Raised when a field has invalid type"""

    status_code = 400

    def __init__(self, field_name, field_value, expected_type="integer"):
        self.field_name = field_name
        self.field_value = field_value
        self.expected_type = expected_type
        super().__init__(
            f"Invalid {field_name}: '{field_value}'. Must be a valid {expected_type}."
        )


class RagException(CustomAPIExeption):
    """Base exception for RAG operations."""

    status_code = 400
    default_detail = "RAG operation error"
    default_code = "rag_error"


class RagTypeNotFoundException(RagException):
    """Raised when RAG type is not found."""

    def __init__(self, rag_type_id):
        self.rag_type_id = rag_type_id
        super().__init__(f"RAG type with id {rag_type_id} not found")


class NaiveRagNotFoundException(RagException):
    """Raised when NaiveRag is not found."""

    def __init__(self, naive_rag_id):
        self.naive_rag_id = naive_rag_id
        super().__init__(f"NaiveRag with id {naive_rag_id} not found")


class DocumentConfigNotFoundException(RagException):
    """Raised when document config is not found."""

    def __init__(self, config_id):
        self.config_id = config_id
        super().__init__(f"Document config with id {config_id} not found")


class EmbedderNotFoundException(RagException):
    """Raised when embedder is not found."""

    def __init__(self, embedder_id):
        self.embedder_id = embedder_id
        super().__init__(f"Embedder with id {embedder_id} not found")


class InvalidChunkParametersException(RagException):
    """Raised when chunk parameters are invalid."""

    pass


class DocumentsNotFoundException(RagException):
    """Raised when documents are not found."""

    def __init__(self, document_ids):
        self.document_ids = document_ids
        super().__init__(f"Documents not found: {', '.join(map(str, document_ids))}")


class NaiveRagAlreadyExistsException(RagException):
    """Raised when trying to create NaiveRag but it already exists."""

    def __init__(self, collection_id):
        self.collection_id = collection_id
        super().__init__(
            f"NaiveRag already exists for collection {collection_id}. Use update endpoint instead."
        )


class RagNotReadyForIndexingException(RagException):
    """Raised when RAG configuration is not ready for indexing."""

    def __init__(self, message: str):
        super().__init__(message)


class GraphRagNotImplementedException(RagException):
    """GraphRag not yet implemented."""

    def __init__(self):
        super().__init__("GraphRag is not yet implemented")


class AgentMissingCollectionException(RagException):
    """Raised when attempting to assign RAG to agent without knowledge_collection."""

    def __init__(self):
        super().__init__("Agent must have a knowledge_collection to assign RAG")


class RagCollectionMismatchException(RagException):
    """Raised when RAG doesn't belong to agent's knowledge_collection."""

    def __init__(self, rag_type, rag_id, collection_id):
        self.rag_type = rag_type
        self.rag_id = rag_id
        self.collection_id = collection_id
        super().__init__(
            f"{rag_type.capitalize()}Rag {rag_id} does not belong to agent's "
            f"knowledge_collection (collection_id={collection_id})"
        )


class UnknownRagTypeException(RagException):
    """Raised when unknown RAG type is provided."""

    def __init__(self, rag_type):
        self.rag_type = rag_type
        super().__init__(f"Unknown RAG type: '{rag_type}'")
