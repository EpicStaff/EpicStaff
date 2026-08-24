class GraphRAGUnavailableError(RuntimeError):
    """Raised when GraphRAG is requested on a host that can't run it."""


class InvalidDocumentFileNameError(ValueError):
    """Raised when a document's file_name is a path instead of a plain name."""
