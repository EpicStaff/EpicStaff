"""An imported LLM or embedding config is fitted to the model catalog, not refused by it.

Settings the model does not take and connection fields the provider does not declare are
dropped, values are kept as they are (a config that no longer fits shows "needs review"),
and required connection fields are not demanded, since older export files cannot hold
them. Secrets are as strict as on any write: a marker sits only in a secret field and
names a secret of the importing organization. Re-importing a file reuses the config whose
fitted `parameters` and `connection` are equal to the file's.
"""

import pytest
from ai_models.models import EmbeddingConfig, EmbeddingModel, LLMConfig, LLMModel, Provider
from tables.exceptions import ConfigValidationError
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.registry import entity_registry
from tables.import_export.services.import_service import ImportService
from tables.import_export.version_conversions.base import VersionConverter
from tables.services.secrets import secret_service

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

pytestmark = pytest.mark.django_db

GATEWAY = "https://gateway.example/openai"
AWS_KEY_MARKER = "epicstaff_secret(AWS_KEY)"


def _v5_file(main_entity, **entities) -> dict:
    return {"version": 5, "main_entity": main_entity, **entities}


def _imported(file: dict, main_entity, org, user):
    id_mapper, _ = ImportService(entity_registry).import_data(
        VersionConverter.convert(file), main_entity, org_id=org.id, user=user
    )
    return id_mapper


def test_a_version_5_llm_config_imports_with_parameters_and_its_custom_model_s_endpoint(
    acme, admin_acme
):
    Provider.objects.create(name="azure")
    file = _v5_file(
        EntityType.LLM_CONFIG,
        LLMModel=[
            {
                "id": 7,
                "name": "gateway-gpt",
                "provider_name": "azure",
                "is_custom": True,
                "predefined": False,
                "base_url": GATEWAY,
                "api_version": "2024-06-01",
                "deployment_id": "prod-gpt",
                "tags": [],
            }
        ],
        LLMConfig=[
            {
                "id": 70,
                "custom_name": "gateway config",
                "model": 7,
                "temperature": 0.3,
                "max_tokens": 1000,
                "logprobs": None,
                # Azure's custom models take no reasoning effort: dropped, not refused.
                "reasoning_effort": "high",
                "base_url": None,
                "api_version": None,
                "extra_headers": {},
                "tags": [],
            }
        ],
    )

    id_mapper = _imported(file, EntityType.LLM_CONFIG, acme, admin_acme)

    config = LLMConfig.objects.get(pk=id_mapper.get(EntityType.LLM_CONFIG, 70))
    assert config.org_id == acme.id
    assert config.parameters == {"temperature": 0.3, "max_tokens": 1000}
    assert config.connection == {
        "base_url": GATEWAY,
        "api_version": "2024-06-01",
        "deployment_id": "prod-gpt",
    }
    assert (config.model.name, config.model.org_id) == ("gateway-gpt", acme.id)


def test_a_version_5_embedding_config_imports_with_parameters_and_its_custom_model_s_endpoint(
    acme, admin_acme
):
    Provider.objects.create(name="gemini")
    file = _v5_file(
        EntityType.EMBEDDING_CONFIG,
        EmbeddingModel=[
            {
                "id": 3,
                "name": "gateway-embedder",
                "provider_name": "gemini",
                "is_custom": True,
                "predefined": False,
                "base_url": GATEWAY,
                # Gemini declares no deployment field, so the import drops it.
                "deployment": "embed-prod",
                "tags": [],
            }
        ],
        EmbeddingConfig=[
            {"id": 30, "custom_name": "embedder", "model": 3, "task_type": "retrieval_document"}
        ],
    )

    id_mapper = _imported(file, EntityType.EMBEDDING_CONFIG, acme, admin_acme)

    config = EmbeddingConfig.objects.get(pk=id_mapper.get(EntityType.EMBEDDING_CONFIG, 30))
    assert config.parameters == {"task_type": "retrieval_document"}
    assert config.connection == {"base_url": GATEWAY}


@pytest.fixture
def gpt_4o(db):
    provider = Provider.objects.get_or_create(name="openai")[0]
    return LLMModel.objects.create(name="gpt-4o", llm_provider=provider, predefined=True)


@pytest.fixture
def bedrock_model(db):
    provider = Provider.objects.create(name="bedrock")
    return LLMModel.objects.create(
        name="anthropic.claude-v2", llm_provider=provider, predefined=True
    )


def _model_mapper(model) -> IDMapper:
    id_mapper = IDMapper()
    id_mapper.map(EntityType.LLM_MODEL, model.id, model.id, was_created=False)
    return id_mapper


def _entry(model, **fields) -> dict:
    return {
        "id": 500,
        "custom_name": "imported config",
        "model": model.id,
        "parameters": {},
        "connection": {},
        "extra_headers": {},
        "tags": [],
        **fields,
    }


def _import_llm_config(entry: dict, model, org, user):
    return entity_registry.get_strategy(EntityType.LLM_CONFIG).import_entity(
        dict(entry), _model_mapper(model), is_main=False, org_id=org.id, user=user
    )


def test_unsupported_keys_are_dropped_and_values_kept_as_they_are(gpt_4o, acme, admin_acme):
    entry = _entry(
        gpt_4o,
        parameters={"temperature": 5, "made_up_setting": 1},
        connection={"base_url": GATEWAY, "region": "eu-west-1"},
    )

    config = _import_llm_config(entry, gpt_4o, acme, admin_acme)

    config.refresh_from_db()
    # 5 is out of range: kept as it is, the config shows "needs review".
    assert config.parameters == {"temperature": 5}
    assert config.connection == {"base_url": GATEWAY}


