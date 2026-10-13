"""
Unit tests for NaiveRagChunkSearchView.

They verify only the view's own responsibilities: org scoping of the
document config, query-param parsing, validation, mapping service results /
exceptions to HTTP responses, and the shape of the response payload. Search
semantics (case-insensitive substring match, ordering) belong to
service-level tests.
"""

from unittest.mock import patch

import pytest
from rest_framework import status
from rest_framework.test import APIRequestFactory, force_authenticate

from tables.exceptions import DocumentConfigNotFoundException
from tables.views.knowledge_views.naive_rag_views import NaiveRagChunkSearchView
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


pytestmark = pytest.mark.django_db

SEARCH_PATH = "/dummy/"  # APIRequestFactory bypasses URL routing; path is unused.

view = NaiveRagChunkSearchView.as_view()


def _call_view(user, org, document_config, query_params=None):
    """Build a GET request acting in `org` as `user` and invoke the view directly."""
    request = APIRequestFactory().get(
        SEARCH_PATH, query_params or {}, HTTP_X_ORGANIZATION_ID=str(org.id)
    )
    force_authenticate(request, user=user)
    return view(
        request,
        naive_rag_id=document_config.naive_rag_id,
        document_config_id=document_config.pk,
    )


@pytest.fixture
def get_search(regular_user, default_org, naive_rag_document_config):
    """GET the view as an Org Admin of the org that owns the document config."""

    def _get(query_params=None):
        return _call_view(
            regular_user, default_org, naive_rag_document_config, query_params
        )

    return _get


SERVICE_PATH = (
    "tables.views.knowledge_views.naive_rag_views.NaiveRagService.search_chunks"
)


class TestChunkSearchViewSuccess:
    """View correctly forwards params to the service and shapes the response."""

    def test_returns_payload_from_service(
        self, get_search, naive_rag_document_config
    ):
        service_result = {
            "total_matches": 1,
            "preview_chunk_ids": [20],
        }
        with patch(SERVICE_PATH, return_value=service_result) as mock_search:
            resp = get_search({"q": "hello world"})

        naive_rag_id = naive_rag_document_config.naive_rag_id
        document_config_id = naive_rag_document_config.pk
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data == {
            "naive_rag_id": naive_rag_id,
            "document_config_id": document_config_id,
            "query": "hello world",
            "total_matches": 1,
            "limit": NaiveRagChunkSearchView.DEFAULT_LIMIT,
            "offset": 0,
            "preview_chunk_ids": [20],
        }
        mock_search.assert_called_once_with(
            naive_rag_id=naive_rag_id,
            document_config_id=document_config_id,
            query="hello world",
            limit=NaiveRagChunkSearchView.DEFAULT_LIMIT,
            offset=0,
        )

    def test_preserves_whitespace_around_query(self, get_search):
        with patch(SERVICE_PATH, return_value=_empty_result()) as mock_search:
            get_search({"q": "  banana  "})

        assert mock_search.call_args.kwargs["query"] == "  banana  "

    def test_passes_custom_limit_and_offset_to_service(self, get_search):
        with patch(SERVICE_PATH, return_value=_empty_result()) as mock_search:
            get_search({"q": "foo", "limit": 5, "offset": 10})

        kwargs = mock_search.call_args.kwargs
        assert kwargs["limit"] == 5
        assert kwargs["offset"] == 10

    def test_caps_limit_at_max_limit(self, get_search):
        with patch(SERVICE_PATH, return_value=_empty_result()) as mock_search:
            get_search({"q": "foo", "limit": 10_000})

        assert (
            mock_search.call_args.kwargs["limit"] == NaiveRagChunkSearchView.MAX_LIMIT
        )

    def test_uses_default_limit_when_omitted(self, get_search):
        with patch(SERVICE_PATH, return_value=_empty_result()) as mock_search:
            get_search({"q": "foo"})

        assert (
            mock_search.call_args.kwargs["limit"]
            == NaiveRagChunkSearchView.DEFAULT_LIMIT
        )


class TestChunkSearchViewValidation:
    """View-level validation runs before the service is invoked."""

    def test_missing_q_returns_400(self, get_search):
        with patch(SERVICE_PATH) as mock_search:
            resp = get_search()
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["message"].startswith("q:")
        mock_search.assert_not_called()

    def test_whitespace_only_q_is_allowed(self, get_search):
        with patch(SERVICE_PATH, return_value=_empty_result()) as mock_search:
            resp = get_search({"q": "   "})
        assert resp.status_code == status.HTTP_200_OK
        assert mock_search.call_args.kwargs["query"] == "   "

    def test_non_integer_limit_returns_400(self, get_search):
        with patch(SERVICE_PATH) as mock_search:
            resp = get_search({"q": "foo", "limit": "abc"})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["message"].startswith("limit:")
        mock_search.assert_not_called()

    def test_non_integer_offset_returns_400(self, get_search):
        with patch(SERVICE_PATH) as mock_search:
            resp = get_search({"q": "foo", "offset": "abc"})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["message"].startswith("offset:")
        mock_search.assert_not_called()

    def test_negative_limit_returns_400(self, get_search):
        with patch(SERVICE_PATH) as mock_search:
            resp = get_search({"q": "foo", "limit": -1})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["message"].startswith("limit:")
        mock_search.assert_not_called()

    def test_negative_offset_returns_400(self, get_search):
        with patch(SERVICE_PATH) as mock_search:
            resp = get_search({"q": "foo", "offset": -1})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["message"].startswith("offset:")
        mock_search.assert_not_called()


class TestChunkSearchViewOrgScoping:
    """The document config is resolved in the caller's active org first."""

    def test_document_config_in_other_org_returns_404(
        self, admin_acme, acme, naive_rag_document_config
    ):
        with patch(SERVICE_PATH) as mock_search:
            resp = _call_view(
                admin_acme, acme, naive_rag_document_config, {"q": "foo"}
            )

        assert resp.status_code == status.HTTP_404_NOT_FOUND
        mock_search.assert_not_called()


class TestChunkSearchViewExceptionMapping:
    """Service exceptions are translated to the right HTTP status codes."""

    def test_document_config_not_found_returns_404(
        self, get_search, naive_rag_document_config
    ):
        exc = DocumentConfigNotFoundException(naive_rag_document_config.pk)
        with patch(SERVICE_PATH, side_effect=exc):
            resp = get_search({"q": "foo"})

        assert resp.status_code == status.HTTP_404_NOT_FOUND
        assert resp.data == {"error": str(exc)}

    def test_unexpected_exception_returns_500(self, get_search):
        with patch(SERVICE_PATH, side_effect=RuntimeError("boom")):
            resp = get_search({"q": "foo"})

        assert resp.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert "boom" in resp.data["error"]


def _empty_result():
    return {
        "total_matches": 0,
        "preview_chunk_ids": [],
    }
