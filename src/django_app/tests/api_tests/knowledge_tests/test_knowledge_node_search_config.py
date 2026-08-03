"""
API tests for KnowledgeNode search config: create / update (partial merge) / get,
for both naive and graph RAG.
"""

import pytest
from django.urls import reverse
from rest_framework import status

from tables.models.graph_models import Graph, KnowledgeNode
from tables.models.knowledge_models import BaseRagType, SourceCollection
from tables.models.knowledge_models import (
    KnowledgeNodeNaiveRagSearchConfig,
    KnowledgeNodeGraphRagBasicSearchConfig,
    KnowledgeNodeGraphRagLocalSearchConfig,
)


@pytest.fixture
def auth_client(api_client, regular_user, default_org):
    api_client.force_authenticate(user=regular_user)
    api_client.credentials(HTTP_X_ORGANIZATION_ID=str(default_org.id))
    return api_client


@pytest.fixture
def graph(default_org):
    return Graph.objects.create(org=default_org, name="KB Flow")


@pytest.fixture
def collection(default_org):
    return SourceCollection.objects.create(org=default_org, collection_name="KB")


@pytest.fixture
def naive_rag_type(collection):
    return BaseRagType.objects.create(
        source_collection=collection, rag_type=BaseRagType.RagType.NAIVE
    )


@pytest.fixture
def other_collection_rag_type(default_org):
    other = SourceCollection.objects.create(org=default_org, collection_name="Other")
    return BaseRagType.objects.create(
        source_collection=other, rag_type=BaseRagType.RagType.NAIVE
    )


@pytest.fixture
def node(graph):
    """Bare KnowledgeNode, no configs yet."""
    return KnowledgeNode.objects.create(graph=graph)


def list_url():
    return reverse("knowledgenode-list")


def detail_url(node_id):
    return reverse("knowledgenode-detail", args=[node_id])


