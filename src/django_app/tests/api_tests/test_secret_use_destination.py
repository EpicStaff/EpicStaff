"""A config that carries a secret (an API-key secret or an `epicstaff_secret(<name>)`
header marker) sends it to its destination: the config's `base_url` and its model's
`base_url`. Pointing such a config, or a model one of them uses, at another host
needs secrets:USE. Writes that leave the destination where it is stay free."""

import pytest

from rbac.models.enums import Permission, ResourceType
from tables.models import EmbeddingConfig, LLMConfig
from tables.models.embedding_models import EmbeddingModel
from tables.models.llm_models import LLMModel
from tests.api_tests.role_grant_clients import FULL_CRUD, client_with_grants

GATEWAY_URL = "https://gateway.example.com/v1"
ATTACKER_URL = "https://attacker.example.com/v1"
MARKER_HEADERS = {"Authorization": "Bearer epicstaff_secret(GATEWAY_TOKEN)"}


@pytest.fixture
def no_use_client(db, django_user_model, default_org):
    return client_with_grants(
        org=default_org,
        django_user_model=django_user_model,
        email="destination-nouse@example.com",
        resource_permissions={
            ResourceType.SECRETS.value: int(Permission.READ),
            ResourceType.LLM_CONFIGS.value: FULL_CRUD,
        },
    )


@pytest.fixture
def use_client(db, django_user_model, default_org):
    return client_with_grants(
        org=default_org,
        django_user_model=django_user_model,
        email="destination-use@example.com",
        resource_permissions={
            ResourceType.SECRETS.value: int(Permission.READ | Permission.USE),
            ResourceType.LLM_CONFIGS.value: FULL_CRUD,
        },
    )


@pytest.fixture
def custom_llm_model(default_org, openai_provider):
    def _make(name, base_url):
        return LLMModel.objects.create(
            name=name,
            llm_provider=openai_provider,
            base_url=base_url,
            is_custom=True,
            org=default_org,
        )

    return _make


@pytest.fixture
def custom_embedding_model(default_org, openai_provider):
    def _make(name, base_url):
        return EmbeddingModel.objects.create(
            name=name,
            embedding_provider=openai_provider,
            base_url=base_url,
            is_custom=True,
            org=default_org,
        )

    return _make


@pytest.fixture
def gateway_llm_model(custom_llm_model):
    return custom_llm_model("gateway-llm", GATEWAY_URL)


@pytest.fixture
def secret_llm_config(default_org, gateway_llm_model, secret_a):
    return LLMConfig.objects.create(
        custom_name="destination-secret-config",
        model=gateway_llm_model,
        api_key_secret=secret_a,
        org=default_org,
    )


@pytest.fixture
def secret_embedding_config(default_org, embedding_model, secret_a):
    return EmbeddingConfig.objects.create(
        custom_name="destination-secret-embedder",
        model=embedding_model,
        api_key_secret=secret_a,
        org=default_org,
    )


@pytest.mark.django_db
def test_llm_config_base_url_change_with_api_key_denied(no_use_client, secret_llm_config):
    response = no_use_client.patch(
        f"/api/llm-configs/{secret_llm_config.pk}/", {"base_url": ATTACKER_URL}, format="json"
    )

    assert response.status_code == 400, response.json()
    assert response.json()["message"].startswith("base_url:")
    secret_llm_config.refresh_from_db()
    assert secret_llm_config.base_url is None


@pytest.mark.django_db
def test_base_url_change_on_marker_only_config_denied(no_use_client, default_org):
    config = LLMConfig.objects.create(
        custom_name="destination-marker-config", extra_headers=MARKER_HEADERS, org=default_org
    )

    response = no_use_client.patch(
        f"/api/llm-configs/{config.pk}/", {"base_url": ATTACKER_URL}, format="json"
    )

    assert response.status_code == 400, response.json()
    assert response.json()["message"].startswith("base_url:")
    config.refresh_from_db()
    assert config.base_url is None


@pytest.mark.django_db
def test_switch_to_custom_model_with_other_base_url_denied(
    no_use_client, secret_llm_config, gateway_llm_model, custom_llm_model
):
    attacker_model = custom_llm_model("attacker-llm", ATTACKER_URL)

    response = no_use_client.patch(
        f"/api/llm-configs/{secret_llm_config.pk}/", {"model": attacker_model.pk}, format="json"
    )

    assert response.status_code == 400, response.json()
    assert response.json()["message"].startswith("model:")
    secret_llm_config.refresh_from_db()
    assert secret_llm_config.model_id == gateway_llm_model.pk


@pytest.mark.django_db
def test_switch_to_model_with_same_base_url_is_free(
    no_use_client, secret_llm_config, custom_llm_model
):
    sibling_model = custom_llm_model("gateway-llm-sibling", GATEWAY_URL)

    response = no_use_client.patch(
        f"/api/llm-configs/{secret_llm_config.pk}/", {"model": sibling_model.pk}, format="json"
    )

    assert response.status_code == 200, response.json()
    secret_llm_config.refresh_from_db()
    assert secret_llm_config.model_id == sibling_model.pk


@pytest.mark.django_db
def test_unrelated_field_edit_is_free(no_use_client, secret_llm_config):
    response = no_use_client.patch(
        f"/api/llm-configs/{secret_llm_config.pk}/", {"temperature": 0.9}, format="json"
    )

    assert response.status_code == 200, response.json()
    secret_llm_config.refresh_from_db()
    assert secret_llm_config.temperature == 0.9


