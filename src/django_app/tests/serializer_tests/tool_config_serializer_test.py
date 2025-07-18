import pytest
from tables.models import ToolConfig
from tables.serializers.model_serializers import ToolConfigSerializer
from tests.fixtures import *
from rest_framework.exceptions import ValidationError
from tables.validators.tool_config_validator import ToolConfigValidator


@pytest.mark.django_db
def test_tool_config_serialization(test_tool_with_fields, llm_config, embedding_config):
    tool = test_tool_with_fields
    data = {
        "name": "Config serialization test tool config",
        "tool": tool.pk,
        "configuration": {
            "llm_config": llm_config.pk,
            "embedding_config": embedding_config.pk,
            "url": "http://someurl.com",
        },
    }

    tool_config_serializer = ToolConfigSerializer(data=data)
    tool_config_serializer.is_valid(raise_exception=True)
    tool_config: ToolConfig = tool_config_serializer.save()

    assert tool_config.tool.pk == data["tool"]
    assert (
        tool_config.configuration["llm_config"] == data["configuration"]["llm_config"]
    )
    assert (
        tool_config.configuration["embedding_config"]
        == data["configuration"]["embedding_config"]
    )
    assert tool_config.configuration["url"] == data["configuration"]["url"]


@pytest.mark.parametrize(
    "llm_config_invalid_data",
    [
        999,
        "one",
    ],
)
@pytest.mark.django_db
def test_tool_config_serialization_invalid_llm_config_id(
    test_tool_with_fields,
    llm_config,
    llm_config_invalid_data,
    embedding_config,
):
    tool = test_tool_with_fields
    data = {
        "tool": tool.pk,
        "configuration": {
            "llm_config": llm_config_invalid_data,
            "embedding_config": embedding_config.pk,
            "url": "http://someurl.com",
        },
    }

    tool_config_serializer = ToolConfigSerializer(data=data)

    with pytest.raises((ValidationError, ValueError)):
        assert not tool_config_serializer.is_valid(raise_exception=True)


@pytest.mark.django_db
def test_tool_config_serialization_missing_required(
    test_tool_with_fields, llm_config, embedding_config
):
    tool = test_tool_with_fields
    data = {
        "name": "Config serialization missing required test tool config",
        "tool": tool.pk,
        "configuration": {
            "llm_config": llm_config.pk,
            "embedding_config": embedding_config.pk,
            # "url": "http://someurl.com"  # missing required url field
        },
    }

    tool_config_serializer = ToolConfigSerializer(data=data)

    # Allow missing required
    assert tool_config_serializer.is_valid(raise_exception=True)


@pytest.mark.django_db
def test_tool_config_serialization_non_fields(test_tool_with_fields):
    tool = test_tool_with_fields
    data = {
        "name": "Config serialization missing required test tool config",
        "tool": tool.pk,
        "configuration": {"llm_config": None, "embedding_config": None, "url": None},
    }

    tool_config_serializer = ToolConfigSerializer(data=data)

    # Allow missing required
    assert tool_config_serializer.is_valid(raise_exception=True)


@pytest.mark.django_db
def test_to_representation_with_valid_data(
    llm_config, embedding_config, test_tool_github_search_with_fields
):
    """
    Test that `to_representation` correctly converts ToolConfig instances into a dictionary representation.
    """

    tool = test_tool_github_search_with_fields

    configuration = {
        "llm_config": llm_config.pk,
        "github_repo": "https://github.com/python/cpython",
        "gh_token": "111",
        "embedding_config": embedding_config.pk,
        "content_types": {
            "user_input": "['code', 'repo', 'pr', 'issue']",
            "decoded_value": ["code", "repo", "pr", "issue"],
        },
    }

    tool_config = ToolConfig.objects.create(
        name="Valid ToolConfig",
        tool=tool,
        configuration=configuration,
    )
    serializer = ToolConfigSerializer()

    result = serializer.to_representation(tool_config)
    print(result)

    # Ensure all fields are represented correctly
    assert result["name"] == tool_config.name
    assert result["tool"] == tool.pk
    assert result["configuration"]["llm_config"] == llm_config.pk
    assert result["configuration"]["embedding_config"] == embedding_config.pk
    assert result["configuration"]["github_repo"] == "https://github.com/python/cpython"
    assert result["configuration"]["gh_token"] == "111"
    assert result["configuration"]["content_types"] == "['code', 'repo', 'pr', 'issue']"

    assert result["is_completed"] is True


@pytest.mark.django_db
def test_to_representation_with_invalid_data(
    llm_config, embedding_config, test_tool_github_search_with_fields
):

    tool = test_tool_github_search_with_fields

    configuration = {
        "llm_config": llm_config.pk,
        "github_repo": "https://github.com/python/cpython",
        "gh_token": "111",
        "embedding_config": embedding_config.pk,
        "content_types": {
            "user_input": "['code', 'repo', 'pr', 'issue']",
            "decoded_value": ["code", "repo", "pr", "issue"],
        },
    }

    tool_config = ToolConfig.objects.create(
        name="Valid ToolConfig",
        tool=tool,
        configuration=configuration,
    )
    serializer = ToolConfigSerializer()

    result = serializer.to_representation(tool_config)
    # Ensure all fields are represented correctly
    assert result["configuration"]["llm_config"] == llm_config.pk
    assert result["configuration"]["embedding_config"] == embedding_config.pk
    assert result["is_completed"] is True

    # delete llm_config (invalid configuration)
    # udpate config for ANY field type because it was overwritten in to_representation()
    tool_config.configuration["content_types"] = {
        "user_input": "['code', 'repo', 'pr', 'issue']",
        "decoded_value": ["code", "repo", "pr", "issue"],
    }

    llm_config.delete()

    result_after_deleting_llmconfig = serializer.to_representation(tool_config)

    assert result_after_deleting_llmconfig["is_completed"] is False


@pytest.mark.django_db
def test_validate_is_completed_with_valid_empty_configuration(test_tool):
    """
    Test `validate_is_completed` when all required fields are present and valid.
    """
    tool = test_tool
    configuration = {}
    tool_config_validator = ToolConfigValidator()
    is_completed = tool_config_validator.validate_is_completed(tool.pk, configuration)

    assert is_completed is True


@pytest.mark.django_db
def test_validate_is_completed_with_missing_fields(
    llm_config, test_tool_github_search_with_fields
):
    """
    Test `validate_is_completed` when required fields are missing.
    """
    tool = test_tool_github_search_with_fields
    configuration = {
        "llm_config": llm_config.pk,  # Missing required fields
    }
    tool_config_validator = ToolConfigValidator()
    is_completed = tool_config_validator.validate_is_completed(tool.pk, configuration)

    assert is_completed is False


@pytest.mark.django_db
def test_validate_is_completed_with_invalid_field_data(
    llm_config, test_tool_with_fields
):
    """
    Test `validate_is_completed` when a field has invalid data.
    """
    tool = test_tool_with_fields
    configuration = {
        "llm_config": llm_config.pk,
        "url": 123,  # Should be an string, not a integer
    }
    tool_config_validator = ToolConfigValidator()
    is_completed = tool_config_validator.validate_is_completed(tool.pk, configuration)

    assert is_completed is False
