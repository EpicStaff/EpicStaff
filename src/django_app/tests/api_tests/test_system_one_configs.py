import pytest
from django.db import IntegrityError, transaction

from tables.models import LLMConfig, SystemOneConfig
from tables.services.secrets import secret_service
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

URL = "/api/system-one-configs/"


def _in_org(client, org):
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client


@pytest.fixture
def admin_client(client_as, admin_acme, acme):
    return _in_org(client_as(admin_acme), acme)


@pytest.fixture
def member_client(client_as, member_only, acme):
    return _in_org(client_as(member_only), acme)


@pytest.fixture
def acme_secret(acme):
    return secret_service.create(text="ts-key", org=acme, name="TYPESAFE_KEY")


@pytest.fixture
def acme_llm_config(acme):
    return LLMConfig.objects.create(custom_name="acme-llm", org=acme)


def _typesafe(secret_id, **overrides):
    return {
        "custom_name": "jev",
        "provider": "typesafe",
        "model_name": "jev-1.14.0",
        "api_key_secret_id": secret_id,
        **overrides,
    }


def _openai(secret_id, **overrides):
    return {
        "custom_name": "luna",
        "provider": "openai",
        "model_name": "gpt-6-luna",
        "api_key_secret_id": secret_id,
        **overrides,
    }


@pytest.mark.django_db
def test_create_typesafe_config_lands_in_active_org(admin_client, acme, acme_secret, admin_acme):
    response = admin_client.post(URL, _typesafe(acme_secret.id), format="json")
    assert response.status_code == 201, response.json()
    config = SystemOneConfig.objects.get(id=response.json()["id"])
    assert (config.org_id, config.created_by_id) == (acme.id, admin_acme.id)
    assert response.json()["api_key_secret_id"] == acme_secret.id


@pytest.mark.django_db
def test_create_openai_config(admin_client, acme_secret):
    response = admin_client.post(URL, _openai(acme_secret.id), format="json")
    assert response.status_code == 201, response.json()
    assert response.json()["api_key_secret_id"] == acme_secret.id
    assert response.json()["model_name"] == "gpt-6-luna"


@pytest.mark.django_db
def test_create_llm_backed_config(admin_client, acme_llm_config):
    body = {"custom_name": "llm-s1", "provider": "llm", "llm_config": acme_llm_config.id}
    response = admin_client.post(URL, body, format="json")
    assert response.status_code == 201, response.json()
    assert SystemOneConfig.objects.get(id=response.json()["id"]).llm_config_id == acme_llm_config.id


@pytest.mark.django_db
@pytest.mark.parametrize(
    "overrides,field",
    [
        ({"api_key_secret_id": None}, "api_key_secret_id"),
        ({"model_name": "jev-9.9.9"}, "model_name"),
        ({"model_name": None}, "model_name"),
        ({"model_name": "gpt-6-luna"}, "model_name"),
    ],
)
def test_invalid_typesafe_config_is_refused(admin_client, acme_secret, overrides, field):
    response = admin_client.post(URL, _typesafe(acme_secret.id, **overrides), format="json")
    assert response.status_code == 400
    assert field in str(response.json())


@pytest.mark.django_db
@pytest.mark.parametrize(
    "overrides,field",
    [
        ({"api_key_secret_id": None}, "api_key_secret_id"),
        ({"model_name": None}, "model_name"),
        ({"model_name": "jev-1.14.0"}, "model_name"),
    ],
)
def test_invalid_openai_config_is_refused(admin_client, acme_secret, overrides, field):
    response = admin_client.post(URL, _openai(acme_secret.id, **overrides), format="json")
    assert response.status_code == 400
    assert field in str(response.json())


@pytest.mark.django_db
def test_openai_config_with_llm_config_is_refused(admin_client, acme_secret, acme_llm_config):
    response = admin_client.post(
        URL, _openai(acme_secret.id, llm_config=acme_llm_config.id), format="json"
    )
    assert response.status_code == 400
    assert "llm_config" in str(response.json())


@pytest.mark.django_db
def test_typesafe_config_still_updates(admin_client, acme_secret):
    created = admin_client.post(URL, _typesafe(acme_secret.id), format="json").json()
    response = admin_client.patch(f"{URL}{created['id']}/", {"custom_name": "renamed"}, format="json")
    assert response.status_code == 200, response.json()
    assert response.json()["custom_name"] == "renamed"


