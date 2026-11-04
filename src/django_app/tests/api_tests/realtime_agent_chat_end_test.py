import pytest
from django.urls import reverse
from rest_framework import status

from rbac.models import Organization
from tables.models.realtime_models import (
    OpenAIRealtimeConfig,
    RealtimeAgent,
    RealtimeAgentChat,
)
from tests.fixtures import *


def _make_realtime_agent(agent, org):
    """Self-contained RealtimeAgent creation — mirrors init_realtime_test.py's
    helper (the shared `wikipedia_agent_with_configured_realtime` fixture is
    broken independent of this change, see that file's note)."""
    config = OpenAIRealtimeConfig.objects.create(custom_name="test-openai", org=org)
    return RealtimeAgent.objects.create(agent=agent, openai_config=config)


def _make_chat(rt_agent, connection_key="conn-under-test"):
    return RealtimeAgentChat.objects.create(
        rt_agent=rt_agent, connection_key=connection_key
    )


@pytest.mark.django_db
class TestRealtimeAgentChatEnd:
    """Security fix: `end` (POST /realtime-agent-chats/end/) looked up the
    target chat by `connection_key` alone, with no org filter, and previously
    accepted any authenticated JWT session or API key
    (`IsAuthenticatedOrApiKey`) — so any authenticated caller could end/mutate
    another org's realtime chat by guessing/observing its `connection_key`.

    Fixed by restricting the action to `key_type=SYSTEM` API-key callers only
    (`IsSystemApiKeyAuthenticated`), mirroring `RealtimeChannelViewSet.
    lookup_by_token` / `InitRealtimeAPIView`'s pattern — the only
    legitimate caller is the `realtime` service's
    `AgentChatEndClient.end_chat`, which authenticates with the
    env-seeded system API key."""

    def _url(self):
        return reverse("realtimeagentchat-end")

    def test_succeeds_with_system_api_key_for_any_org(
        self, wikipedia_agent, default_org, api_client, env_api_key
    ):
        """The trusted internal caller has no org context to send; the system
        API key itself is the trust boundary, regardless of which org owns
        the chat (mirrors lookup_by_token's cross-org-by-design behavior)."""
        rt_agent = _make_realtime_agent(wikipedia_agent, default_org)
        chat = _make_chat(rt_agent)
        raw_key, _key = env_api_key
        api_client.credentials(HTTP_X_API_KEY=raw_key)

        response = api_client.post(
            self._url(),
            data={
                "connection_key": chat.connection_key,
                "duration_seconds": 12.5,
                "end_reason": "completed",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        chat.refresh_from_db()
        assert chat.ended_at is not None
        assert chat.duration_seconds == 12.5
        assert chat.end_reason == "completed"

    def test_second_end_keeps_the_first_duration_and_reason(
        self, wikipedia_agent, default_org, api_client, env_api_key, monkeypatch
    ):
        from tables.views import model_view_sets

        revoked_chat_ids = []
        monkeypatch.setattr(
            model_view_sets.session_credential_service,
            "revoke_for_realtime_chat",
            revoked_chat_ids.append,
        )
        rt_agent = _make_realtime_agent(wikipedia_agent, default_org)
        chat = _make_chat(rt_agent, connection_key="conn-ended-twice")
        raw_key, _key = env_api_key
        api_client.credentials(HTTP_X_API_KEY=raw_key)

        first = api_client.post(
            self._url(),
            data={"connection_key": chat.connection_key, "duration_seconds": 12.5, "end_reason": "error"},
            format="json",
        )
        chat.refresh_from_db()
        first_ended_at = chat.ended_at
        second = api_client.post(
            self._url(),
            data={"connection_key": chat.connection_key, "duration_seconds": 99.0, "end_reason": "completed"},
            format="json",
        )

        assert first.status_code == status.HTTP_200_OK
        assert second.status_code == status.HTTP_200_OK
        chat.refresh_from_db()
        assert chat.ended_at == first_ended_at
        assert chat.duration_seconds == 12.5
        assert chat.end_reason == "error"
        assert revoked_chat_ids == [chat.id, chat.id]

    @pytest.mark.parametrize(
        "end_reason", ["max_duration_exceeded", "something_else", 5], ids=["too-long", "unknown", "not-a-string"]
    )
    def test_unknown_end_reason_is_stored_as_error_and_still_revokes(
        self, wikipedia_agent, default_org, api_client, env_api_key, monkeypatch, end_reason
    ):
        from tables.views import model_view_sets

        revoked_chat_ids = []
        monkeypatch.setattr(
            model_view_sets.session_credential_service,
            "revoke_for_realtime_chat",
            revoked_chat_ids.append,
        )
        chat = _make_chat(_make_realtime_agent(wikipedia_agent, default_org), "conn-bad-reason")
        api_client.credentials(HTTP_X_API_KEY=env_api_key[0])

        response = api_client.post(
            self._url(),
            data={"connection_key": chat.connection_key, "end_reason": end_reason},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        chat.refresh_from_db()
        assert chat.end_reason == "error"
        assert revoked_chat_ids == [chat.id]

    def test_missing_end_reason_defaults_to_completed(
        self, wikipedia_agent, default_org, api_client, env_api_key
    ):
        chat = _make_chat(_make_realtime_agent(wikipedia_agent, default_org), "conn-no-reason")
        api_client.credentials(HTTP_X_API_KEY=env_api_key[0])

        api_client.post(self._url(), data={"connection_key": chat.connection_key}, format="json")

        chat.refresh_from_db()
        assert chat.end_reason == "completed"

    @pytest.mark.parametrize("duration", ["abc", None, [1], {"a": 1}], ids=["text", "null", "list", "dict"])
    def test_non_numeric_duration_is_stored_as_null_and_still_revokes(
        self, wikipedia_agent, default_org, api_client, env_api_key, monkeypatch, duration
    ):
        from tables.views import model_view_sets

        revoked_chat_ids = []
        monkeypatch.setattr(
            model_view_sets.session_credential_service,
            "revoke_for_realtime_chat",
            revoked_chat_ids.append,
        )
        chat = _make_chat(_make_realtime_agent(wikipedia_agent, default_org), "conn-bad-duration")
        api_client.credentials(HTTP_X_API_KEY=env_api_key[0])

        response = api_client.post(
            self._url(),
            data={"connection_key": chat.connection_key, "duration_seconds": duration},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        chat.refresh_from_db()
        assert chat.duration_seconds is None
        assert chat.ended_at is not None
        assert revoked_chat_ids == [chat.id]

    def test_update_failure_does_not_skip_the_revoke(
        self, wikipedia_agent, default_org, api_client, env_api_key, monkeypatch
    ):
        from django.db.models.query import QuerySet
        from tables.views import model_view_sets

        revoked_chat_ids = []
        monkeypatch.setattr(
            model_view_sets.session_credential_service,
            "revoke_for_realtime_chat",
            revoked_chat_ids.append,
        )

        def failing_update(self, **kwargs):
            raise RuntimeError("database unavailable")

        monkeypatch.setattr(QuerySet, "update", failing_update)
        chat = _make_chat(_make_realtime_agent(wikipedia_agent, default_org), "conn-update-fails")
        api_client.credentials(HTTP_X_API_KEY=env_api_key[0])

        response = api_client.post(
            self._url(), data={"connection_key": chat.connection_key}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK
        assert revoked_chat_ids == [chat.id]

    def test_jwt_session_from_another_org_cannot_end_chat(
        self, wikipedia_agent, default_org, auth_client
    ):
        """Regression guard for the fixed bug: a regular JWT session (member
        of default_org) must not be able to end a chat belonging to a
        *different* org just by knowing its connection_key."""
        other_org = Organization.objects.create(name="Some Other Org")
        rt_agent = _make_realtime_agent(wikipedia_agent, other_org)
        chat = _make_chat(rt_agent, connection_key="conn-other-org")

        response = auth_client.post(
            self._url(),
            data={"connection_key": chat.connection_key},
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        chat.refresh_from_db()
        assert chat.ended_at is None

    def test_jwt_session_from_same_org_cannot_end_chat(
        self, wikipedia_agent, default_org, auth_client
    ):
        """Even a same-org JWT session must be rejected — `end` is an
        internal-service-only callback, not a user-facing action; only the
        system API key may call it."""
        rt_agent = _make_realtime_agent(wikipedia_agent, default_org)
        chat = _make_chat(rt_agent, connection_key="conn-same-org")

        response = auth_client.post(
            self._url(),
            data={"connection_key": chat.connection_key},
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        chat.refresh_from_db()
        assert chat.ended_at is None

    def test_user_scoped_api_key_cannot_end_chat(
        self, wikipedia_agent, default_org, api_client, user_api_key
    ):
        """Companion pattern: a self-issued `key_type=USER`
        API key (any org member can mint one) must not hit the trusted-caller
        bypass either — only `key_type=SYSTEM` may call `end`."""
        rt_agent = _make_realtime_agent(wikipedia_agent, default_org)
        chat = _make_chat(rt_agent, connection_key="conn-user-key")
        raw_key, _key = user_api_key
        api_client.credentials(HTTP_X_API_KEY=raw_key)

        response = api_client.post(
            self._url(),
            data={"connection_key": chat.connection_key},
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        chat.refresh_from_db()
        assert chat.ended_at is None

    def test_missing_connection_key_returns_400(self, api_client, env_api_key, db):
        raw_key, _key = env_api_key
        api_client.credentials(HTTP_X_API_KEY=raw_key)

        response = api_client.post(self._url(), data={}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
