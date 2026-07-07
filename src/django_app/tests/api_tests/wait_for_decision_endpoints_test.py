"""
Tests for the session-level human-in-the-loop "decision" endpoints
(EST-3285 item 4.8):

    POST /api/sessions/<id>/decisions/open/
    POST /api/sessions/<id>/decisions/answer/
    POST /api/sessions/<id>/decisions/cancel/

These are called by wait_for_decision_tool (src/shared/tools/wait_for_decision_tool/)
over REST, exactly like subflow_tool/schedule_manager_tool call other
existing REST endpoints -- NOT via the in-process
get_wait_for_user_callback/AnswerToLLM flat-string path, which remains
completely untouched.

NOTE on auth in this test module: `tests/settings.py` sets
DEFAULT_AUTHENTICATION_CLASSES/DEFAULT_PERMISSION_CLASSES to `[]` for the
whole test suite (see that file's docstring-less override), so
`api_client.credentials(...)` headers (JWT bearer, X-Api-Key) are never
actually processed by DRF in tests -- `request.user`/`request.auth` stay
Anonymous/None regardless. This is why `tests/graph_collab/conftest.py`
already overrides `auth_client` to use `force_authenticate` instead; we do
the same here, and set `request.auth` explicitly (via `token=`) to exercise
the API-key-specific code paths (env-seeded system key vs. user-owned key).
"""

import pytest

from django.contrib.auth.models import AnonymousUser
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from tables.models import Graph, GraphOrganization, Organization, Session
from tests.fixtures import *  # noqa: F401,F403


@pytest.fixture
def auth_client(api_client, regular_user) -> APIClient:
    """Override the global JWT-header-based `auth_client` (see module
    docstring): force_authenticate sets request.user directly, bypassing the
    disabled test-settings authentication classes."""
    api_client.force_authenticate(user=regular_user)
    return api_client


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="org-b")


@pytest.fixture
def graph_in_default_org(graph: Graph, default_org: Organization) -> Graph:
    GraphOrganization.objects.create(graph=graph, organization=default_org)
    return graph


@pytest.fixture
def graph_in_org_b(org_b: Organization) -> Graph:
    graph = Graph.objects.create(name="graph-in-org-b")
    GraphOrganization.objects.create(graph=graph, organization=org_b)
    return graph


@pytest.fixture
def session_in_default_org(graph_in_default_org) -> Session:
    return Session.objects.create(
        graph=graph_in_default_org, status=Session.SessionStatus.RUN
    )


@pytest.fixture
def session_in_org_b(graph_in_org_b) -> Session:
    return Session.objects.create(
        graph=graph_in_org_b, status=Session.SessionStatus.RUN
    )


@pytest.fixture
def session_without_org(graph: Graph) -> Session:
    return Session.objects.create(graph=graph, status=Session.SessionStatus.RUN)


def _open_url(session_id):
    return reverse("open-session-decision", kwargs={"session_id": session_id})


def _answer_url(session_id):
    return reverse("answer-session-decision", kwargs={"session_id": session_id})


def _cancel_url(session_id):
    return reverse("cancel-session-decision", kwargs={"session_id": session_id})


def _system_key_client(env_api_key) -> APIClient:
    """A client authenticated as an env-seeded, ownerless (`created_by=None`)
    ApiKey -- request.user is AnonymousUser but request.auth is the real
    ApiKey row, exactly as `JwtOrApiKeyAuthentication._authenticate_api_key`
    resolves it in production."""
    _raw, key = env_api_key
    client = APIClient()
    client.force_authenticate(user=AnonymousUser(), token=key)
    return client


