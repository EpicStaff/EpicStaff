"""Every error answer is `{type, errors: [{code, detail, attr, context}]}`, whatever raised it."""

import logging

import pytest
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed, NotFound, ValidationError
from rest_framework_simplejwt.exceptions import InvalidToken

from utils.exception_handler import custom_exception_handler
from utils.exceptions import CustomAPIExeption


class _BlockedError(CustomAPIExeption):
    status_code = 409
    default_detail = "Something blocks this."
    default_code = "something_blocked"

    def __init__(self, context):
        super().__init__()
        self.context = context


class _PromptSerializer(serializers.Serializer):
    result_variable = serializers.CharField()


class _NodeSerializer(serializers.Serializer):
    name = serializers.CharField()
    prompt_configs = _PromptSerializer(many=True)

    def validate(self, attrs):
        raise serializers.ValidationError("The node as a whole is wrong.")


def _validation_error(serializer) -> ValidationError:
    assert not serializer.is_valid()
    return ValidationError(serializer.errors)


def test_an_exception_renders_one_item_with_every_key():
    response = custom_exception_handler(NotFound("No Graph matches the given query."), {})

    assert response.status_code == 404
    assert response.data == {
        "type": "client_error",
        "errors": [
            {
                "code": "not_found",
                "detail": "No Graph matches the given query.",
                "attr": None,
                "context": None,
            }
        ],
    }


def test_context_goes_on_the_item():
    blocker = {"registration_blocker": {"code": "why", "message": "Because."}}

    response = custom_exception_handler(_BlockedError(blocker), {})

    assert response.status_code == 409
    assert response.data["errors"] == [
        {
            "code": "something_blocked",
            "detail": "Something blocks this.",
            "attr": None,
            "context": blocker,
        }
    ]


def test_a_nested_serializer_names_each_field_by_its_dotted_path():
    error = _validation_error(
        _NodeSerializer(data={"name": "", "prompt_configs": [{"result_variable": "ok"}, {}]})
    )

    response = custom_exception_handler(error, {})

    assert response.status_code == 400
    assert [(item["attr"], item["code"]) for item in response.data["errors"]] == [
        ("name", "blank"),
        ("prompt_configs.1.result_variable", "required"),
    ]


def test_non_field_errors_name_no_field():
    serializer = _NodeSerializer(data={"name": "Node", "prompt_configs": []})

    response = custom_exception_handler(_validation_error(serializer), {})

    assert response.data["errors"] == [
        {
            "code": "invalid",
            "detail": "The node as a whole is wrong.",
            "attr": None,
            "context": None,
        }
    ]


def test_a_code_given_to_the_error_is_kept():
    response = custom_exception_handler(
        ValidationError({"embedder_id": ["Embedder with id 9 not found"]}, code="embedder_not_found"),
        {},
    )

    assert response.data["errors"] == [
        {
            "code": "embedder_not_found",
            "detail": "Embedder with id 9 not found",
            "attr": "embedder_id",
            "context": None,
        }
    ]


def test_an_empty_detail_falls_back_to_the_default_so_errors_is_never_empty():
    response = custom_exception_handler(ValidationError({}), {})

    assert response.data["errors"] == [
        {"code": "invalid", "detail": "Invalid input.", "attr": None, "context": None}
    ]


def test_a_rejected_jwt_is_one_item_with_the_token_code():
    response = custom_exception_handler(
        InvalidToken(
            {
                "detail": "Given token not valid for any token type",
                "messages": [
                    {
                        "token_class": "AccessToken",
                        "token_type": "access",
                        "message": "Token is expired",
                    }
                ],
            }
        ),
        {},
    )

    assert response.status_code == 401
    assert response.data["errors"] == [
        {
            "code": "token_not_valid",
            "detail": "Given token not valid for any token type",
            "attr": None,
            "context": None,
        }
    ]


def test_a_plain_authentication_failure_keeps_its_code():
    response = custom_exception_handler(AuthenticationFailed("Invalid API key"), {})

    assert response.status_code == 401
    assert response.data["errors"] == [
        {
            "code": "authentication_failed",
            "detail": "Invalid API key",
            "attr": None,
            "context": None,
        }
    ]


def test_an_unhandled_error_is_unknown_with_a_fixed_text(monkeypatch, caplog):
    monkeypatch.setattr("utils.exception_handler.DEBUG", False)
    error = RuntimeError('relation "tables_secret" does not exist at character 15')

    with caplog.at_level(logging.ERROR, logger="django.request"):
        response = custom_exception_handler(error, {})

    assert response.status_code == 500
    assert response.content == (
        b'{"type": "server_error", "errors": [{"code": "unknown", '
        b'"detail": "Internal server error.", "attr": null, "context": null}]}'
    )
    assert [
        record.exc_info[1] for record in caplog.records if record.name == "django.request"
    ] == [error]


@pytest.mark.parametrize("status_code", [500, 503])
def test_a_server_error_raised_on_purpose_keeps_its_code(status_code):
    error = CustomAPIExeption("Tool execution failed.", code="tool_failed", status_code=status_code)

    response = custom_exception_handler(error, {})

    assert response.status_code == status_code
    assert response.data["type"] == "server_error"
    assert response.data["errors"][0]["code"] == "tool_failed"
