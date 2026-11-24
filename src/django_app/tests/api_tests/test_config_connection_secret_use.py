"""A config's `connection` may name extra provider secrets (e.g. the AWS access key id) by
`epicstaff_secret(<name>)` marker. Adding a marker needs secrets:USE, as choosing the
API-key secret does; keeping or removing one is free. A marker must name a secret of the
config's own organization: another organization's secret is refused exactly like a name
no secret has. The API returns the markers as stored, never the values they name.
"""

import pytest
from ai_models.models import LLMConfig, LLMModel, Provider
from rbac.models.enums import Permission, ResourceType
from tables.services.secrets import secret_service

from tests.custom_role_fixtures import *  # noqa: F401,F403
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

pytestmark = pytest.mark.django_db

CONFIGS = "/api/llm-configs/"
REGION = {"aws_region_name": "eu-west-1"}
DENIED = 'Changing the secrets referenced here requires the "Use" permission'
LLM_CONFIGS_CRUD = Permission.CREATE | Permission.READ | Permission.UPDATE | Permission.DELETE


def _marker(name):
    return f"epicstaff_secret({name})"


@pytest.fixture
def aws_key(acme):
    return secret_service.create(text="AKIA-ACME-PLAINTEXT", org=acme, name="AWS_KEY")


@pytest.fixture
def other_aws_key(acme):
    return secret_service.create(text="AKIA-ACME-OTHER", org=acme, name="OTHER_AWS_KEY")


@pytest.fixture
def bedrock_model(db):
    provider = Provider.objects.get_or_create(name="bedrock")[0]
    return LLMModel.objects.create(name="ai21.j2-mid-v1", llm_provider=provider, predefined=True)


@pytest.fixture
def gpt_4o(db):
    provider = Provider.objects.get_or_create(name="openai")[0]
    return LLMModel.objects.create(name="gpt-4o", llm_provider=provider, predefined=True)


def _client(org_client_as, custom_role_user, acme, email, secrets_permission):
    user = custom_role_user(
        acme,
        email,
        {ResourceType.SECRETS: secrets_permission, ResourceType.LLM_CONFIGS: LLM_CONFIGS_CRUD},
    )
    return org_client_as(user, acme)


@pytest.fixture
def no_use_client(org_client_as, custom_role_user, acme):
    return _client(org_client_as, custom_role_user, acme, "connection-nouse@example.com", Permission.READ)


@pytest.fixture
def use_client(org_client_as, custom_role_user, acme):
    return _client(
        org_client_as, custom_role_user, acme, "connection-use@example.com", Permission.READ | Permission.USE
    )


def _create(client, model, connection, name="bedrock-config"):
    return client.post(
        CONFIGS, {"custom_name": name, "model": model.pk, "connection": connection}, format="json"
    )


def _stored_config(acme, model, connection):
    return LLMConfig.objects.create(custom_name="stored", model=model, connection=connection, org=acme)


def test_creating_with_a_connection_marker_without_use_is_refused(no_use_client, bedrock_model, aws_key):
    response = _create(no_use_client, bedrock_model, {"aws_access_key_id": _marker("AWS_KEY"), **REGION})

    assert response.status_code == 400, response.data
    assert response.data["message"].startswith(f"connection: {DENIED}")
    assert not LLMConfig.objects.exists()


def test_a_use_holder_creates_with_a_marker_and_reads_back_the_marker_never_the_value(
    use_client, bedrock_model, aws_key
):
    connection = {"aws_access_key_id": _marker("AWS_KEY"), **REGION}

    created = _create(use_client, bedrock_model, connection)
    read = use_client.get(f"{CONFIGS}{created.data['id']}/")

    assert created.status_code == 201, created.data
    assert created.data["connection"] == connection
    assert read.data["connection"] == connection
    assert b"AKIA-ACME-PLAINTEXT" not in created.content + read.content
    assert LLMConfig.objects.get(pk=created.data["id"]).connection == connection


@pytest.mark.parametrize(
    "stored",
    [REGION, {"aws_access_key_id": _marker("AWS_KEY"), **REGION}],
    ids=["no-marker-yet", "other-marker"],
)
def test_adding_a_marker_on_update_without_use_is_refused(
    no_use_client, acme, bedrock_model, aws_key, other_aws_key, stored
):
    config = _stored_config(acme, bedrock_model, stored)

    response = no_use_client.patch(
        f"{CONFIGS}{config.pk}/",
        {"connection": {"aws_access_key_id": _marker("OTHER_AWS_KEY"), **REGION}},
        format="json",
    )

    assert response.status_code == 400, response.data
    assert response.data["message"].startswith(f"connection: {DENIED}")
    config.refresh_from_db()
    assert config.connection == stored


