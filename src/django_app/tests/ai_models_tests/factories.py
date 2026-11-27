from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field, replace
from datetime import date

from ai_models.domain.catalog import Catalog
from ai_models.domain.registry import ParameterRegistry
from ai_models.domain.specs import (
    ConnectionFieldSpec,
    DefaultThinkingSpec,
    ModelKind,
    ModelSpec,
    ParameterSpec,
    ProviderSpec,
)


def make_parameter(name: str = "temperature", **fields) -> ParameterSpec:
    values = {
        "value_type": "number",
        "control": "slider",
        "label": name.replace("_", " ").title(),
        "help_text": f"Help for {name}.",
        "group": "sampling",
        "default": None,
        "minimum": None,
        "maximum": None,
        "step": None,
        "options": (),
        "limit_from": None,
        "draft": False,
        "overrides": {},
    }
    values.update(fields)
    return ParameterSpec(name=name, **values)


def make_model(**fields) -> ModelSpec:
    values = {
        "name": "gpt-4o",
        "provider": "openai",
        "kind": ModelKind.LLM,
        "recommended": False,
        "deprecation_date": None,
        "limits": {},
        "parameter_names": (),
        "options": {},
    }
    values.update(fields)
    return ModelSpec(**values)


def make_provider(**fields) -> ProviderSpec:
    values = {
        "name": "openai",
        "label": "OpenAI",
        "recommended": True,
        "kinds": (ModelKind.LLM,),
        "custom_models": True,
        "connection_fields": (
            ConnectionFieldSpec(
                name="base_url",
                value_type="text",
                control="text",
                label="Base URL",
                required=False,
                secret=False,
                endpoint=True,
                litellm_argument="api_base",
            ),
        ),
        "common_parameters": {ModelKind.LLM: ("temperature",)},
    }
    values.update(fields)
    return ProviderSpec(**values)


def make_registry(**fields) -> ParameterRegistry:
    values = {
        "parameters": {"temperature": make_parameter("temperature", default=0.7, minimum=0, maximum=2)},
        "providers": {"openai": make_provider()},
        "hidden_names": frozenset({"tools", "stream"}),
        "kind_parameters": {},
        "recommended_models": {},
        "default_thinking": {},
    }
    values.update(fields)
    return ParameterRegistry(**values)


@dataclass
class FakeLiteLLMAdapter:
    """Stands in for `LiteLLMAdapter`: answers from the dicts it is given."""

    models: list[ModelSpec] = field(default_factory=list)
    llm: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    embedding: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    transcription: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    annotations: Mapping[str, object] = field(default_factory=dict)
    adaptive_thinking: frozenset[str] = frozenset()

    def version(self) -> str:
        return "1.108.1"

    def model_entries(self, kind: ModelKind) -> Iterator[ModelSpec]:
        return iter([model for model in self.models if model.kind == kind])

    def llm_parameters(self, model: ModelSpec) -> tuple[str, ...]:
        return self.llm.get(model.name, ())

    def supports_adaptive_thinking(self, model: ModelSpec) -> bool:
        return model.name in self.adaptive_thinking

    def embedding_parameters(self, provider: str) -> tuple[str, ...] | None:
        return self.embedding.get(provider)

    def transcription_parameters(self, provider: str) -> tuple[str, ...] | None:
        return self.transcription.get(provider)

    def completion_annotations(self) -> Mapping[str, object]:
        return self.annotations


def make_connection_field(name: str = "base_url", **fields) -> ConnectionFieldSpec:
    values = {
        "value_type": "text",
        "control": "text",
        "label": name.replace("_", " ").title(),
        "required": False,
        "secret": False,
        "endpoint": False,
        "litellm_argument": name,
    }
    values.update(fields)
    return ConnectionFieldSpec(name=name, **values)


