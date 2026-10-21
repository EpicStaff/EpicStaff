"""`GET /api/execution-timeout-limits/`: the limits, in seconds, a PythonCode's
`execution_timeout` is validated against.

Invariant: the response mirrors the deployment configuration (minimum, default, and
maximum, where a null maximum means no upper limit). The limits are the same for every
organization, so any authenticated user may read them without an active organization;
an anonymous caller is refused.
"""

import pytest
from django.urls import reverse
from rest_framework import status


@pytest.fixture
def limits_url() -> str:
    return reverse("execution_timeout_limits")


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("default_seconds", "max_seconds"), [(45, 600), (60, None)], ids=["with-maximum", "no-maximum"]
)
def test_returns_the_configured_limits(
    auth_client, limits_url, settings, default_seconds, max_seconds
):
    settings.DEFAULT_EXECUTION_TIMEOUT_SECONDS = default_seconds
    settings.MAX_EXECUTION_TIMEOUT_SECONDS = max_seconds

    response = auth_client.get(limits_url)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.json() == {
        "min_seconds": settings.MIN_EXECUTION_TIMEOUT_SECONDS,
        "default_seconds": default_seconds,
        "max_seconds": max_seconds,
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
