"""Regression guard for the cross-org secret read through POST /api/init-realtime/.

`config` is an unconstrained DictField and realtime_service setattrs every key
that exists on the payload. `rt_api_key_secret_id` is a declared carrier field,
so before org-scoped resolution a caller with AGENTS.READ on one of their own
agents could name ANY Secret id in the installation and have Django decrypt it
into realtime_agents:schema.
"""

import pytest
from rest_framework.test import APIClient

from tables.models.rbac_models import Organization
from tables.services.secrets import secret_service

FOREIGN_PLAINTEXT = "sk-FOREIGN-must-never-be-decrypted-4b71"


@pytest.fixture
def default_org_client(regular_user, default_org):
    # regular_user is an Org Admin of default_org. JWT auth is inert under
    # tests/settings.py (DEFAULT_AUTHENTICATION_CLASSES is cleared), so
    # force_authenticate is the only pattern that works here.
    client = APIClient()
    client.force_authenticate(user=regular_user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(default_org.id))
    return client


@pytest.mark.django_db
def test_config_cannot_name_another_orgs_secret(
    default_org_client,
    wikipedia_agent_with_configured_realtime,
    default_org,
    redis_client_mock,
):
    foreign_org = Organization.objects.create(name="Org Foreign RT")
    foreign_secret = secret_service.create(
        text=FOREIGN_PLAINTEXT, org=foreign_org, name="foreign-rt-key"
    )

    resp = default_org_client.post(
        "/api/init-realtime/",
        {
            "agent_id": wikipedia_agent_with_configured_realtime.pk,
            "config": {"rt_api_key_secret_id": foreign_secret.pk},
        },
        format="json",
    )

    # The view wraps any init_realtime failure as {"error": str(exc)}; pin the
    # cause to SecretResolver's org filter, not some unrelated failure.
    assert resp.status_code == 400, resp.data
    assert "could not be resolved" in resp.data["error"]
    published = "".join(str(call) for call in redis_client_mock.publish.call_args_list)
    assert FOREIGN_PLAINTEXT not in published


@pytest.mark.django_db
def test_own_org_secret_in_config_still_works(
    default_org_client,
    wikipedia_agent_with_configured_realtime,
    default_org,
    redis_client_mock,
):
    # Proving the theft is blocked is worthless if the legitimate override broke.
    own_secret = secret_service.create(
        text="sk-own-rt-key", org=default_org, name="own-rt-key"
    )

    resp = default_org_client.post(
        "/api/init-realtime/",
        {
            "agent_id": wikipedia_agent_with_configured_realtime.pk,
            "config": {"rt_api_key_secret_id": own_secret.pk},
        },
        format="json",
    )

    assert resp.status_code == 201, resp.data
    published = "".join(str(call) for call in redis_client_mock.publish.call_args_list)
    assert "sk-own-rt-key" in published