@pytest.mark.django_db
class TestOpenSessionDecision:
    def test_opens_decision_and_sets_wait_for_user(
        self, auth_client, redis_client_mock, session_in_default_org
    ):
        response = auth_client.post(
            _open_url(session_in_default_org.pk),
            {
                "question": "Proceed with deployment?",
                "options": ["yes", "no"],
                "allow_free_text": True,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED, response.content
        decision_id = response.data["decision_id"]
        assert response.data["status"] == Session.SessionStatus.WAIT_FOR_USER

        session_in_default_org.refresh_from_db()
        assert session_in_default_org.status == Session.SessionStatus.WAIT_FOR_USER
        decision = session_in_default_org.status_data["decision"]
        assert decision["decision_id"] == decision_id
        assert decision["question"] == "Proceed with deployment?"
        assert decision["options"] == ["yes", "no"]
        assert decision["allow_free_text"] is True
        assert decision["answer"] is None

        # A GraphSessionMessage was created + republished for the FE.
        from tables.models.graph_models import GraphSessionMessage

        message = GraphSessionMessage.objects.get(session=session_in_default_org)
        assert message.message_data["message_type"] == "wait_for_decision"
        assert message.message_data["decision_id"] == decision_id
        redis_client_mock.publish.assert_called()

    def test_rejects_too_few_options(
        self, auth_client, redis_client_mock, session_in_default_org
    ):
        response = auth_client.post(
            _open_url(session_in_default_org.pk),
            {"question": "Proceed?", "options": ["only-one"]},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content

    def test_rejects_too_many_options(
        self, auth_client, redis_client_mock, session_in_default_org
    ):
        response = auth_client.post(
            _open_url(session_in_default_org.pk),
            {"question": "Proceed?", "options": ["a", "b", "c", "d", "e"]},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content

    def test_missing_session_returns_404(self, auth_client, redis_client_mock):
        response = auth_client.post(
            _open_url(999999),
            {"question": "Proceed?", "options": ["yes", "no"]},
            format="json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_cross_org_session_is_rejected(
        self, auth_client, redis_client_mock, session_in_org_b
    ):
        """`regular_user` (auth_client) belongs to `default_org`, not org-b --
        must not be able to open a decision on org-b's session."""
        response = auth_client.post(
            _open_url(session_in_org_b.pk),
            {"question": "Proceed?", "options": ["yes", "no"]},
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content

        session_in_org_b.refresh_from_db()
        assert session_in_org_b.status == Session.SessionStatus.RUN
        assert "decision" not in (session_in_org_b.status_data or {})

    def test_session_without_org_is_accepted(
        self, auth_client, redis_client_mock, session_without_org
    ):
        """No GraphOrganization at all -- treated as the same 'no org' bucket
        (mirrors run_session_parent_org_test's no-org acceptance case)."""
        response = auth_client.post(
            _open_url(session_without_org.pk),
            {"question": "Proceed?", "options": ["yes", "no"]},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.content

    def test_env_system_api_key_is_treated_as_trusted(
        self, redis_client_mock, session_in_org_b, env_api_key
    ):
        """An env-seeded (ownerless) system API key must be able to open a
        decision on ANY org's session -- it has no org to be scoped to."""
        client = _system_key_client(env_api_key)

        response = client.post(
            _open_url(session_in_org_b.pk),
            {"question": "Proceed?", "options": ["yes", "no"]},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.content

    def test_unauthenticated_request_is_rejected(
        self, api_client, redis_client_mock, session_in_default_org
    ):
        """Real deployments never reach the view at all when unauthenticated
        (DRF's IsAuthenticated permission returns 401 first) -- but since
        test settings disable DRF auth/permission enforcement (see module
        docstring), this exercises the view's own defense-in-depth check
        instead, which returns 403."""
        response = api_client.post(
            _open_url(session_in_default_org.pk),
            {"question": "Proceed?", "options": ["yes", "no"]},
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestAnswerSessionDecision:
    def _open(self, auth_client, session, allow_free_text=True):
        response = auth_client.post(
            _open_url(session.pk),
            {
                "question": "Proceed?",
                "options": ["yes", "no"],
                "allow_free_text": allow_free_text,
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        return response.data["decision_id"]

    def test_answer_with_option_index_resumes_session(
        self, auth_client, redis_client_mock, session_in_default_org
    ):
        decision_id = self._open(auth_client, session_in_default_org)

        response = auth_client.post(
            _answer_url(session_in_default_org.pk),
            {"decision_id": decision_id, "option_index": 0, "free_text": None},
            format="json",
        )
        assert response.status_code == status.HTTP_202_ACCEPTED, response.content

        session_in_default_org.refresh_from_db()
        assert session_in_default_org.status == Session.SessionStatus.RUN
        decision = session_in_default_org.status_data["decision"]
        assert decision["answer"] == {"option_index": 0, "free_text": None}

    def test_answer_with_free_text_only(
        self, auth_client, redis_client_mock, session_in_default_org
    ):
        decision_id = self._open(auth_client, session_in_default_org)

        response = auth_client.post(
            _answer_url(session_in_default_org.pk),
            {"decision_id": decision_id, "free_text": "actually, wait"},
            format="json",
        )
        assert response.status_code == status.HTTP_202_ACCEPTED, response.content

        session_in_default_org.refresh_from_db()
        assert session_in_default_org.status == Session.SessionStatus.RUN
        decision = session_in_default_org.status_data["decision"]
        assert decision["answer"]["free_text"] == "actually, wait"

    def test_free_text_rejected_when_not_allowed(
        self, auth_client, redis_client_mock, session_in_default_org
    ):
        decision_id = self._open(
            auth_client, session_in_default_org, allow_free_text=False
        )

        response = auth_client.post(
            _answer_url(session_in_default_org.pk),
            {"decision_id": decision_id, "free_text": "nope"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content

    def test_option_index_out_of_range_rejected(
        self, auth_client, redis_client_mock, session_in_default_org
    ):
        decision_id = self._open(auth_client, session_in_default_org)

        response = auth_client.post(
            _answer_url(session_in_default_org.pk),
            {"decision_id": decision_id, "option_index": 99},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content

    def test_wrong_decision_id_rejected(
        self, auth_client, redis_client_mock, session_in_default_org
    ):
        self._open(auth_client, session_in_default_org)

        response = auth_client.post(
            _answer_url(session_in_default_org.pk),
            {"decision_id": "not-the-real-id", "option_index": 0},
            format="json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND, response.content

    def test_answer_when_session_not_waiting_is_rejected(
        self, auth_client, redis_client_mock, session_in_default_org
    ):
        response = auth_client.post(
            _answer_url(session_in_default_org.pk),
            {"decision_id": "whatever", "option_index": 0},
            format="json",
        )
        assert response.status_code == status.HTTP_409_CONFLICT, response.content

    def test_cross_org_answer_is_rejected(
        self, auth_client, redis_client_mock, session_in_org_b, env_api_key
    ):
        """Open as the trusted system key (bypasses org check), then confirm
        the regular (default_org) user still cannot answer org-b's
        decision."""
        system_client = _system_key_client(env_api_key)
        open_response = system_client.post(
            _open_url(session_in_org_b.pk),
            {"question": "Proceed?", "options": ["yes", "no"]},
            format="json",
        )
        decision_id = open_response.data["decision_id"]

        response = auth_client.post(
            _answer_url(session_in_org_b.pk),
            {"decision_id": decision_id, "option_index": 0},
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content


@pytest.mark.django_db
class TestCancelSessionDecision:
    def _open(self, auth_client, session):
        response = auth_client.post(
            _open_url(session.pk),
            {"question": "Proceed?", "options": ["yes", "no"]},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        return response.data["decision_id"]

    def test_cancel_resets_status_and_clears_decision(
        self, auth_client, redis_client_mock, session_in_default_org
    ):
        decision_id = self._open(auth_client, session_in_default_org)

        response = auth_client.post(
            _cancel_url(session_in_default_org.pk),
            {"decision_id": decision_id},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.data["cancelled"] is True

        session_in_default_org.refresh_from_db()
        assert session_in_default_org.status == Session.SessionStatus.RUN
        assert "decision" not in (session_in_default_org.status_data or {})

    def test_cancel_is_idempotent_noop_when_already_resolved(
        self, auth_client, redis_client_mock, session_in_default_org
    ):
        decision_id = self._open(auth_client, session_in_default_org)
        auth_client.post(
            _answer_url(session_in_default_org.pk),
            {"decision_id": decision_id, "option_index": 0},
            format="json",
        )

        # Timeout-driven cancel arrives late, after a human already answered.
        response = auth_client.post(
            _cancel_url(session_in_default_org.pk),
            {"decision_id": decision_id},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.data["cancelled"] is False

        session_in_default_org.refresh_from_db()
        # The earlier answer must not be clobbered by the late cancel.
        assert session_in_default_org.status == Session.SessionStatus.RUN
        assert session_in_default_org.status_data["decision"]["answer"] == {
            "option_index": 0,
            "free_text": None,
        }