@pytest.mark.django_db
class TestKnowledgeNodeCreate:
    def test_create_bare_node(self, auth_client, graph):
        resp = auth_client.post(list_url(), {"graph": graph.id}, format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.json()["search_configs"] is None

    def test_create_with_naive_config(self, auth_client, graph):
        data = {
            "graph": graph.id,
            "search_configs": {
                "naive": {"search_limit": 7, "similarity_threshold": 0.5}
            },
        }
        resp = auth_client.post(list_url(), data, format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        naive = resp.json()["search_configs"]["naive"]
        assert naive["search_limit"] == 7
        assert naive["similarity_threshold"] == 0.5

        node = KnowledgeNode.objects.get(id=resp.json()["id"])
        cfg = KnowledgeNodeNaiveRagSearchConfig.objects.get(knowledge_node=node)
        assert cfg.search_limit == 7
        assert float(cfg.similarity_threshold) == 0.5

    def test_create_with_graph_basic_config(self, auth_client, graph):
        data = {
            "graph": graph.id,
            "search_configs": {
                "graph": {
                    "search_method": "basic",
                    "basic": {"k": 8, "max_context_tokens": 8000},
                }
            },
        }
        resp = auth_client.post(list_url(), data, format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        gr = resp.json()["search_configs"]["graph"]
        assert gr["search_method"] == "basic"
        assert gr["basic"]["k"] == 8
        assert gr["local"] is None

        node = KnowledgeNode.objects.get(id=resp.json()["id"])
        assert node.search_method == "basic"
        assert (
            KnowledgeNodeGraphRagBasicSearchConfig.objects.get(knowledge_node=node).k
            == 8
        )

    def test_create_with_graph_local_config(self, auth_client, graph):
        data = {
            "graph": graph.id,
            "search_configs": {
                "graph": {
                    "search_method": "local",
                    "local": {"top_k_entities": 20, "text_unit_prop": 0.6},
                }
            },
        }
        resp = auth_client.post(list_url(), data, format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        local = resp.json()["search_configs"]["graph"]["local"]
        assert local["top_k_entities"] == 20
        assert local["text_unit_prop"] == 0.6

    def test_create_with_both_rag_types(self, auth_client, graph):
        data = {
            "graph": graph.id,
            "search_configs": {
                "naive": {"search_limit": 4},
                "graph": {"search_method": "basic", "basic": {"k": 5}},
            },
        }
        resp = auth_client.post(list_url(), data, format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        cfg = resp.json()["search_configs"]
        assert cfg["naive"]["search_limit"] == 4
        assert cfg["graph"]["basic"]["k"] == 5

    def test_rag_type_without_collection_fails(
        self, auth_client, graph, naive_rag_type
    ):
        resp = auth_client.post(
            list_url(),
            {"graph": graph.id, "rag_type": naive_rag_type.pk},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "Required when rag_type is set." in str(resp.json())

    def test_rag_type_from_other_collection_fails(
        self, auth_client, graph, collection, other_collection_rag_type
    ):
        data = {
            "graph": graph.id,
            "source_collection": collection.collection_id,
            "rag_type": other_collection_rag_type.pk,
        }
        resp = auth_client.post(list_url(), data, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "rag_type must belong" in str(resp.json())

    def test_empty_search_configs_fails(self, auth_client, graph):
        resp = auth_client.post(
            list_url(), {"graph": graph.id, "search_configs": {}}, format="json"
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "At least one RAG type" in str(resp.json())

    @pytest.mark.parametrize(
        "bad",
        [
            {"naive": {"search_limit": 0}},
            {"naive": {"similarity_threshold": 1.5}},
            {"graph": {"basic": {"k": 200}}},
        ],
    )
    def test_out_of_range_values_fail(self, auth_client, graph, bad):
        resp = auth_client.post(
            list_url(), {"graph": graph.id, "search_configs": bad}, format="json"
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestKnowledgeNodeUpdate:
    @pytest.fixture
    def node_with_naive(self, node):
        KnowledgeNodeNaiveRagSearchConfig.objects.create(
            knowledge_node=node, search_limit=3, similarity_threshold=0.2
        )
        return node

    @pytest.fixture
    def node_with_graph(self, node):
        node.search_method = "basic"
        node.save(update_fields=["search_method"])
        KnowledgeNodeGraphRagBasicSearchConfig.objects.create(knowledge_node=node, k=10)
        KnowledgeNodeGraphRagLocalSearchConfig.objects.create(
            knowledge_node=node, top_k_entities=10
        )
        return node

    def test_patch_naive_limit_keeps_threshold(self, auth_client, node_with_naive):
        resp = auth_client.patch(
            detail_url(node_with_naive.id),
            {"search_configs": {"naive": {"search_limit": 15}}},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        naive = resp.json()["search_configs"]["naive"]
        assert naive["search_limit"] == 15
        assert naive["similarity_threshold"] == 0.2

    def test_patch_basic_k_keeps_local_and_method(self, auth_client, node_with_graph):
        resp = auth_client.patch(
            detail_url(node_with_graph.id),
            {"search_configs": {"graph": {"basic": {"k": 25}}}},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        gr = resp.json()["search_configs"]["graph"]
        assert gr["basic"]["k"] == 25
        assert gr["search_method"] == "basic"
        assert gr["local"]["top_k_entities"] == 10

    def test_patch_switch_search_method(self, auth_client, node_with_graph):
        resp = auth_client.patch(
            detail_url(node_with_graph.id),
            {"search_configs": {"graph": {"search_method": "local"}}},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["search_configs"]["graph"]["search_method"] == "local"
        node_with_graph.refresh_from_db()
        assert node_with_graph.search_method == "local"

    def test_patch_add_graph_to_naive_only_node(self, auth_client, node_with_naive):
        resp = auth_client.patch(
            detail_url(node_with_naive.id),
            {
                "search_configs": {
                    "graph": {"search_method": "basic", "basic": {"k": 6}}
                }
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        cfg = resp.json()["search_configs"]
        assert cfg["naive"]["search_limit"] == 3
        assert cfg["graph"]["basic"]["k"] == 6

    def test_put_merges_not_wipes_configs(self, auth_client, graph, node_with_naive):
        resp = auth_client.put(
            detail_url(node_with_naive.id),
            {
                "graph": graph.id,
                "search_configs": {
                    "graph": {"search_method": "basic", "basic": {"k": 9}}
                },
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["search_configs"]["naive"]["search_limit"] == 3

    def test_content_hash_precondition(self, auth_client, node_with_naive):
        current = auth_client.get(detail_url(node_with_naive.id)).json()["content_hash"]

        stale = auth_client.patch(
            detail_url(node_with_naive.id),
            {"query": "x", "content_hash": "deadbeef"},
            format="json",
        )
        assert stale.status_code == status.HTTP_409_CONFLICT

        ok = auth_client.patch(
            detail_url(node_with_naive.id),
            {"query": "y", "content_hash": current},
            format="json",
        )
        assert ok.status_code == status.HTTP_200_OK

        no_hash = auth_client.patch(
            detail_url(node_with_naive.id), {"query": "z"}, format="json"
        )
        assert no_hash.status_code == status.HTTP_200_OK


@pytest.mark.django_db
class TestKnowledgeNodeGet:
    def test_retrieve_no_configs_returns_null(self, auth_client, node):
        resp = auth_client.get(detail_url(node.id))
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["search_configs"] is None

    def test_retrieve_naive_only(self, auth_client, node):
        KnowledgeNodeNaiveRagSearchConfig.objects.create(knowledge_node=node)
        cfg = auth_client.get(detail_url(node.id)).json()["search_configs"]
        assert "naive" in cfg
        assert "graph" not in cfg
        assert cfg["naive"]["search_limit"] == 3

    def test_retrieve_graph_only(self, auth_client, node):
        node.search_method = "basic"
        node.save(update_fields=["search_method"])
        KnowledgeNodeGraphRagBasicSearchConfig.objects.create(knowledge_node=node)
        cfg = auth_client.get(detail_url(node.id)).json()["search_configs"]
        assert "graph" in cfg and "naive" not in cfg
        assert cfg["graph"]["search_method"] == "basic"
        assert cfg["graph"]["basic"]["k"] == 10
        assert cfg["graph"]["local"] is None

    def test_retrieve_both(self, auth_client, node):
        KnowledgeNodeNaiveRagSearchConfig.objects.create(knowledge_node=node)
        KnowledgeNodeGraphRagLocalSearchConfig.objects.create(knowledge_node=node)
        cfg = auth_client.get(detail_url(node.id)).json()["search_configs"]
        assert "naive" in cfg and "graph" in cfg

    def test_list_includes_search_configs(self, auth_client, node):
        KnowledgeNodeNaiveRagSearchConfig.objects.create(knowledge_node=node)
        body = auth_client.get(list_url()).json()
        items = (
            body["results"] if isinstance(body, dict) and "results" in body else body
        )
        assert any(i["id"] == node.id and i["search_configs"] for i in items)
