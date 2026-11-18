"""A run payload's `connection` fields resolve their `epicstaff_secret(<name>)` markers like
`extra_headers` do: by name, among the live secrets of the payload's organization only.

Most tests pin the resolver's side with a payload model of the same field names; the last
one runs the real wire shape through to the arguments a LiteLLM call receives.
"""

import pytest
from pydantic import BaseModel
from rbac.models import Organization
from src.shared.models import LLMConfigData, LLMData
from tables.services.secrets import SecretResolutionError, secret_resolver, secret_service

pytestmark = pytest.mark.django_db


class _ConfigPayload(BaseModel):
    connection: dict[str, str] | None = None
    embedder_connection: dict[str, str] | None = None
    extra_headers: dict[str, str] | None = None


class _RunPayload(BaseModel):
    llm: _ConfigPayload


@pytest.fixture
def acme(db):
    return Organization.objects.create(name="Acme connection markers")


@pytest.fixture
def beta(db):
    return Organization.objects.create(name="Beta connection markers")


def test_markers_in_a_connection_field_resolve_in_the_run_payload(acme):
    secret_service.create(text="AKIA-acme", org=acme, name="AWS_KEY")
    payload = _RunPayload(
        llm=_ConfigPayload(
            connection={"aws_access_key_id": "epicstaff_secret(AWS_KEY)", "aws_region_name": "eu-west-1"},
            embedder_connection={"aws_access_key_id": "epicstaff_secret( AWS_KEY )"},
        )
    )

    resolved = secret_resolver.resolve_payload(payload=payload, org_id=acme.id)

    assert resolved.llm.connection == {"aws_access_key_id": "AKIA-acme", "aws_region_name": "eu-west-1"}
    assert resolved.llm.embedder_connection == {"aws_access_key_id": "AKIA-acme"}
    # The payload the caller holds keeps its markers.
    assert payload.llm.connection["aws_access_key_id"] == "epicstaff_secret(AWS_KEY)"


@pytest.mark.parametrize("name", ["BETA_KEY", "NOBODY_KEY"], ids=["other-org", "unknown"])
def test_a_name_the_payloads_org_has_no_secret_for_never_resolves(acme, beta, name):
    secret_service.create(text="AKIA-beta", org=beta, name="BETA_KEY")
    payload = _RunPayload(llm=_ConfigPayload(connection={"aws_access_key_id": f"epicstaff_secret({name})"}))

    with pytest.raises(SecretResolutionError) as error:
        secret_resolver.resolve_payload(payload=payload, org_id=acme.id)

    assert "_ConfigPayload.connection" in str(error.value)
    assert name in str(error.value)
    assert "AKIA-beta" not in str(error.value)


def test_a_binned_secret_never_resolves(acme):
    secret = secret_service.create(text="AKIA-binned", org=acme, name="BINNED_KEY")
    secret.delete()
    payload = _RunPayload(llm=_ConfigPayload(connection={"aws_access_key_id": "epicstaff_secret(BINNED_KEY)"}))

    with pytest.raises(SecretResolutionError):
        secret_resolver.resolve_payload(payload=payload, org_id=acme.id)


def test_a_resolved_llm_config_hands_litellm_its_connection_and_main_secret(acme):
    secret_service.create(text="AKIA-acme", org=acme, name="AWS_KEY")
    main_secret = secret_service.create(text="aws-secret-value", org=acme, name="AWS_SECRET")
    payload = LLMData(
        provider="bedrock",
        config=LLMConfigData(
            model="anthropic.claude-v2",
            connection={"aws_access_key_id": "epicstaff_secret(AWS_KEY)", "aws_region_name": "eu-west-1"},
            main_secret_argument="aws_secret_access_key",
            api_key_secret_id=main_secret.pk,
        ),
    )

    resolved = secret_resolver.resolve_payload(payload=payload, org_id=acme.id)

    assert resolved.config.connection_kwargs() == {
        "aws_access_key_id": "AKIA-acme",
        "aws_region_name": "eu-west-1",
        "aws_secret_access_key": "aws-secret-value",
    }
    assert payload.config.connection_kwargs() == {
        "aws_access_key_id": "epicstaff_secret(AWS_KEY)",
        "aws_region_name": "eu-west-1",
    }