def test_re_importing_the_same_file_reuses_the_config(gpt_4o, acme, admin_acme):
    entry = _entry(
        gpt_4o,
        parameters={"temperature": 0.2, "made_up_setting": 1},
        connection={"base_url": GATEWAY},
    )
    first = _import_llm_config(entry, gpt_4o, acme, admin_acme)

    second = _import_llm_config(entry, gpt_4o, acme, admin_acme)

    assert second.pk == first.pk
    assert LLMConfig.objects.filter(org=acme).count() == 1


def test_a_stale_config_is_reused_by_its_own_export(gpt_4o, acme, admin_acme):
    # A catalog update left this config with a setting its model no longer takes.
    stale = LLMConfig.objects.create(
        custom_name="imported config",
        model=gpt_4o,
        parameters={"temperature": 0.2, "made_up_setting": 1},
        org=acme,
    )
    entry = _entry(gpt_4o, parameters={"temperature": 0.2, "made_up_setting": 1})

    assert _import_llm_config(entry, gpt_4o, acme, admin_acme).pk == stale.pk


@pytest.mark.parametrize(
    "changes",
    [{"parameters": {"temperature": 0.9}}, {"connection": {"base_url": "https://other.example"}}],
    ids=["parameters", "connection"],
)
def test_a_file_with_other_values_does_not_reuse_the_config(gpt_4o, acme, admin_acme, changes):
    entry = _entry(gpt_4o, parameters={"temperature": 0.2}, connection={"base_url": GATEWAY})
    first = _import_llm_config(entry, gpt_4o, acme, admin_acme)

    second = _import_llm_config({**entry, **changes}, gpt_4o, acme, admin_acme)

    assert second.pk != first.pk


def test_required_connection_fields_are_not_demanded(bedrock_model, acme, admin_acme):
    # An export older than version 6 cannot hold the region Bedrock now requires.
    config = _import_llm_config(_entry(bedrock_model), bedrock_model, acme, admin_acme)

    assert config.connection == {}


def test_a_marker_resolves_against_the_importing_organization(
    bedrock_model, acme, beta, admin_acme
):
    secret_service.create(text="AKIA-acme", org=acme, name="AWS_KEY")
    secret_service.create(text="AKIA-beta", org=beta, name="AWS_KEY")
    connection = {"aws_access_key_id": AWS_KEY_MARKER, "aws_region_name": "eu-west-1"}

    config = _import_llm_config(
        _entry(bedrock_model, connection=connection), bedrock_model, acme, admin_acme
    )

    assert (config.org_id, config.connection) == (acme.id, connection)


def test_a_marker_naming_only_another_organization_s_secret_is_refused(
    bedrock_model, acme, beta, admin_acme
):
    secret_service.create(text="AKIA-beta", org=beta, name="AWS_KEY")
    entry = _entry(
        bedrock_model,
        connection={"aws_access_key_id": AWS_KEY_MARKER, "aws_region_name": "eu-west-1"},
    )

    with pytest.raises(ConfigValidationError) as refusal:
        _import_llm_config(entry, bedrock_model, acme, admin_acme)

    assert refusal.value.detail["connection"]["aws_access_key_id"] == [
        "No secret named 'AWS_KEY'."
    ]
    assert not LLMConfig.objects.filter(org=acme).exists()


def test_a_marker_outside_a_secret_field_is_refused(bedrock_model, acme, admin_acme):
    secret_service.create(text="AKIA-acme", org=acme, name="AWS_KEY")
    entry = _entry(bedrock_model, connection={"aws_region_name": AWS_KEY_MARKER})

    with pytest.raises(ConfigValidationError) as refusal:
        _import_llm_config(entry, bedrock_model, acme, admin_acme)

    assert list(refusal.value.detail["connection"]) == ["aws_region_name"]
    assert not LLMConfig.objects.filter(org=acme).exists()


def test_a_plaintext_value_in_a_secret_field_is_refused(bedrock_model, acme, admin_acme):
    entry = _entry(bedrock_model, connection={"aws_access_key_id": "AKIAEXAMPLE"})

    with pytest.raises(ConfigValidationError) as refusal:
        _import_llm_config(entry, bedrock_model, acme, admin_acme)

    assert list(refusal.value.detail["connection"]) == ["aws_access_key_id"]


@pytest.mark.parametrize("part", ["parameters", "connection"])
def test_a_part_that_is_no_object_is_refused(gpt_4o, acme, admin_acme, part):
    with pytest.raises(ConfigValidationError) as refusal:
        _import_llm_config(_entry(gpt_4o, **{part: "temperature=1"}), gpt_4o, acme, admin_acme)

    assert refusal.value.detail[part] == ["Must be an object."]


def test_an_embedding_config_is_fitted_like_an_llm_config(acme, admin_acme):
    provider = Provider.objects.create(name="gemini")
    model = EmbeddingModel.objects.create(
        name="gemini-embedding-001", embedding_provider=provider, predefined=True
    )
    id_mapper = IDMapper()
    id_mapper.map(EntityType.EMBEDDING_MODEL, model.id, model.id, was_created=False)
    entry = _entry(
        model,
        parameters={"task_type": "retrieval_query", "temperature": 0.5},
        connection={"base_url": GATEWAY, "deployment_id": "x"},
    )

    config = entity_registry.get_strategy(EntityType.EMBEDDING_CONFIG).import_entity(
        entry, id_mapper, is_main=False, org_id=acme.id, user=admin_acme
    )

    config.refresh_from_db()
    assert config.parameters == {"task_type": "retrieval_query"}
    assert config.connection == {"base_url": GATEWAY}
