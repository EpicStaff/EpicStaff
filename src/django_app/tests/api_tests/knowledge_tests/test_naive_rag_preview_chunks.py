"""Searching and fetching a document config's preview chunks.

GET .../chunks/search/?q= returns the ids of preview chunks whose text contains q
(case-insensitive, spaces kept); POST .../chunks/by-ids/ returns those chunks, in the
order asked, skipping ids of other configs. Both run against real preview chunks.
"""

import pytest
from django.urls import reverse
from rest_framework import status

from tables.models.knowledge_models import NaiveRagDocumentConfig, NaiveRagPreviewChunk
from tables.views.knowledge_views.naive_rag_views import NaiveRagChunkSearchView
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

pytestmark = pytest.mark.django_db

TEXTS = ["Hello World", "say hello  world twice: HELLO WORLD", "nothing here", "  hello world"]


@pytest.fixture
def chunks(naive_rag_document_config):
    return [
        NaiveRagPreviewChunk.objects.create(naive_rag_document_config=naive_rag_document_config, text=text, chunk_index=index)
        for index, text in enumerate(TEXTS)
    ]


def _url(name, config):
    return reverse(name, args=[config.naive_rag_id, config.pk])


@pytest.mark.parametrize(
    ("params", "expected_indexes", "expected_limit"),
    [
        ({"q": "hello world"}, [0, 1, 3], NaiveRagChunkSearchView.DEFAULT_LIMIT),
        # Internal and surrounding spaces are part of the query.
        ({"q": "hello  world"}, [1], NaiveRagChunkSearchView.DEFAULT_LIMIT),
        ({"q": "  hello"}, [3], NaiveRagChunkSearchView.DEFAULT_LIMIT),
        ({"q": "   "}, [], NaiveRagChunkSearchView.DEFAULT_LIMIT),
        ({"q": "hello world", "limit": 1, "offset": 1}, [1], 1),
        ({"q": "hello world", "limit": 10_000}, [0, 1, 3], NaiveRagChunkSearchView.MAX_LIMIT),
    ],
    ids=["match", "internal-spaces", "leading-spaces", "spaces-only", "page", "limit-capped"],
)
def test_search_returns_the_matching_chunk_ids(auth_client, naive_rag_document_config, chunks, params, expected_indexes, expected_limit):
    response = auth_client.get(_url("naive-rag-chunks-search", naive_rag_document_config), params)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["preview_chunk_ids"] == [chunks[index].pk for index in expected_indexes]
    assert response.data["query"] == params["q"]
    assert response.data["limit"] == expected_limit
    if "limit" not in params:
        assert response.data["total_matches"] == len(expected_indexes)


@pytest.mark.parametrize(
    "params",
    [{}, {"q": "x", "limit": "ten"}, {"q": "x", "offset": "one"}, {"q": "x", "limit": -1}, {"q": "x", "offset": -1}],
    ids=["no-query", "limit-not-integer", "offset-not-integer", "negative-limit", "negative-offset"],
)
def test_bad_search_params_are_400(auth_client, naive_rag_document_config, params):
    assert auth_client.get(_url("naive-rag-chunks-search", naive_rag_document_config), params).status_code == 400


def test_by_ids_returns_this_configs_chunks_in_the_order_asked(
    auth_client, naive_rag_document_config, multiple_documents, chunks
):
    sibling_config = NaiveRagDocumentConfig.objects.create(
        naive_rag=naive_rag_document_config.naive_rag, document=multiple_documents[0],
        chunk_strategy="token", chunk_size=1000, chunk_overlap=150,
    )
    sibling_chunk = NaiveRagPreviewChunk.objects.create(naive_rag_document_config=sibling_config, text="other", chunk_index=0)
    wanted = [chunks[2].pk, sibling_chunk.pk, chunks[0].pk, chunks[2].pk, 999_999]

    response = auth_client.post(
        _url("naive-rag-chunks-by-ids", naive_rag_document_config), {"preview_chunk_ids": wanted}, format="json"
    )

    assert response.status_code == status.HTTP_200_OK
    assert [chunk["preview_chunk_id"] for chunk in response.data["chunks"]] == [chunks[2].pk, chunks[0].pk]
    assert response.data["total"] == 2


@pytest.mark.parametrize(
    "body",
    [{}, {"preview_chunk_ids": []}, {"preview_chunk_ids": ["a"]}, {"preview_chunk_ids": [0]}],
    ids=["no-body", "empty-list", "not-integer", "not-positive"],
)
def test_bad_by_ids_body_is_400(auth_client, naive_rag_document_config, body):
    response = auth_client.post(_url("naive-rag-chunks-by-ids", naive_rag_document_config), body, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.parametrize(
    ("name", "method", "payload"),
    [
        ("naive-rag-chunks-search", "get", {"q": "hello"}),
        ("naive-rag-chunks-by-ids", "post", {"preview_chunk_ids": [1]}),
    ],
    ids=["search", "by-ids"],
)
def test_another_orgs_document_config_is_404(client_as, admin_acme, acme, naive_rag_document_config, chunks, name, method, payload):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

    response = getattr(client, method)(_url(name, naive_rag_document_config), payload, format="json" if method == "post" else None)

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert "Hello" not in str(response.data)


@pytest.mark.parametrize(("name", "method", "payload"), [("naive-rag-chunks-search", "get", {"q": "x"}), ("naive-rag-chunks-by-ids", "post", {"preview_chunk_ids": [1]})])
def test_a_config_under_another_rag_id_is_404(auth_client, naive_rag_document_config, name, method, payload):
    url = reverse(name, args=[naive_rag_document_config.naive_rag_id + 1000, naive_rag_document_config.pk])

    response = getattr(auth_client, method)(url, payload, format="json" if method == "post" else None)

    assert response.status_code == status.HTTP_404_NOT_FOUND
