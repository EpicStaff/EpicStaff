"""`extra_headers` on LLM and embedding configs: stored as given, validated as a flat
{name: value} mapping of strings, and invisible across organizations."""

import pytest
from django.utils.module_loading import import_string

from tables.models.embedding_models import EmbeddingConfig
from tables.models.llm_models import LLMConfig
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

CONFIG_ENDPOINTS = [
    ("/api/embedding-configs/", EmbeddingConfig),
    ("/api/llm-configs/", LLMConfig),
]


@pytest.fixture
def client(client_as, admin_acme, acme):
    api_client = client_as(admin_acme)
    api_client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return api_client


@pytest.mark.django_db
@pytest.mark.parametrize("endpoint, model", CONFIG_ENDPOINTS)
def test_extra_headers_round_trip_with_markers_kept_verbatim(client, endpoint, model):
    headers = {
        "Authorization": "Bearer epicstaff_secret(GATEWAY_TOKEN)",
        "X-Trace": "plain-value",
    }

    created = client.post(
        endpoint,
        {"custom_name": "with-headers", "extra_headers": headers},
        format="json",
    )

    assert created.status_code == 201, created.data
    assert created.data["extra_headers"] == headers
    assert model.objects.get(pk=created.data["id"]).extra_headers == headers
    fetched = client.get(f"{endpoint}{created.data['id']}/")
    assert fetched.data["extra_headers"] == headers


@pytest.mark.django_db
@pytest.mark.parametrize("endpoint, model", CONFIG_ENDPOINTS)
def test_extra_headers_default_to_an_empty_object(client, endpoint, model):
    created = client.post(endpoint, {"custom_name": "no-headers"}, format="json")

    assert created.status_code == 201, created.data
    assert created.data["extra_headers"] == {}


@pytest.mark.django_db
@pytest.mark.parametrize("endpoint, model", CONFIG_ENDPOINTS)
@pytest.mark.parametrize(
    "extra_headers",
    [
        ["X-Key", "value"],
        "X-Key: value",
        {"X-Key": 1},
        {"X-Key": {"nested": "value"}},
        {"X-Key": None},
        {" ": "value"},
        {"X Key": "value"},
        {"X-Key:": "value"},
        {"X-Ключ": "value"},
        {"X-A": "1", "x-a": "2"},
        {"X-Key": "ok\r\nInjected: yes"},
        {"X-Key": "bell"},
    ],
    ids=[
        "list",
        "string",
        "int-value",
        "nested-value",
        "null-value",
        "blank-name",
        "name-with-space",
        "name-with-colon",
        "non-ascii-name",
        "case-duplicate",
        "crlf-value",
        "control-char-value",
    ],
)
def test_malformed_extra_headers_are_rejected(client, endpoint, model, extra_headers):
    response = client.post(
        endpoint,
        {"custom_name": "bad-headers", "extra_headers": extra_headers},
        format="json",
    )

    assert response.status_code == 400
    # The global exception handler folds field errors into the "message" string.
    assert "extra_headers" in response.json()["message"]
    assert not model.objects.filter(custom_name="bad-headers").exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "extra_headers, offending",
    [
        ({"X Key": "v"}, "X Key"),
        ({"X-A": "1", "x-a": "2"}, "x-a"),
        ({"X-Key": "a\nb"}, "X-Key"),
    ],
)
def test_rejection_message_names_the_offending_header(client, extra_headers, offending):
    response = client.post(
        "/api/llm-configs/",
        {"custom_name": "bad-headers", "extra_headers": extra_headers},
        format="json",
    )

    assert response.status_code == 400
    assert f"'{offending}'" in response.json()["message"]


@pytest.mark.django_db
def test_valid_token_characters_and_tab_in_value_are_accepted(client):
    headers = {"X-Api_Key.v2~1": "a\tb", "!#$%&'*+^`|": "v"}

    response = client.post(
        "/api/llm-configs/",
        {"custom_name": "token-chars", "extra_headers": headers},
        format="json",
    )

    assert response.status_code == 201, response.data
    assert response.data["extra_headers"] == headers


@pytest.mark.django_db
def test_patch_validates_extra_headers(client, acme):
    config = EmbeddingConfig.objects.create(custom_name="patch-me", org=acme)

    response = client.patch(
        f"/api/embedding-configs/{config.pk}/",
        {"extra_headers": {"X-Key": 42}},
        format="json",
    )

    assert response.status_code == 400
    config.refresh_from_db()
    assert config.extra_headers == {}


@pytest.mark.django_db
def test_another_orgs_embedding_config_headers_are_not_readable(client, beta):
    foreign = EmbeddingConfig.objects.create(
        custom_name="beta-config",
        org=beta,
        extra_headers={"X-Key": "epicstaff_secret(BETA_KEY)"},
    )

    assert client.get(f"/api/embedding-configs/{foreign.pk}/").status_code == 404
    patched = client.patch(
        f"/api/embedding-configs/{foreign.pk}/",
        {"extra_headers": {"X-Key": "hijacked"}},
        format="json",
    )
    assert patched.status_code == 404
    foreign.refresh_from_db()
    assert foreign.extra_headers == {"X-Key": "epicstaff_secret(BETA_KEY)"}


@pytest.mark.django_db
@pytest.mark.parametrize(
    "serializer_path",
    [
        "tables.import_export.serializers.configs.LLMConfigImportSerializer",
        "tables.import_export.serializers.configs.EmbeddingConfigImportSerializer",
    ],
)
@pytest.mark.parametrize(
    "extra_headers",
    [{"X Key": "v"}, {"X-A": "1", "x-a": "2"}, {"X-Key": "a\r\nb"}],
    ids=["bad-name", "case-duplicate", "crlf-value"],
)
def test_import_serializers_reject_invalid_headers(serializer_path, extra_headers):
    serializer = import_string(serializer_path)(
        data={"custom_name": "imported", "extra_headers": extra_headers}
    )

    assert not serializer.is_valid()
    assert "extra_headers" in serializer.errors
