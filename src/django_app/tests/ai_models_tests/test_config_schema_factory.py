import time

import pytest
from ai_models.domain.schemas import ConfigSchemaFactory
from ai_models.domain.specs import ModelKind
from ai_models.domain.value_types import ValueTypeRegistry
from ai_models.repository import CatalogRepository
from jsonschema import Draft202012Validator

from tests.ai_models_tests.factories import make_runtime_catalog


@pytest.fixture
def factory():
    return ConfigSchemaFactory(CatalogRepository(make_runtime_catalog()), ValueTypeRegistry())


def _valid(schema: dict, value: dict) -> bool:
    return Draft202012Validator(schema).is_valid(value)


def test_parameters_schema_is_a_closed_draft_2020_12_object(factory):
    schema = factory.parameters_schema(ModelKind.LLM, "openai", "gpt-4o")

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {
        "max_tokens",
        "reasoning_effort",
        "seed",
        "stop",
        "temperature",
        "top_p",
    }
    assert not _valid(schema, {"frequency_penalty": 0.0})


def test_anthropic_temperature_maximum_is_one(factory):
    schema = factory.parameters_schema(ModelKind.LLM, "anthropic", "claude-sonnet")

    assert schema["properties"]["temperature"]["maximum"] == 1
    assert _valid(schema, {"temperature": 1})
    assert not _valid(schema, {"temperature": 1.5})


def test_model_limit_and_options_reach_the_schema(factory):
    properties = factory.parameters_schema(ModelKind.LLM, "openai", "gpt-4o")["properties"]

    assert properties["max_tokens"]["maximum"] == 16384
    # The registry default "medium" is not offered, so the setting defaults to "not set".
    assert properties["reasoning_effort"]["enum"] == ["low", "high", None]
    assert properties["reasoning_effort"]["default"] is None


def test_unknown_model_gets_the_provider_common_list(factory):
    schema = factory.parameters_schema(ModelKind.LLM, "openai", "my-fine-tune")

    assert list(schema["properties"]) == ["temperature", "max_tokens", "seed"]
    # No model limit, so the registry maximum applies.
    assert schema["properties"]["max_tokens"]["maximum"] == 2147483647


def test_unknown_provider_allows_no_parameters(factory):
    schema = factory.parameters_schema(ModelKind.LLM, "nobody", "gpt-4o")

    assert schema["properties"] == {}
    assert _valid(schema, {}) and not _valid(schema, {"temperature": 0.5})


def test_schemas_are_memoized_per_argument_tuple(factory):
    first = factory.parameters_schema(ModelKind.LLM, "openai", "gpt-4o")

    assert factory.parameters_schema(ModelKind.LLM, "openai", "gpt-4o") is first
    assert factory.parameters_schema(ModelKind.LLM, "openai", "gpt-4o-mini") is not first
    assert factory.connection_schema("bedrock") is factory.connection_schema("bedrock")


def test_connection_schema_marks_secret_fields_and_requires_required_ones(factory):
    schema = factory.connection_schema("bedrock")

    assert schema["additionalProperties"] is False
    assert schema["required"] == ["aws_region_name"]
    secret = schema["properties"]["aws_access_key_id"]
    assert secret["x-widget"] == "secret"
    assert schema["properties"]["aws_region_name"]["x-widget"] == "text"


@pytest.mark.parametrize(
    ("connection", "accepted"),
    [
        ({"aws_access_key_id": "epicstaff_secret(aws-key)", "aws_region_name": "eu-west-1"}, True),
        ({"aws_access_key_id": "epicstaff_secret( aws-key )", "aws_region_name": "eu-west-1"}, True),
        # A bearer api_key needs no access key id; only SigV4 signing reads one.
        ({"aws_region_name": "eu-west-1"}, True),
        # A secret field never holds a plaintext value.
        ({"aws_access_key_id": "AKIAEXAMPLE", "aws_region_name": "eu-west-1"}, False),
        ({"aws_access_key_id": "epicstaff_secret(aws-key)", "aws_region_name": ""}, False),
        ({"aws_access_key_id": "epicstaff_secret(aws-key)"}, False),
        ({"aws_access_key_id": "epicstaff_secret(aws-key)", "aws_region_name": "eu-west-1", "region": "x"}, False),
    ],
)
def test_connection_schema_validates_values(factory, connection, accepted):
    assert _valid(factory.connection_schema("bedrock"), connection) is accepted


