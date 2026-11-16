from rest_framework.exceptions import APIException


class CustomAPIExeption(APIException):
    """
    A custom API exception class with dynamic status code support.

    Extends the `APIException` class provided by Django REST Framework and adds
    the ability to dynamically set a `status_code` when the exception is raised.

    Inherit from this to create custom API exceptions"""

    # Extra top-level keys for the error response; the handler's envelope keys win.
    extra_response_data: dict | None = None

    def __init__(self, detail=None, code=None, status_code=None):
        if status_code is not None:
            self.status_code = status_code
        super().__init__(detail=detail, code=code)


class DatabasePoolExhaustedError(CustomAPIExeption):
    """No pooled database connection freed up within the pool timeout.

    The request did nothing wrong and is worth repeating once the load drops, hence 503
    with Retry-After rather than the generic 500.
    """

    status_code = 503
    default_detail = "The server is busy. Please retry shortly."
    default_code = "database_pool_exhausted"
    # Clients retrying sooner add to the burst that held every connection.
    RETRY_AFTER_SECONDS = 5

    def __init__(self):
        super().__init__()
        self.headers = {"Retry-After": str(self.RETRY_AFTER_SECONDS)}
