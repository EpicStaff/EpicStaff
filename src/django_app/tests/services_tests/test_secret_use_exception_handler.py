"""The project exception handler renders a secret Use denial as the 400 a serializer field error gives."""

import pytest
from rest_framework.exceptions import PermissionDenied, ValidationError
from tables.services.secrets import SecretUseDeniedError
from tables.services.secrets.exceptions import (
    IncompletePluginCredentialError,
    ModelEndpointNotSettableError,
)
from utils.exception_handler import custom_exception_handler

_MESSAGE = "Changing the secrets referenced here requires Use."


def test_denial_renders_as_400_envelope_with_field_name():
    response = custom_exception_handler(
        SecretUseDeniedError(field_path=("api_key_secret_id",), message=_MESSAGE), {}
    )

    assert response.status_code == 400
    assert response.data == {
        "status_code": 400,
        "code": "invalid",
        "message": f"api_key_secret_id: {_MESSAGE}",
    }


def test_nested_path_renders_all_segments():
    response = custom_exception_handler(
        SecretUseDeniedError(field_path=("python_code", "secret_ids"), message=_MESSAGE), {}
    )

    assert response.status_code == 400
    assert response.data["message"] == f"python_code: secret_ids: {_MESSAGE}"


@pytest.mark.parametrize(
    ("field_path", "field_errors"),
    [
        (("api_key_secret_id",), {"api_key_secret_id": [_MESSAGE]}),
        (("extra_headers",), {"extra_headers": [_MESSAGE]}),
        (("python_code", "secret_ids"), {"python_code": {"secret_ids": [_MESSAGE]}}),
    ],
    ids=["fk_field", "marker_field", "nested_python_code"],
)
def test_denial_renders_like_the_validation_error_write_points_raised_before(
    field_path, field_errors
):
    """Write points used to raise ValidationError(field_errors) themselves; clients see no change."""
    denied = custom_exception_handler(
        SecretUseDeniedError(field_path=field_path, message=_MESSAGE), {}
    )
    translated = custom_exception_handler(ValidationError(field_errors), {})

    assert denied.status_code == translated.status_code
    assert denied.data == translated.data


def test_endpoint_refusal_renders_like_the_validation_error_raised_before():
    """The endpoint rule used to raise ValidationError({field: message}) per changed field."""
    refused = custom_exception_handler(
        ModelEndpointNotSettableError(fields=("base_url", "deployment_id")), {}
    )
    translated = custom_exception_handler(
        ValidationError(dict.fromkeys(("base_url", "deployment_id"), ModelEndpointNotSettableError.message)),
        {},
    )

    assert refused.status_code == translated.status_code == 400
    assert refused.data == translated.data


def test_incomplete_plugin_credential_renders_like_the_permission_denied_raised_before():
    refused = custom_exception_handler(IncompletePluginCredentialError(), {})
    translated = custom_exception_handler(
        PermissionDenied(IncompletePluginCredentialError.message), {}
    )

    assert refused.status_code == translated.status_code == 403
    assert refused.data == translated.data