def make_runtime_catalog() -> Catalog:
    """A small catalog with every case the run-time catalog services must tell apart.

    LLM providers: `anthropic` and `openai` (recommended), `bedrock` (secret connection
    field), `ollama` (custom models, no catalog model), `watsonx` (no model, no custom
    models), `legacy_ai` (only a deprecated model), `mystery` (models, no `ProviderSpec`).
    Embedding: `openai`, plus `voyage`, whose spec lists no kind. `bedrock` also has an
    embedding model although it no longer runs embedding.
    """
    parameters = {
        "temperature": make_parameter(
            "temperature",
            default=0.7,
            minimum=0,
            maximum=2,
            step=0.01,
            overrides={"anthropic": {"maximum": 1}},
        ),
        "top_p": make_parameter(
            "top_p", control="percent", default=1.0, minimum=0.01, maximum=1.0, step=0.01
        ),
        "max_tokens": make_parameter(
            "max_tokens",
            value_type="integer",
            control="stepper",
            group="output",
            default=4096,
            minimum=500,
            maximum=2147483647,
            step=100,
            limit_from="max_output_tokens",
        ),
        "reasoning_effort": make_parameter(
            "reasoning_effort",
            value_type="choice",
            control="select",
            group="reasoning",
            default="medium",
            options=("low", "medium", "high"),
        ),
        "seed": make_parameter(
            "seed", value_type="integer", control="stepper", minimum=0, maximum=1000, step=1
        ),
        "stop": make_parameter("stop", value_type="text_list", control="chips", group="output"),
        "dimensions": make_parameter(
            "dimensions", value_type="integer", control="stepper", minimum=1, maximum=3072
        ),
    }
    providers = {
        "openai": make_provider(
            kinds=(ModelKind.LLM, ModelKind.EMBEDDING),
            common_parameters={
                ModelKind.LLM: ("temperature", "max_tokens", "seed"),
                ModelKind.EMBEDDING: ("dimensions",),
            },
        ),
        "anthropic": make_provider(
            name="anthropic",
            label="Anthropic",
            custom_models=False,
            common_parameters={ModelKind.LLM: ("temperature", "top_p", "max_tokens")},
        ),
        "bedrock": make_provider(
            name="bedrock",
            label="Bedrock",
            recommended=False,
            custom_models=False,
            connection_fields=(
                make_connection_field("aws_access_key_id", secret=True),
                make_connection_field("aws_region_name", required=True),
            ),
            common_parameters={
                ModelKind.LLM: ("max_tokens",),
                ModelKind.EMBEDDING: ("dimensions",),
            },
        ),
        "ollama": make_provider(name="ollama", label="Ollama", recommended=False),
        "watsonx": make_provider(
            name="watsonx", label="watsonx", recommended=False, custom_models=False
        ),
        "legacy_ai": make_provider(
            name="legacy_ai", label="Legacy AI", recommended=False, custom_models=False
        ),
        "voyage": make_provider(
            name="voyage", label="Voyage", recommended=False, kinds=(), custom_models=False
        ),
    }
    past, future = date(2020, 1, 1), date(2999, 1, 1)
    llm_models = [
        make_model(
            name="gpt-4o",
            recommended=True,
            limits={"max_input_tokens": 128000, "max_output_tokens": 16384},
            parameter_names=(
                "max_tokens", "reasoning_effort", "seed", "stop", "temperature", "top_p"
            ),
            options={"reasoning_effort": ("low", "high")},
        ),
        make_model(
            name="gpt-4o-mini",
            limits={"max_output_tokens": 2048},
            parameter_names=("max_tokens", "temperature"),
        ),
        make_model(name="gpt-3.5-turbo-0301", deprecation_date=past, parameter_names=("seed",)),
        make_model(name="gpt-7", deprecation_date=future, parameter_names=("temperature",)),
        make_model(
            name="claude-sonnet",
            provider="anthropic",
            recommended=True,
            limits={"max_output_tokens": 4096},
            parameter_names=("max_tokens", "temperature", "top_p"),
        ),
        make_model(
            name="anthropic.claude-v2", provider="bedrock", parameter_names=("max_tokens",)
        ),
        make_model(name="old-model", provider="legacy_ai", deprecation_date=past),
        make_model(name="mystery-1", provider="mystery", parameter_names=("temperature",)),
    ]
    embedding_models = [
        make_model(
            name="text-embedding-3-small",
            kind=ModelKind.EMBEDDING,
            parameter_names=("dimensions",),
        ),
        make_model(name="voyage-3", provider="voyage", kind=ModelKind.EMBEDDING),
        make_model(
            name="amazon.titan-embed",
            provider="bedrock",
            kind=ModelKind.EMBEDDING,
            parameter_names=("dimensions", "seed"),
        ),
    ]
    models: dict = {}
    for model in llm_models + embedding_models:
        models.setdefault(model.kind, {}).setdefault(model.provider, {})[model.name] = model
    return Catalog(
        litellm_version="1.108.1", parameters=parameters, providers=providers, models=models
    )