@pytest.mark.django_db
def test_openai_config_with_llm_config_is_refused_by_the_database(acme, acme_llm_config):
    with pytest.raises(IntegrityError), transaction.atomic():
        SystemOneConfig.objects.create(
            custom_name="luna", provider="openai", llm_config=acme_llm_config, org=acme
        )


@pytest.mark.django_db
def test_typesafe_config_with_llm_config_is_refused(admin_client, acme_secret, acme_llm_config):
    response = admin_client.post(
        URL, _typesafe(acme_secret.id, llm_config=acme_llm_config.id), format="json"
    )
    assert response.status_code == 400
    assert "llm_config" in str(response.json())


@pytest.mark.django_db
@pytest.mark.parametrize(
    "extra,field",
    [({}, "llm_config"), ({"model_name": "jev-1.14.0"}, "model_name")],
)
def test_invalid_llm_backed_config_is_refused(admin_client, acme_llm_config, extra, field):
    body = {"custom_name": "x", "provider": "llm", **extra}
    if field != "llm_config":
        body["llm_config"] = acme_llm_config.id
    response = admin_client.post(URL, body, format="json")
    assert response.status_code == 400
    assert field in str(response.json())


@pytest.mark.django_db
def test_list_returns_only_active_org_configs(admin_client, acme, beta):
    SystemOneConfig.objects.create(custom_name="mine", provider="llm", org=acme)
    SystemOneConfig.objects.create(custom_name="theirs", provider="llm", org=beta)
    body = admin_client.get(URL).json()
    names = {row["custom_name"] for row in body.get("results", body)}
    assert names == {"mine"}


@pytest.mark.django_db
def test_detail_of_another_org_config_is_404(admin_client, beta):
    theirs = SystemOneConfig.objects.create(custom_name="theirs", provider="llm", org=beta)
    assert admin_client.get(f"{URL}{theirs.id}/").status_code == 404


@pytest.mark.django_db
def test_llm_config_of_another_org_is_refused(admin_client, beta):
    theirs = LLMConfig.objects.create(custom_name="b-llm", org=beta)
    body = {"custom_name": "x", "provider": "llm", "llm_config": theirs.id}
    response = admin_client.post(URL, body, format="json")
    assert response.status_code == 400
    assert "llm_config" in str(response.json())


@pytest.mark.django_db
def test_secret_of_another_org_is_refused(admin_client, beta):
    theirs = secret_service.create(text="b-key", org=beta, name="B_KEY")
    response = admin_client.post(URL, _typesafe(theirs.id), format="json")
    assert response.status_code == 400
    assert "api_key_secret_id" in str(response.json())


@pytest.mark.django_db
def test_member_cannot_create(member_client, acme_secret):
    assert member_client.post(URL, _typesafe(acme_secret.id), format="json").status_code == 403


@pytest.mark.django_db
def test_duplicate_name_is_refused_in_the_same_org_only(admin_client, acme, beta, acme_secret):
    SystemOneConfig.objects.create(custom_name="jev", provider="llm", org=beta)
    assert admin_client.post(URL, _typesafe(acme_secret.id), format="json").status_code == 201
    assert admin_client.post(URL, _typesafe(acme_secret.id), format="json").status_code == 400


@pytest.mark.django_db
def test_deleting_the_llm_config_keeps_the_config_and_refuses_a_resave(
    admin_client, acme, acme_llm_config
):
    config = SystemOneConfig.objects.create(
        custom_name="llm-s1", provider="llm", llm_config=acme_llm_config, org=acme
    )
    assert admin_client.delete(f"/api/llm-configs/{acme_llm_config.id}/").status_code == 204
    config.refresh_from_db()
    assert config.llm_config_id is None
    response = admin_client.patch(f"{URL}{config.id}/", {"custom_name": "renamed"}, format="json")
    assert response.status_code == 400
    assert "llm_config" in str(response.json())


@pytest.mark.django_db
def test_switching_provider_with_old_fields_is_refused(admin_client, acme_secret, acme_llm_config):
    created = admin_client.post(URL, _typesafe(acme_secret.id), format="json").json()
    response = admin_client.patch(
        f"{URL}{created['id']}/",
        {"provider": "llm", "llm_config": acme_llm_config.id},
        format="json",
    )
    assert response.status_code == 400
    body = str(response.json())
    assert "model_name" in body
    assert "api_key_secret_id" in body
