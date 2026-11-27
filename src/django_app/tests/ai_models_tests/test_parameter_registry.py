from pathlib import Path

import ai_models
import pytest
import yaml
from ai_models.domain.registry import ParameterRegistry
from ai_models.domain.specs import DefaultThinkingSpec, ModelKind

REGISTRY_PATH = Path(ai_models.__file__).parent / "data" / "parameter_registry.yaml"

MINIMAL_REGISTRY = {
    "parameters": {
        "temperature": {
            "value_type": "number",
            "control": "slider",
            "label": "Temperature",
            "help_text": "Randomness.",
            "group": "sampling",
            "default": 0.7,
            "minimum": 0,
            "maximum": 2,
        },
    },
    "hidden": ["tools"],
    "providers": {
        "openai": {
            "label": "OpenAI",
            "kinds": ["llm"],
            "connection_fields": {
                "base_url": {"label": "Base URL", "litellm_argument": "api_base"},
            },
            "common_parameters": {"llm": ["temperature"]},
        },
    },
    "kind_parameters": {"embedding": {"openai": []}},
    "recommended_models": {"openai": ["gpt-4o"]},
}


@pytest.fixture(scope="module")
def registry() -> ParameterRegistry:
    return ParameterRegistry.load(REGISTRY_PATH)


def _load_variant(tmp_path: Path, data: dict) -> ParameterRegistry:
    path = tmp_path / "parameter_registry.yaml"
    path.write_text(yaml.safe_dump(data))
    return ParameterRegistry.load(path)


def _variant(**changes) -> dict:
    data = yaml.safe_load(yaml.safe_dump(MINIMAL_REGISTRY))
    for dotted_path, value in changes.items():
        *parents, leaf = dotted_path.split("__")
        target = data
        for parent in parents:
            target = target[parent]
        target[leaf] = value
    return data


def test_registry_file_loads(registry):
    assert registry.parameter("temperature").default == 0.7


def test_provider_override_applies(registry):
    temperature = registry.parameter("temperature")

    anthropic_temperature = temperature.for_provider("anthropic")
    assert anthropic_temperature.maximum == 1
    assert anthropic_temperature.minimum == 0 and anthropic_temperature.default == 0.7
    assert temperature.for_provider("openai").maximum == 2


def test_embedding_kind_limited_to_runtime_providers(registry):
    embedding_providers = {
        provider.name for provider in registry.providers() if ModelKind.EMBEDDING in provider.kinds
    }

    assert embedding_providers == {"openai", "gemini", "cohere", "mistral", "together_ai"}


def test_every_runtime_provider_declares_its_settings_for_custom_models(registry):
    for provider in registry.providers():
        assert set(provider.kinds) <= set(provider.common_parameters), provider.name


def test_runtime_embedding_settings_come_from_the_registry(registry):
    for provider in registry.providers():
        if ModelKind.EMBEDDING in provider.kinds:
            assert registry.kind_parameters(ModelKind.EMBEDDING, provider.name) is not None


def test_hidden_names_are_never_settings(registry):
    assert {"tools", "messages", "stream", "response_format"} <= registry.hidden_names
    assert all(registry.parameter(name) is None for name in registry.hidden_names)


@pytest.mark.parametrize(
    "name",
    [
        "mirostat_target",
        "mirostat_lr",
        "safe_tokenization",
        "reasoning_history",
        "context_length_exceeded_behavior",
        "prompt_truncate_len",
    ],
)
def test_provider_tuning_settings_are_offered_unset_by_default(registry, name):
    assert name not in registry.hidden_names
    assert registry.parameter(name).default is None


@pytest.mark.parametrize(
    "name",
    [
        "ignore_eos",
        "store",
        "prompt_cache_retention",
        "max_retries",
        "cache_control",
        "context_management",
        "k",
        "retrieval_method",
        "filter_kb_content_by_query_metadata",
    ],
)
def test_runtime_and_policy_settings_stay_hidden(registry, name):
    assert name in registry.hidden_names


def test_recommended_models_come_from_the_seed(registry):
    assert registry.is_recommended("openai", "gpt-4o")
    assert registry.is_recommended("gemini", "gemini/gemini-2.5-flash")
    assert not registry.is_recommended("openai", "gpt-3.5-turbo")
    assert not registry.is_recommended("unknown_provider", "gpt-4o")


