from rest_framework.exceptions import APIException


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
