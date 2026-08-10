import pytest
from django.urls import reverse
from rest_framework import status

from tables.models.rbac_models import Organization
from tables.models.realtime_models import OpenAIRealtimeConfig, RealtimeAgent
from tests.fixtures import *


def _make_realtime_agent(agent, org):
    """Self-contained RealtimeAgent creation used by the tests below.

    NOTE: the shared `wikipedia_agent_with_configured_realtime` fixture
    (tests/fixtures.py) is currently broken independent of this change — it
    still passes the pre-EST-3629/3630 kwargs `realtime_config=` /
    `realtime_transcription_config=` to `RealtimeAgent.objects.create()`,
    but the model was migrated to per-provider FKs (`openai_config`,
    `elevenlabs_config`, `gemini_config`). This is a pre-existing gap on
    this branch (reproduces on a clean checkout too, unrelated to this
    fix) — flagged for the user rather than fixed here, since it is out of
    this task's scope. New tests below build their own valid RealtimeAgent
    to avoid depending on it.
    """
    config = OpenAIRealtimeConfig.objects.create(custom_name="test-openai", org=org)
    return RealtimeAgent.objects.create(agent=agent, openai_config=config)


@pytest.mark.django_db
def test_init_realtime(
    wikipedia_agent_with_configured_realtime, auth_client, redis_client_mock
):
    agent_id = wikipedia_agent_with_configured_realtime.pk

    url = reverse("init-realtime")

    data = {"agent_id": agent_id}

    response = auth_client.post(url, data=data, format="json")
    response_data = response.json()

    # Assert that the response status code is 201
    assert response.status_code == status.HTTP_201_CREATED, response_data

    # Assert that the response contains the 'connection_key' field
    assert "connection_key" in response_data
    assert isinstance(response_data["connection_key"], str)

    redis_client_mock.publish.assert_called()


@pytest.mark.django_db
class TestInitRealtimeApiKeyCaller:
    """EST-3631 (3rd STR): the Twilio MediaStream WebSocket bridge
    (`realtime`'s `_voice_stream_handler`) calls POST /api/init-realtime/
    server-to-server with `X-API-Key` and no logged-in user, so it cannot
    supply `X-Organization-Id`. It already resolved `agent_id` itself via
    `RealtimeChannelViewSet.lookup_by_token`, so org is derived from the
    agent's own `org` FK instead of requiring a header — same approach as
    `lookup_by_token`. Normal JWT/user callers must keep requiring org
    context exactly as before."""

    def _url(self):
        return reverse("init-realtime")

    def test_succeeds_with_system_api_key_no_org_header(
        self,
        wikipedia_agent,
        default_org,
        api_client,
        env_api_key,
        redis_client_mock,
    ):
        rt_agent = _make_realtime_agent(wikipedia_agent, default_org)
        raw_key, _key = env_api_key
        api_client.credentials(HTTP_X_API_KEY=raw_key)

        response = api_client.post(
            self._url(),
            data={"agent_id": rt_agent.agent_id},
            format="json",
        )
        response_data = response.json()

        assert response.status_code == status.HTTP_201_CREATED, response_data
        assert "connection_key" in response_data
        redis_client_mock.publish.assert_called()

    def test_succeeds_for_agent_in_a_different_org(
        self,
        wikipedia_agent,
        default_org,
        api_client,
        env_api_key,
        redis_client_mock,
    ):
        """By design: the API key itself is the trust boundary (server-to-
        server secret between `realtime` and Django), and `agent_id` was
        already resolved server-side from a trusted, org-scoped lookup
        (lookup_by_token). No X-Organization-Id is required or checked for
        this caller, regardless of which org owns the agent — mirroring
        lookup_by_token's cross-org-by-design behavior."""
        rt_agent = _make_realtime_agent(wikipedia_agent, default_org)
        Organization.objects.create(name="Some Other Org")
        raw_key, _key = env_api_key
        api_client.credentials(HTTP_X_API_KEY=raw_key)

        response = api_client.post(
            self._url(),
            data={"agent_id": rt_agent.agent_id},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()

    def test_rejects_unknown_agent_id(self, api_client, env_api_key, db):
        raw_key, _key = env_api_key
        api_client.credentials(HTTP_X_API_KEY=raw_key)

        response = api_client.post(
            self._url(), data={"agent_id": 999999}, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_jwt_session_still_requires_org_context(
        self, wikipedia_agent, default_org, api_client, jwt_tokens
    ):
        """Regression guard: a regular JWT-authenticated user (no ApiKey auth)
        must keep requiring/deriving org via their session exactly as before
        — the API-key branch must not weaken this path."""
        rt_agent = _make_realtime_agent(wikipedia_agent, default_org)
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {jwt_tokens['access']}")

        response = api_client.post(
            self._url(),
            data={"agent_id": rt_agent.agent_id},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json().get("code") == "org_context_required"