def test_minimal_file_loads_with_defaults(tmp_path):
    registry = _load_variant(tmp_path, MINIMAL_REGISTRY)

    openai = registry.provider("openai")
    assert openai.recommended is False and openai.custom_models is False
    assert openai.connection_fields[0].required is False
    assert openai.connection_fields[0].secret is False
    assert registry.parameter("temperature").options == ()
    assert registry.parameter("temperature").draft is False
    assert registry.kind_parameters(ModelKind.EMBEDDING, "openai") == ()
    assert registry.kind_parameters(ModelKind.TRANSCRIPTION, "openai") is None
    assert registry.provider("anthropic") is None


@pytest.mark.parametrize(
    ("changes", "named"),
    [
        ({"paramters": {}}, "paramters"),
        ({"parameters__temperature__maximun": 2}, "maximun"),
        ({"parameters__temperature__overrides": {"anthropic": {"maximun": 1}}}, "maximun"),
        ({"providers__openai__kind": ["llm"]}, "kind"),
        ({"providers__openai__connection_fields__base_url__secrets": True}, "secrets"),
        ({"providers__openai__common_parameters": {"chat": ["temperature"]}}, "chat"),
        ({"kind_parameters": {"embeddings": {}}}, "embeddings"),
        ({"default_thinking": {"claude-x": {"thinks_by_default": False, "efort": "high"}}}, "efort"),
    ],
)
def test_unknown_key_in_yaml_raises(tmp_path, changes, named):
    with pytest.raises(ValueError, match=named):
        _load_variant(tmp_path, _variant(**changes))


@pytest.mark.parametrize(
    ("changes", "named"),
    [
        ({"providers__openai__common_parameters": {"llm": ["temprature"]}}, "temprature"),
        ({"kind_parameters": {"embedding": {"openai": ["dimension"]}}}, "dimension"),
        ({"kind_parameters": {"embedding": {"opnai": []}}}, "opnai"),
        ({"recommended_models": {"opnai": ["gpt-4o"]}}, "opnai"),
        ({"parameters__temperature__value_type": "float"}, "float"),
        ({"parameters__temperature__control": "slide"}, "slide"),
        ({"providers__openai__kinds": ["chat"]}, "chat"),
    ],
)
def test_unknown_reference_or_value_raises(tmp_path, changes, named):
    with pytest.raises(ValueError, match=named):
        _load_variant(tmp_path, _variant(**changes))


def test_missing_required_key_raises(tmp_path):
    data = _variant()
    del data["parameters"]["temperature"]["default"]

    with pytest.raises(ValueError, match="default"):
        _load_variant(tmp_path, data)


def test_database_provider_names_are_aliases_of_their_litellm_provider(registry):
    aliases = {
        alias: provider.name for provider in registry.providers() for alias in provider.aliases
    }

    assert aliases == {
        "google_ai": "gemini",
        "novita_ai": "novita",
        "aws_sagemaker": "sagemaker",
        "featherless-ai": "featherless_ai",
        "together-ai": "together_ai",
        "aleph-alpha": "aleph_alpha",
        "cloudflare_workers_ai": "cloudflare",
    }


def test_providers_litellm_lists_no_models_for_take_typed_model_names(registry):
    for name in (
        "openrouter",
        "huggingface",
        "github",
        "nvidia_nim",
        "aleph_alpha",
        "clarifai",
        "petals",
        "galadriel",
        "compactifai",
    ):
        assert registry.provider(name).custom_models is True, name


def _with_second_provider(**anthropic_fields) -> dict:
    data = _variant()
    data["providers"]["anthropic"] = {"label": "Anthropic", "kinds": ["llm"], **anthropic_fields}
    return data


@pytest.mark.parametrize(
    ("anthropic_aliases", "openai_aliases"),
    [
        (["openai"], []),  # an alias naming another provider
        (["legacy"], ["legacy"]),  # one alias on two providers
    ],
)
def test_alias_colliding_with_another_name_raises(tmp_path, anthropic_aliases, openai_aliases):
    data = _with_second_provider(aliases=anthropic_aliases)
    data["providers"]["openai"]["aliases"] = openai_aliases

    with pytest.raises(ValueError, match="aliases"):
        _load_variant(tmp_path, data)