@pytest.mark.parametrize(
    ("access_key_id", "accepted"),
    [
        ("epicstaff_secret(aws-key)", True),
        ("epicstaff_secret(  aws-key  )", True),
        ("epicstaff_secret(my aws key)", True),
        ("epicstaff_secret(\n aws-key \t)", True),
        ("epicstaff_secret(aws-key", False),
        ("epicstaff_secret()", False),
        ("epicstaff_secret(   )", False),
        ("epicstaff_secret(one) epicstaff_secret(two)", False),
        ("epicstaff_secret(epicstaff_secret(aws-key)", False),
        ("prefix epicstaff_secret(aws-key)", False),
        ("epicstaff_secret(aws-key) suffix", False),
    ],
    ids=[
        "plain",
        "padded",
        "inner-space",
        "padded-newline-tab",
        "unclosed",
        "empty",
        "blank",
        "two-markers",
        "unclosed-before-closed",
        "text-before",
        "text-after",
    ],
)
def test_secret_field_accepts_exactly_one_marker(factory, access_key_id, accepted):
    connection = {"aws_access_key_id": access_key_id, "aws_region_name": "eu-west-1"}

    assert _valid(factory.connection_schema("bedrock"), connection) is accepted


@pytest.mark.parametrize(
    "access_key_id",
    [
        "epicstaff_secret(a" + " " * 50_000,
        "epicstaff_secret(" + " " * 50_000,
        "epicstaff_secret(" + ("a" + " " * 20_000) * 5,
    ],
    ids=["name-then-spaces", "spaces-only", "words-between-long-spaces"],
)
def test_secret_field_rejects_a_long_unclosed_marker_quickly(factory, access_key_id):
    schema = factory.connection_schema("bedrock")
    connection = {"aws_access_key_id": access_key_id, "aws_region_name": "eu-west-1"}

    started = time.perf_counter()
    accepted = _valid(schema, connection)

    assert time.perf_counter() - started < 1.0
    assert accepted is False


def test_optional_connection_field_may_be_left_out(factory):
    schema = factory.connection_schema("openai")

    assert "required" not in schema
    assert _valid(schema, {}) and _valid(schema, {"base_url": "https://example.com/v1"})


def test_unknown_provider_has_no_connection_fields(factory):
    schema = factory.connection_schema("nobody")

    assert schema["properties"] == {} and not _valid(schema, {"base_url": "x"})


@pytest.fixture
def committed_factory():
    return ConfigSchemaFactory(CatalogRepository.default(), ValueTypeRegistry())


def test_fireworks_model_offers_its_tuning_settings_unset(committed_factory):
    model = "fireworks_ai/gpt-oss-120b"
    schema = committed_factory.parameters_schema(ModelKind.LLM, "fireworks_ai", model)
    properties = schema["properties"]

    for name in (
        "mirostat_target",
        "mirostat_lr",
        "safe_tokenization",
        "reasoning_history",
        "context_length_exceeded_behavior",
        "prompt_truncate_len",
    ):
        assert properties[name]["default"] is None
    assert properties["safe_tokenization"]["type"] == ["boolean", "null"]
    assert properties["context_length_exceeded_behavior"]["enum"] == ["error", "truncate", None]
    # Truncating the prompt is capped by the model's input window, not by its output limit.
    input_window = CatalogRepository.default().model(ModelKind.LLM, "fireworks_ai", model).limits[
        "max_input_tokens"
    ]
    assert properties["prompt_truncate_len"]["maximum"] == input_window
    assert _valid(schema, {"prompt_truncate_len": input_window, "safe_tokenization": None})
    assert not _valid(schema, {"prompt_truncate_len": input_window + 1})
    assert not _valid(schema, {"mirostat_target": 10.5})