def test_keeping_and_removing_markers_is_free(no_use_client, acme, bedrock_model, gpt_4o, aws_key):
    connection = {"aws_access_key_id": _marker("AWS_KEY"), **REGION}
    config = _stored_config(acme, bedrock_model, connection)
    url = f"{CONFIGS}{config.pk}/"

    resent = no_use_client.patch(
        url,
        {"custom_name": "renamed", "connection": {"aws_access_key_id": "epicstaff_secret( AWS_KEY )", **REGION}},
        format="json",
    )
    # Switching to a provider without that field drops the marker with it.
    removed = no_use_client.patch(url, {"model": gpt_4o.pk, "connection": {}}, format="json")

    assert resent.status_code == 200, resent.data
    assert removed.status_code == 200, removed.data
    config.refresh_from_db()
    assert (config.custom_name, config.model_id, config.connection) == ("renamed", gpt_4o.pk, {})


def test_a_marker_naming_another_orgs_secret_is_refused_like_an_unknown_name(
    use_client, bedrock_model, beta
):
    secret_service.create(text="AKIA-BETA-PLAINTEXT", org=beta, name="BETA_AWS_KEY")

    theirs = _create(use_client, bedrock_model, {"aws_access_key_id": _marker("BETA_AWS_KEY"), **REGION})
    nobodys = _create(use_client, bedrock_model, {"aws_access_key_id": _marker("NOBODY_KEY"), **REGION})

    assert (theirs.status_code, nobodys.status_code) == (400, 400)
    assert theirs.data["message"] == nobodys.data["message"].replace("NOBODY_KEY", "BETA_AWS_KEY")
    assert theirs.data["message"] == "connection: aws_access_key_id: No secret named 'BETA_AWS_KEY'."
    assert theirs.data["errors"] == [
        {"field": "connection.aws_access_key_id", "reason": "No secret named 'BETA_AWS_KEY'."}
    ]
    assert b"AKIA-BETA-PLAINTEXT" not in theirs.content
    assert not LLMConfig.objects.exists()


def test_a_plain_value_in_a_secret_field_is_refused_and_never_echoed(use_client, bedrock_model):
    response = _create(use_client, bedrock_model, {"aws_access_key_id": "AKIA-TYPED-IN", **REGION})

    assert response.status_code == 400, response.data
    assert response.data["message"].startswith("connection: aws_access_key_id: Must be an epicstaff_secret")
    assert response.data["errors"] == [
        {
            "field": "connection.aws_access_key_id",
            "reason": "Must be an epicstaff_secret(<name>) marker naming a secret.",
        }
    ]
    assert b"AKIA-TYPED-IN" not in response.content
    assert not LLMConfig.objects.exists()


def test_a_marker_in_an_endpoint_field_is_refused_even_with_use(use_client, gpt_4o, aws_key):
    response = _create(use_client, gpt_4o, {"base_url": f"https://gateway.example/{_marker('AWS_KEY')}"})

    assert response.status_code == 400, response.data
    assert response.data["errors"] == [
        {
            "field": "connection.base_url",
            "value": "https://gateway.example/epicstaff_secret(AWS_KEY)",
            "reason": "Secret markers are only allowed in secret fields.",
        }
    ]
    assert b"AKIA-ACME-PLAINTEXT" not in response.content
    assert not LLMConfig.objects.exists()


def test_another_orgs_config_is_not_found_before_any_secret_check(use_client, beta, bedrock_model):
    theirs = LLMConfig.objects.create(custom_name="theirs", model=bedrock_model, connection=REGION, org=beta)

    response = use_client.patch(
        f"{CONFIGS}{theirs.pk}/", {"connection": {"aws_region_name": "us-east-1"}}, format="json"
    )

    assert response.status_code == 404
    theirs.refresh_from_db()
    assert theirs.connection == REGION


def test_a_connection_marker_shows_in_usage_and_delete_as_a_header_marker_does(
    org_client_as, admin_acme, acme, bedrock_model, gpt_4o
):
    # Usage and the bin treat both kinds of marker alike; a difference means one of the
    # two marker fields was left out where the other is followed.
    header_secret = secret_service.create(text="header-value", org=acme, name="HEADER_KEY")
    connection_secret = secret_service.create(text="connection-value", org=acme, name="CONNECTION_KEY")
    LLMConfig.objects.create(
        custom_name="header-user",
        model=gpt_4o,
        extra_headers={"X-Key": _marker("HEADER_KEY")},
        org=acme,
    )
    LLMConfig.objects.create(
        custom_name="connection-user",
        model=bedrock_model,
        connection={"aws_access_key_id": _marker("CONNECTION_KEY"), **REGION},
        org=acme,
    )
    client = org_client_as(admin_acme, acme)

    usage = [client.get(f"/api/secrets/{secret.pk}/usage/") for secret in (header_secret, connection_secret)]
    deleted = [client.delete(f"/api/secrets/{secret.pk}/") for secret in (header_secret, connection_secret)]

    assert [response.status_code for response in usage] == [200, 200]
    assert usage[0].data == usage[1].data
    assert deleted[0].status_code == deleted[1].status_code