def make_thinking_catalog() -> Catalog:
    """`make_runtime_catalog` plus one Anthropic model of each `default_thinking` case.

    `claude-between-tools` and `claude-disabled` think by default and are turned off with
    that `thinking.type`; `claude-always-thinks` cannot be turned off (no "none");
    `claude-gateway-thinks` thinks by default but is reached where `thinking` is not
    sent; `claude-asks-to-think` thinks only when asked.
    """
    catalog = make_runtime_catalog()
    efforts = ("none", "low", "medium", "high")
    thinking_models = [
        make_model(
            name="claude-between-tools",
            options={"reasoning_effort": efforts},
            default_thinking=DefaultThinkingSpec("high", "between_tools"),
        ),
        make_model(
            name="claude-disabled",
            options={"reasoning_effort": efforts},
            default_thinking=DefaultThinkingSpec("medium", "disabled"),
        ),
        make_model(
            name="claude-always-thinks",
            options={"reasoning_effort": efforts[1:]},
            default_thinking=DefaultThinkingSpec("medium", None),
        ),
        make_model(
            name="claude-gateway-thinks",
            options={"reasoning_effort": efforts},
            default_thinking=DefaultThinkingSpec(
                "high", "disabled", provider_accepts_thinking=False
            ),
        ),
        make_model(name="claude-asks-to-think", options={"reasoning_effort": efforts}),
    ]
    anthropic_models = dict(catalog.models[ModelKind.LLM]["anthropic"])
    for model in thinking_models:
        anthropic_models[model.name] = replace(
            model, provider="anthropic", parameter_names=("reasoning_effort", "temperature")
        )
    llm_models = {**catalog.models[ModelKind.LLM], "anthropic": anthropic_models}
    return replace(catalog, models={**catalog.models, ModelKind.LLM: llm_models})


def make_catalog() -> Catalog:
    temperature = make_parameter(
        "temperature",
        default=0.7,
        minimum=0.0,
        maximum=2.0,
        step=0.01,
        overrides={"anthropic": {"maximum": 1}},
    )
    reasoning_effort = make_parameter(
        "reasoning_effort",
        value_type="choice",
        control="select",
        group="reasoning",
        options=("low", "medium", "high"),
    )
    llm_model = make_model(
        name="gpt-4o",
        recommended=True,
        deprecation_date=date(2027, 1, 31),
        limits={"max_input_tokens": 128000, "max_output_tokens": 16384},
        parameter_names=("reasoning_effort", "temperature"),
        options={"reasoning_effort": ("low", "high")},
    )
    embedding_model = make_model(
        name="text-embedding-3-small",
        kind=ModelKind.EMBEDDING,
        limits={"max_input_tokens": 8191},
    )
    vertex = make_provider(
        name="vertex_ai",
        label="Vertex AI",
        recommended=False,
        kinds=(ModelKind.LLM, ModelKind.EMBEDDING),
        custom_models=False,
        connection_fields=(
            ConnectionFieldSpec(
                name="vertex_project",
                value_type="text",
                control="text",
                label="Project",
                required=True,
                secret=False,
                endpoint=True,
                litellm_argument="vertex_project",
            ),
        ),
        common_parameters={ModelKind.LLM: ("temperature",), ModelKind.EMBEDDING: ()},
        main_secret_argument="vertex_credentials",
    )
    return Catalog(
        litellm_version="1.108.1",
        parameters={"temperature": temperature, "reasoning_effort": reasoning_effort},
        providers={"openai": make_provider(), "vertex_ai": vertex},
        models={
            ModelKind.LLM: {"openai": {"gpt-4o": llm_model}},
            ModelKind.EMBEDDING: {"openai": {"text-embedding-3-small": embedding_model}},
        },
    )