def test_aliases_default_to_none(tmp_path):
    assert _load_variant(tmp_path, MINIMAL_REGISTRY).provider("openai").aliases == ()


@pytest.mark.parametrize(
    ("fields", "argument"),
    [({}, "api_key"), ({"main_secret_argument": "vertex_credentials"}, "vertex_credentials")],
    ids=["default", "set"],
)
def test_main_secret_argument_names_where_the_api_key_secret_goes(tmp_path, fields, argument):
    data = _variant()
    data["providers"]["openai"].update(fields)

    assert _load_variant(tmp_path, data).provider("openai").main_secret_argument == argument


def _thinking_entry(**fields) -> dict:
    return {"thinks_by_default": True, "default_effort": "high", "thinking_type_to_turn_off": "disabled", **fields}


def test_default_thinking_entries_load(tmp_path):
    data = _variant(
        default_thinking={
            "claude-turned-off": _thinking_entry(),
            "claude-always": _thinking_entry(default_effort="medium", thinking_type_to_turn_off=None),
            "claude-asks": {"thinks_by_default": False},
        }
    )

    registry = _load_variant(tmp_path, data)

    assert registry.default_thinking("claude-turned-off") == DefaultThinkingSpec("high", "disabled")
    assert registry.default_thinking("claude-always") == DefaultThinkingSpec("medium", None)
    assert registry.default_thinking("claude-asks") is None
    assert registry.thinking_base_name("claude-asks") == "claude-asks"
    assert registry.thinking_base_names() == {"claude-turned-off", "claude-always", "claude-asks"}


def test_default_thinking_section_is_optional(tmp_path):
    registry = _load_variant(tmp_path, MINIMAL_REGISTRY)

    assert registry.thinking_base_name("claude-x") is None


@pytest.mark.parametrize(
    ("entry", "named"),
    [
        ({"thinks_by_default": "yes"}, "thinks_by_default"),
        ({"thinks_by_default": False, "default_effort": "high"}, "default_effort"),
        ({"thinks_by_default": True, "default_effort": "high"}, "thinking_type_to_turn_off"),
        ({"thinks_by_default": True, "thinking_type_to_turn_off": None}, "default_effort"),
        (_thinking_entry(default_effort="none"), "unknown effort: none"),
        (_thinking_entry(default_effort="extreme"), "extreme"),
        (_thinking_entry(thinking_type_to_turn_off="off"), "unknown type: off"),
    ],
)
def test_bad_default_thinking_entry_raises(tmp_path, entry, named):
    with pytest.raises(ValueError, match=f"default_thinking.claude-x.*{named}"):
        _load_variant(tmp_path, _variant(default_thinking={"claude-x": entry}))


@pytest.mark.parametrize(
    ("model_name", "base_name"),
    [
        ("claude-opus-5", "claude-opus-5"),
        ("claude-opus-5-5", "claude-opus-5-5"),
        ("us.anthropic.claude-opus-5-5", "claude-opus-5-5"),
        ("bedrock/us-gov-west-1/anthropic.claude-opus-5", "claude-opus-5"),
        ("vertex_ai/claude-opus-5-5@default", "claude-opus-5-5"),
        ("azure_ai/claude-opus-5-5-fast", "claude-opus-5-5"),
        ("databricks/databricks-claude-opus-5", "claude-opus-5"),
        ("anthropic.claude-opus-5-v1", "claude-opus-5"),
        # A later version or a dated snapshot is another model.
        ("claude-opus-5-7", None),
        ("claude-opus-5-20270101", None),
        ("github_copilot/claude-opus-5.7", None),
        ("myclaude-opus-5", None),
        ("gpt-4o", None),
    ],
)
def test_model_name_matches_the_longest_base_name_it_is_a_variant_of(tmp_path, model_name, base_name):
    data = _variant(
        default_thinking={"claude-opus-5": _thinking_entry(), "claude-opus-5-5": {"thinks_by_default": False}}
    )

    assert _load_variant(tmp_path, data).thinking_base_name(model_name) == base_name
