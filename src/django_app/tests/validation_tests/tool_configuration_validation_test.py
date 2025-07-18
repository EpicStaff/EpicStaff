import pytest
from tables.validators.tool_config_validator import ToolConfigValidator
from tests.fixtures import *
from django.core.exceptions import ValidationError


@pytest.mark.django_db
def test_partial_tool_configuration_validation_with_all_fields_set(
    test_tool_with_fields, llm_config, embedding_config
):
    tool = test_tool_with_fields
    name = "tool_configuration_validation config"
    configuration = {
        "llm_config": llm_config.pk,
        "embedding_config": embedding_config.pk,
        "url": "http://some-url.com",
    }
    validator = ToolConfigValidator(
        validate_null_fields=False, validate_missing_reqired_fields=False
    )

    validator.validate(name=name, tool=tool, configuration=configuration)


@pytest.mark.django_db
def test_partial_tool_configuration_validation_without_all_fields_set(
    test_tool_with_fields, llm_config, embedding_config
):
    tool = test_tool_with_fields
    name = "tool_configuration_validation config"
    configuration = {
        "embedding_config": None,
    }
    validator = ToolConfigValidator(
        validate_null_fields=False, validate_missing_reqired_fields=False
    )

    validator.validate(name=name, tool=tool, configuration=configuration)


@pytest.mark.django_db
def test_full_configuration_validation_with_all_fields_set(
    test_tool_with_fields, llm_config, embedding_config
):
    tool = test_tool_with_fields
    name = "tool_configuration_validation config"
    configuration = {
        "llm_config": llm_config.pk,
        "embedding_config": embedding_config.pk,
        "url": "http://some-url.com",
    }
    validator = ToolConfigValidator(
        validate_null_fields=True, validate_missing_reqired_fields=True
    )

    validator.validate(name=name, tool=tool, configuration=configuration)


@pytest.mark.django_db
def test_full_configuration_validation_invalid(
    test_tool_with_fields, llm_config, embedding_config
):
    tool = test_tool_with_fields
    name = "tool_configuration_validation config"
    configuration = {
        "llm_config": None,
        "embedding_config": "str",
    }
    validator = ToolConfigValidator(
        validate_null_fields=True, validate_missing_reqired_fields=True
    )
    with pytest.raises((ValidationError, ValueError)):
        validator.validate(name=name, tool=tool, configuration=configuration)


@pytest.mark.django_db
def test_full_configuration_validation_invalid_field_types(
    test_tool_with_fields, llm_config, embedding_config
):
    tool = test_tool_with_fields
    name = "tool_configuration_validation config"
    configuration = {"llm_config": "foo", "embedding_config": ["bar"], "url": 5}
    validator = ToolConfigValidator(
        validate_null_fields=True, validate_missing_reqired_fields=True
    )
    with pytest.raises(ValueError):
        validator.validate(name=name, tool=tool, configuration=configuration)


@pytest.mark.django_db
def test_partial_configuration_validation_invalid_field_types(
    test_tool_with_fields, llm_config, embedding_config
):
    tool = test_tool_with_fields
    name = "tool_configuration_validation config"
    configuration = {"llm_config": "foo", "embedding_config": ["bar"], "url": 5}
    validator = ToolConfigValidator(
        validate_null_fields=False, validate_missing_reqired_fields=False
    )
    with pytest.raises(ValueError):
        validator.validate(name=name, tool=tool, configuration=configuration)
