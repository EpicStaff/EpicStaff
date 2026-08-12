"""
API tests for KnowledgeNode search config: create / update (partial merge) / get,
for both naive and graph RAG.
"""

import pytest
from django.urls import reverse
from rest_framework import status

from tables.models.graph_models import Graph, KnowledgeNode
from tables.models.knowledge_models import (
    BaseRagType,
    GraphRag,
    NaiveRag,
    SourceCollection,
)
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

    def test_rag_id_without_collection_fails(self, auth_client, graph):
        # A concrete rag_id can only be validated against a source_collection.
        resp = auth_client.post(
            list_url(),
            {"graph": graph.id, "rag_type": "naive", "rag_id": 1},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "Required when a RAG is selected." in str(resp.json())

    def test_rag_id_without_type_fails(self, auth_client, graph, collection):
        resp = auth_client.post(
            list_url(),
            {
                "graph": graph.id,
                "source_collection": collection.collection_id,
                "rag_id": 1,
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "Required when rag_id is set." in str(resp.json())

    def test_rag_from_other_collection_fails(
        self, auth_client, graph, collection, other_collection_rag_type
    ):
        # rag_id exists, but in a different collection than the node's.
        impl = NaiveRag.objects.create(base_rag_type=other_collection_rag_type)
        data = {
            "graph": graph.id,
            "source_collection": collection.collection_id,
            "rag_type": "naive",
            "rag_id": impl.naive_rag_id,
        }
        resp = auth_client.post(list_url(), data, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "does not belong" in str(resp.json())

    def test_rag_type_only_remembers_kind(self, auth_client, graph):
        # rag_type without a concrete rag_id is allowed: it persists the last
        # selected kind so the flow reopens on the right naive/graph tab.
        resp = auth_client.post(
            list_url(),
            {"graph": graph.id, "rag_type": "naive"},
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.content
        node = KnowledgeNode.objects.get(id=resp.json()["id"])
        assert node.rag_type == "naive"
        assert node.rag_id is None

    def test_naive_selection_persists(
        self, auth_client, graph, collection, naive_rag_type
    ):
        impl = NaiveRag.objects.create(base_rag_type=naive_rag_type)
        data = {
            "graph": graph.id,
            "source_collection": collection.collection_id,
            "rag_type": "naive",
            "rag_id": impl.naive_rag_id,
            "search_configs": {"naive": {"search_limit": 3}},
        }
        resp = auth_client.post(list_url(), data, format="json")
        assert resp.status_code == status.HTTP_201_CREATED, resp.content
        body = resp.json()
        # Stored and echoed verbatim — no resolution.
        assert body["rag_type"] == "naive"
        assert body["rag_id"] == impl.naive_rag_id
        assert "search_method" not in body
        node = KnowledgeNode.objects.get(id=body["id"])
        assert node.rag_type == "naive"
        assert node.rag_id == impl.naive_rag_id

    def test_graph_selection_persists(
        self, auth_client, graph, collection, naive_rag_type
    ):
        # naive and graph impl ids may collide (separate AutoField sequences), but
        # rag_type disambiguates explicitly — no resolution guesswork needed.
        graph_rag_type = BaseRagType.objects.create(
            source_collection=collection, rag_type=BaseRagType.RagType.GRAPH
        )
        graph_impl = GraphRag.objects.create(base_rag_type=graph_rag_type)
        data = {
            "graph": graph.id,
            "source_collection": collection.collection_id,
            "rag_type": "graph",
            "rag_id": graph_impl.graph_rag_id,
            "search_configs": {"graph": {"search_method": "basic", "basic": {"k": 5}}},
        }
        resp = auth_client.post(list_url(), data, format="json")
        assert resp.status_code == status.HTTP_201_CREATED, resp.content
        body = resp.json()
        assert body["rag_type"] == "graph"
        assert body["rag_id"] == graph_impl.graph_rag_id
        node = KnowledgeNode.objects.get(id=body["id"])
        assert node.rag_type == "graph"
        assert node.rag_id == graph_impl.graph_rag_id
        # search_method survives nested, not at the top level.
        assert body["search_configs"]["graph"]["search_method"] == "basic"
        assert "search_method" not in body

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


@pytest.mark.django_db
class TestKnowledgeNodeRunValidation:
    """Run-time completeness gate (validate_runnable). Save stays permissive;
    an incompletely configured node must not be allowed to start a session."""

    @pytest.fixture
    def validator(self):
        from tables.validators.knowledge_node_validator import KnowledgeNodeValidator

        return KnowledgeNodeValidator()

    @pytest.fixture
    def runnable_node(self, graph, collection, naive_rag_type):
        impl = NaiveRag.objects.create(base_rag_type=naive_rag_type)
        return KnowledgeNode.objects.create(
            graph=graph,
            source_collection=collection,
            rag_type="naive",
            rag_id=impl.naive_rag_id,
            query="find me",
        )

    def _error(self):
        from tables.exceptions import KnowledgeNodeRunValidationError

        return KnowledgeNodeRunValidationError

    def test_fully_configured_passes(self, validator, runnable_node):
        validator.validate_runnable([runnable_node])  # no raise

    def test_missing_collection_blocks_even_with_query(self, validator, graph):
        node = KnowledgeNode.objects.create(
            graph=graph, rag_type="naive", rag_id=1, query="find me"
        )
        with pytest.raises(self._error()) as exc:
            validator.validate_runnable([node])
        assert "source_collection" in str(exc.value.detail)

    def test_incomplete_rag_blocks(self, validator, graph, collection):
        node = KnowledgeNode.objects.create(
            graph=graph, source_collection=collection, rag_type="naive", query="q"
        )  # rag_id missing
        with pytest.raises(self._error()) as exc:
            validator.validate_runnable([node])
        assert "rag_type/rag_id" in str(exc.value.detail)

    def test_empty_query_and_no_input_blocks(
        self, validator, graph, collection, naive_rag_type
    ):
        impl = NaiveRag.objects.create(base_rag_type=naive_rag_type)
        node = KnowledgeNode.objects.create(
            graph=graph,
            source_collection=collection,
            rag_type="naive",
            rag_id=impl.naive_rag_id,
            query="",
            input_map={},
        )
        with pytest.raises(self._error()) as exc:
            validator.validate_runnable([node])
        assert "query or input" in str(exc.value.detail)

    def test_empty_query_with_input_passes(
        self, validator, graph, collection, naive_rag_type
    ):
        impl = NaiveRag.objects.create(base_rag_type=naive_rag_type)
        node = KnowledgeNode.objects.create(
            graph=graph,
            source_collection=collection,
            rag_type="naive",
            rag_id=impl.naive_rag_id,
            query="",
            input_map={"text": "some_var"},
        )
        validator.validate_runnable([node])  # no raise

    def test_all_offending_nodes_reported_together(self, validator, graph):
        n1 = KnowledgeNode.objects.create(graph=graph, query="q")  # no collection/rag
        n2 = KnowledgeNode.objects.create(graph=graph)  # empty everything
        with pytest.raises(self._error()) as exc:
            validator.validate_runnable([n1, n2])
        reported = exc.value.detail["knowledge_nodes"]
        assert len(reported) == 2
