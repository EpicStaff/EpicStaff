"""`GET /api/sandbox-limits/` tells the flow editor the largest node execution timeout.

Invariant: any authenticated user reads the deployment-wide ceiling in whole minutes,
whatever organization is active (the limit is configuration, not tenant data);
an anonymous caller gets 401.
"""

import pytest
from django.urls import reverse
from rest_framework import status

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


@pytest.fixture
def url():
    return reverse("sandbox_limits")


@pytest.mark.django_db
def test_anonymous_caller_is_unauthorized(api_client, url):
    response = api_client.get(url)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED, response.content


@pytest.mark.django_db
def test_returns_the_configured_ceiling(auth_client, url, settings):
    settings.SANDBOX_MAX_EXECUTION_TIMEOUT_MINUTES = 12

    response = auth_client.get(url)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.json() == {"max_execution_timeout_minutes": 12}


@pytest.mark.django_db
def test_every_organization_reads_the_same_ceiling(client_as, member_only, acme, beta, url, settings):
    settings.SANDBOX_MAX_EXECUTION_TIMEOUT_MINUTES = 3
    client = client_as(member_only)

    responses = [
        client.get(url, HTTP_X_ORGANIZATION_ID=str(organization.id)) for organization in (acme, beta)
    ]

    assert [response.status_code for response in responses] == [status.HTTP_200_OK] * 2
    assert [response.json() for response in responses] == [{"max_execution_timeout_minutes": 3}] * 2
