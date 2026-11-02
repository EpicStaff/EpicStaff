"""`GET /api/llm-config-timeout-limits/`: the limits, in seconds, an LLM config's
`timeout` is validated against.

Invariant: the response reports the bounds the LLM config API enforces (minimum 1, maximum
from DJANGO_LLM_CONFIG_MAX_TIMEOUT). They are the same for every organization, so any
authenticated user may read them, also without an active organization; an anonymous
caller is refused.
"""

import pytest
from django.conf import settings
from django.urls import reverse
from rest_framework import status


@pytest.fixture
def limits_url() -> str:
    return reverse("llm_config_timeout_limits")


@pytest.mark.django_db
def test_returns_the_enforced_limits(auth_client, limits_url):
    response = auth_client.get(limits_url)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.json() == {
        "min_seconds": 1,
        "max_seconds": settings.LLM_CONFIG_TIMEOUT_MAX_SECONDS,
    }


@pytest.mark.django_db
def test_authenticated_user_without_an_active_organization_can_read(
    api_client, jwt_tokens, limits_url
):
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {jwt_tokens['access']}")

    response = api_client.get(limits_url)

    assert response.status_code == status.HTTP_200_OK, response.content


@pytest.mark.django_db
def test_anonymous_caller_is_refused(api_client, limits_url):
    response = api_client.get(limits_url)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED, response.content