@pytest.mark.django_db
@pytest.mark.parametrize("stored, sent", [(None, ""), ("", None)])
def test_empty_and_null_base_url_are_same_destination(
    no_use_client, secret_llm_config, stored, sent
):
    LLMConfig.objects.filter(pk=secret_llm_config.pk).update(base_url=stored)

    response = no_use_client.patch(
        f"/api/llm-configs/{secret_llm_config.pk}/", {"base_url": sent}, format="json"
    )

    assert response.status_code == 200, response.json()
    secret_llm_config.refresh_from_db()
    assert secret_llm_config.base_url == sent


@pytest.mark.django_db
def test_base_url_change_without_secret_is_free(no_use_client, default_org, gateway_llm_model):
    config = LLMConfig.objects.create(
        custom_name="destination-plain-config",
        model=gateway_llm_model,
        extra_headers={"X-Trace": "plain"},
        org=default_org,
    )

    response = no_use_client.patch(
        f"/api/llm-configs/{config.pk}/", {"base_url": ATTACKER_URL}, format="json"
    )

    assert response.status_code == 200, response.json()
    config.refresh_from_db()
    assert config.base_url == ATTACKER_URL


@pytest.mark.django_db
@pytest.mark.parametrize(
    "secret_fields_for",
    [
        pytest.param(lambda secret: {"api_key_secret": secret}, id="api-key"),
        pytest.param(lambda secret: {"extra_headers": MARKER_HEADERS}, id="header-marker"),
    ],
)
def test_llm_model_base_url_edit_used_by_secret_config_denied(
    no_use_client, default_org, gateway_llm_model, secret_a, secret_fields_for
):
    LLMConfig.objects.create(
        custom_name="destination-model-user",
        model=gateway_llm_model,
        org=default_org,
        **secret_fields_for(secret_a),
    )

    response = no_use_client.patch(
        f"/api/llm-models/{gateway_llm_model.pk}/", {"base_url": ATTACKER_URL}, format="json"
    )

    assert response.status_code == 400, response.json()
    assert response.json()["message"].startswith("base_url:")
    gateway_llm_model.refresh_from_db()
    assert gateway_llm_model.base_url == GATEWAY_URL


@pytest.mark.django_db
def test_llm_model_base_url_edit_without_secret_configs_is_free(
    no_use_client, default_org, gateway_llm_model
):
    LLMConfig.objects.create(
        custom_name="destination-plain-model-user", model=gateway_llm_model, org=default_org
    )

    response = no_use_client.patch(
        f"/api/llm-models/{gateway_llm_model.pk}/", {"base_url": ATTACKER_URL}, format="json"
    )

    assert response.status_code == 200, response.json()
    gateway_llm_model.refresh_from_db()
    assert gateway_llm_model.base_url == ATTACKER_URL


@pytest.mark.django_db
def test_built_in_model_edit_stays_immutable_without_use(
    no_use_client, default_org, gpt_4o_llm, secret_a
):
    LLMConfig.objects.create(
        custom_name="destination-builtin-user",
        model=gpt_4o_llm,
        api_key_secret=secret_a,
        org=default_org,
    )

    response = no_use_client.patch(
        f"/api/llm-models/{gpt_4o_llm.pk}/", {"base_url": ATTACKER_URL}, format="json"
    )

    assert response.status_code == 403, response.json()
    gpt_4o_llm.refresh_from_db()
    assert gpt_4o_llm.base_url is None


@pytest.mark.django_db
def test_embedding_config_model_switch_denied(
    no_use_client, secret_embedding_config, embedding_model, custom_embedding_model
):
    attacker_model = custom_embedding_model("attacker-embedder", ATTACKER_URL)

    response = no_use_client.patch(
        f"/api/embedding-configs/{secret_embedding_config.pk}/",
        {"model": attacker_model.pk},
        format="json",
    )

    assert response.status_code == 400, response.json()
    assert response.json()["message"].startswith("model:")
    secret_embedding_config.refresh_from_db()
    assert secret_embedding_config.model_id == embedding_model.pk


@pytest.mark.django_db
def test_embedding_model_base_url_edit_denied(
    no_use_client, default_org, custom_embedding_model, secret_a
):
    gateway_model = custom_embedding_model("gateway-embedder", GATEWAY_URL)
    EmbeddingConfig.objects.create(
        custom_name="destination-embedder-user",
        model=gateway_model,
        api_key_secret=secret_a,
        org=default_org,
    )

    response = no_use_client.patch(
        f"/api/embedding-models/{gateway_model.pk}/", {"base_url": ATTACKER_URL}, format="json"
    )

    assert response.status_code == 400, response.json()
    assert response.json()["message"].startswith("base_url:")
    gateway_model.refresh_from_db()
    assert gateway_model.base_url == GATEWAY_URL


@pytest.mark.django_db
def test_holder_of_use_may_change_destination(
    use_client, secret_llm_config, gateway_llm_model, secret_embedding_config, custom_embedding_model
):
    attacker_embedder = custom_embedding_model("attacker-embedder", ATTACKER_URL)

    config_response = use_client.patch(
        f"/api/llm-configs/{secret_llm_config.pk}/", {"base_url": ATTACKER_URL}, format="json"
    )
    model_response = use_client.patch(
        f"/api/llm-models/{gateway_llm_model.pk}/", {"base_url": ATTACKER_URL}, format="json"
    )
    embedder_response = use_client.patch(
        f"/api/embedding-configs/{secret_embedding_config.pk}/",
        {"model": attacker_embedder.pk},
        format="json",
    )

    assert config_response.status_code == 200, config_response.json()
    assert model_response.status_code == 200, model_response.json()
    assert embedder_response.status_code == 200, embedder_response.json()
    secret_llm_config.refresh_from_db()
    gateway_llm_model.refresh_from_db()
    secret_embedding_config.refresh_from_db()
    assert secret_llm_config.base_url == ATTACKER_URL
    assert gateway_llm_model.base_url == ATTACKER_URL
    assert secret_embedding_config.model_id == attacker_embedder.pk
