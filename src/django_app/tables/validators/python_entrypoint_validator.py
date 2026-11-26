import keyword

from django.core.exceptions import ValidationError


def validate_python_entrypoint(value: str) -> None:
    """Reject an entrypoint that is not a plain Python name, which the sandbox refuses to run."""
    if not value.isidentifier() or keyword.iskeyword(value):
        raise ValidationError("Must be a Python function name.", code="invalid")
