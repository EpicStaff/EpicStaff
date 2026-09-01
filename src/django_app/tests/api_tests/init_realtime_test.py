import json

import pytest
from django.urls import reverse
from rest_framework import status

from tables.models.rbac_models import Organization
from tables.models.realtime_models import OpenAIRealtimeConfig, RealtimeAgent
from tables.models.secret_models import Secret
from tables.services.secrets import secret_encryption
from tests.fixtures import *


def _published_chat_data(redis_client_mock) -> dict:
    """Decode the `RealtimeAgentChatData` JSON published on `publish()`."""
    _channel, payload = redis_client_mock.publish.call_args.args
    return json.loads(payload)


def _make_realtime_agent(agent, org):
    """Self-contained RealtimeAgent creation used by the tests below (kept
    separate from the shared `wikipedia_agent_with_configured_realtime`
    fixture so these org/API-key tests can control the agent's org
    independently)."""
    api_key_secret = Secret(org=org, name="test-openai-init-realtime-api-key")
    secret_encryption.encrypt(text="sk-test-key").write_to(api_key_secret)
    api_key_secret.save()

    config = OpenAIRealtimeConfig.objects.create(
        custom_name="test-openai",
        org=org,
        model_name="gpt-4o-realtime-preview",
        api_key_secret=api_key_secret,
    )
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
def test_init_realtime_populates_created_by_for_browser_jwt_session(
    wikipedia_agent_with_configured_realtime,
    auth_client,
    regular_user,
    redis_client_mock,
):
    """Follow-up to finding #33: the browser `/chats` flow has a real
    authenticated user making the request, so `RealtimeAgentChatData.user_id`
    (→ `RealtimeSessionItem.created_by`) must be populated from it."""
    agent_id = wikipedia_agent_with_configured_realtime.pk

    response = auth_client.post(
        reverse("init-realtime"), data={"agent_id": agent_id}, format="json"
    )

    assert response.status_code == status.HTTP_201_CREATED, response.json()
    assert _published_chat_data(redis_client_mock)["user_id"] == regular_user.id


@pytest.mark.django_db
class TestInitRealtimeApiKeyCaller:
    """the Twilio MediaStream WebSocket bridge
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

    def test_system_api_key_leaves_created_by_null(
        self,
        wikipedia_agent,
        default_org,
        api_client,
        env_api_key,
        redis_client_mock,
    ):
        """Twilio's MediaStream bridge (SYSTEM ApiKey caller) has no end-user
        session to attribute the session to — `user_id` must stay `None`,
        unlike the browser JWT flow."""
        rt_agent = _make_realtime_agent(wikipedia_agent, default_org)
        raw_key, _key = env_api_key
        api_client.credentials(HTTP_X_API_KEY=raw_key)

        response = api_client.post(
            self._url(),
            data={"agent_id": rt_agent.agent_id},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert _published_chat_data(redis_client_mock)["user_id"] is None

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

    def test_user_scoped_api_key_rejected_from_starting_session_on_other_org_agent(
        self, wikipedia_agent, default_org, api_client, user_api_key, redis_client_mock
    ):
        """a self-issued `key_type=USER` API key
        (any org member can mint one via POST /api/profile/api-keys/) must NOT
        hit the trusted-caller ApiKey branch above — that branch derives org
        straight from the agent's own `org` FK with no membership check, which
        would let a USER-scoped key start a realtime session on ANY org's
        agent. Only key_type=SYSTEM may use that bypass (mirrors
        RealtimeChannelViewSet.lookup_by_token / IsSystemApiKeyAuthenticated).
        A USER key must instead fall through to the normal org-scoped path and
        be rejected exactly like a JWT session would be for a foreign-org
        agent."""
        other_org = Organization.objects.create(name="Some Other Org")
        # `wikipedia_agent` is saved with org=default_org by its fixture;
        # `_make_realtime_agent`'s `org` arg only scopes the provider config,
        # not the agent itself. Re-home the agent in other_org so this is a
        # genuine cross-org agent, otherwise org_id == default_org.id trivially
        # matches the request's X-Organization-Id and the rejection never
        # exercises the intended cross-org path.
        wikipedia_agent.org = other_org
        wikipedia_agent.save(update_fields=["org"])
        rt_agent = _make_realtime_agent(wikipedia_agent, other_org)
        raw_key, _key = user_api_key
        api_client.credentials(
            HTTP_X_API_KEY=raw_key, HTTP_X_ORGANIZATION_ID=str(default_org.id)
        )

        response = api_client.post(
            self._url(),
            data={"agent_id": rt_agent.agent_id},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        redis_client_mock.publish.assert_not_called()

    def test_user_scoped_api_key_still_requires_org_context(
        self, wikipedia_agent, default_org, api_client, user_api_key
    ):
        """Same fix, the no-header case: a USER-scoped key with no
        X-Organization-Id must be rejected exactly like a JWT session (see
        test_jwt_session_still_requires_org_context above), not silently
        trusted via the ApiKey branch."""
        rt_agent = _make_realtime_agent(wikipedia_agent, default_org)
        raw_key, _key = user_api_key
        api_client.credentials(HTTP_X_API_KEY=raw_key)

        response = api_client.post(
            self._url(),
            data={"agent_id": rt_agent.agent_id},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json().get("code") == "org_context_required"
