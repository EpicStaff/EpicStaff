"""Tests for EST-1429 adaptive context management.

Layered as:
  - Pure-function unit tests: formulas, clamp, builders, registry, Pydantic.
  - HTTP integration tests with monkeypatched services — they exercise the
    DRF view dispatch, exception → status mapping, and Pydantic request
    validation without spinning up SourceCollection / NaiveRag / GraphRag
    fixtures (those are covered by existing knowledge tests).
"""

import pytest
from django.urls import reverse
from pydantic import ValidationError
from rest_framework import status

from src.shared.models.adaptive_context import (
    CollectionMetrics,
    GraphRagSuggestRequest,
    NaiveRagSuggestRequest,
)
from tables.exceptions import (
    CollectionNotFoundException,
    GraphRagIndexNotReadyException,
    LLMConfigNotFoundException,
    NoGraphRagForCollectionException,
)
from tables.services.knowledge_services import adaptive_context_service as svc
from tables.utils.llm_context_windows import (
    FALLBACK_CONTEXT_WINDOW,
    resolve_context_window,
)
from tests.fixtures import *  # noqa: F401,F403


# ---------------------------------------------------------------------------
# Pure-function unit tests
# ---------------------------------------------------------------------------


class TestFormulas:
    # Only anchor points are tested for exact equality — midpoint values
    # are subject to FP rounding edge cases (banker's rounding, 0.175 ≠ 0.175
    # in float). For interpolation behaviour see test_lerp_buckets_monotonic.

    @pytest.mark.parametrize(
        "chunks,expected",
        [
            (0, 3),  # below first anchor
            (50, 3),  # at first anchor
            (500, 5),  # at second anchor
            (5000, 8),  # at third anchor
            (50000, 10),  # at last anchor
            (1_000_000, 10),  # clamped to last anchor
        ],
    )
    def test_naive_search_limit_anchors(self, chunks, expected):
        assert svc.calc_naive_search_limit(chunks) == expected

    @pytest.mark.parametrize(
        "chunks,expected",
        [
            (0, 0.15),
            (50, 0.15),
            (500, 0.20),
            (5000, 0.25),
            (50000, 0.30),
            (1_000_000, 0.30),
        ],
    )
    def test_naive_similarity_threshold_anchors(self, chunks, expected):
        assert svc.calc_naive_similarity_threshold(chunks) == expected

    @pytest.mark.parametrize(
        "chunks,expected",
        [
            (0, 5),
            (50, 5),
            (500, 10),
            (5000, 15),
            (50000, 20),
            (1_000_000, 20),
        ],
    )
    def test_top_k_anchors(self, chunks, expected):
        assert svc.calc_top_k(chunks) == expected

    @pytest.mark.parametrize(
        "size,expected",
        [
            (0, 0.40),
            (400, 0.40),
            (1200, 0.65),
            (5000, 0.65),
        ],
    )
    def test_text_unit_prop_anchors(self, size, expected):
        assert svc.calc_text_unit_prop(size) == expected

    @pytest.mark.parametrize(
        "docs,expected",
        [
            (0, 0.10),
            (5, 0.10),
            (50, 0.20),
            (500, 0.25),
            (5000, 0.30),
            (50000, 0.30),
        ],
    )
    def test_community_prop_anchors(self, docs, expected):
        assert svc.calc_community_prop(docs) == expected

    def test_lerp_buckets_monotonic(self):
        # Smoothed formulas must be monotonically non-decreasing.
        values = [0, 25, 50, 100, 200, 500, 1000, 5000, 50000, 1_000_000]
        for name, fn in [
            ("calc_top_k", svc.calc_top_k),
            ("calc_naive_search_limit", svc.calc_naive_search_limit),
            ("calc_naive_similarity_threshold", svc.calc_naive_similarity_threshold),
            ("calc_drift_concurrency", svc.calc_drift_concurrency),
        ]:
            out = [fn(v) for v in values]
            assert out == sorted(out), f"{name} not monotonic: {out}"

    @pytest.mark.parametrize(
        "chunks,expected",
        [
            (0, 3),  # short-circuit on empty
            (1, 3),  # sqrt(1)/3 = 0 → clamped up to 3
            (88, 3),  # sqrt(88)/3 ≈ 3.13 → 3
            (500, 7),  # sqrt(500)/3 ≈ 7.45 → 7
            (5000, 20),  # sqrt(5000)/3 ≈ 23.57 → clamped down to 20
            (10_000_000, 20),  # huge corpora cap at 20
        ],
    )
    def test_drift_k_followups(self, chunks, expected):
        assert svc.calc_drift_k_followups(chunks) == expected

    @pytest.mark.parametrize(
        "budget,expected",
        [
            (0, 2),  # degenerate ctx → floor 2
            (5_000, 2),  # 16k ctx fallback: 12800/5000=2, max(2,2)=2
            (15_000, 3),  # 50k×0.3 hypothetical
            (25_000, 5),  # gpt-4o-mini = 102k×0.8/4... clamps at 5
            (102_400, 5),  # ceiling
            (1_600_000, 5),  # huge ctx still clamps at 5 (recall ceiling)
        ],
    )
    def test_conversation_history_max_turns_branches(self, budget, expected):
        assert svc.calc_conversation_history_max_turns(budget) == expected

    @pytest.mark.parametrize(
        "docs,expected",
        [
            (0, 3),
            (5, 3),
            (50, 5),
            (500, 7),
            (5000, 7),
        ],
    )
    def test_primer_folds_anchors(self, docs, expected):
        assert svc.calc_drift_primer_folds(docs) == expected

    @pytest.mark.parametrize(
        "docs,expected",
        [
            (0, 4),
            (5, 4),
            (50, 3),
            (500, 2),
            (5000, 2),
        ],
    )
    def test_n_depth_anchors(self, docs, expected):
        assert svc.calc_drift_n_depth(docs) == expected

    @pytest.mark.parametrize(
        "docs,expected",
        [
            (0, 1),  # tiny corpus → flat community structure → depth 1
            (5, 1),
            (50, 2),
            (500, 3),
            (5000, 4),
            (50000, 4),
        ],
    )
    def test_dynamic_search_max_level_anchors(self, docs, expected):
        assert svc.calc_community_level(docs) == expected

    @pytest.mark.parametrize(
        "chunks,expected",
        [
            (0, 16),
            (500, 16),
            (5000, 32),
            (50000, 64),
            (1_000_000, 64),
        ],
    )
    def test_concurrency_anchors(self, chunks, expected):
        assert svc.calc_drift_concurrency(chunks) == expected


class TestClamp:
    def test_safe_budget_trusted_no_ceiling(self):
        # litellm-known model: 200_000 × 0.8 = 160_000 (no ceiling)
        assert svc.safe_budget(200_000, is_trusted=True) == 160_000

    def test_safe_budget_trusted_huge_ctx(self):
        # Gemini 1.5 Pro: 2_000_000 × 0.8 = 1_600_000 (passes through)
        assert svc.safe_budget(2_000_000, is_trusted=True) == 1_600_000

    def test_safe_budget_untrusted_caps_at_max_token_field(self):
        # 3_000_000 × 0.8 = 2_400_000 > MAX_TOKEN_FIELD_VALUE → 2_000_000
        assert svc.safe_budget(3_000_000, is_trusted=False) == 2_000_000

    def test_safe_budget_untrusted_small_ctx_no_cap(self):
        # 16_000 × 0.8 = 12_800 < 2_000_000 → 12_800
        assert svc.safe_budget(16_000, is_trusted=False) == 12_800

    def test_clamp_none_passthrough(self):
        out, clamped = svc.clamp_token_fields({"a": None}, 12_800, is_trusted=True)
        assert out == {"a": None}
        assert clamped == []

    def test_clamp_value_under_budget(self):
        out, clamped = svc.clamp_token_fields({"a": 1000}, 12_800, is_trusted=True)
        assert out == {"a": 1000}
        assert clamped == []

    def test_clamp_value_over_budget(self):
        out, clamped = svc.clamp_token_fields({"a": 50_000}, 12_800, is_trusted=True)
        assert out == {"a": 12_800}
        assert clamped == ["a"]

    def test_default_data_tokens_picks_larger_of_ctx_and_corpus(self):
        # Tiny corpus (5k tokens) vs large budget (100k):
        # by_ctx = 100k × 0.3 = 30k, by_corpus = 5k × 0.3 = 1.5k → 30k
        tiny = CollectionMetrics(
            total_documents=2, total_chunks=10, avg_chunk_size=500.0
        )
        assert svc.default_data_tokens(tiny, 100_000, 0.3, 0.3) == 30_000

    def test_default_data_tokens_corpus_share_wins_on_huge_corpus(self):
        # Huge corpus (10M tokens), small budget (100k):
        # by_ctx = 100k × 0.3 = 30k, by_corpus = 10M × 0.3 = 3M → capped to 100k
        huge = CollectionMetrics(
            total_documents=5000, total_chunks=10_000, avg_chunk_size=1000.0
        )
        assert svc.default_data_tokens(huge, 100_000, 0.3, 0.3) == 100_000

    def test_default_data_tokens_floor_on_empty_corpus(self):
        empty = CollectionMetrics(total_documents=0, total_chunks=0, avg_chunk_size=0.0)
        # by_ctx = 1k × 0.01 = 10, by_corpus = 0 → floor 1000
        assert svc.default_data_tokens(empty, 1_000, 0.01, 0.0) == 1_000

    def test_clamp_untrusted_passes_through(self):
        # Untrusted ctx: user overrides are not clamped, even huge ones.
        out, clamped = svc.clamp_token_fields(
            {"a": 200_000, "b": None, "c": 10}, 12_800, is_trusted=False
        )
        assert out == {"a": 200_000, "b": None, "c": 10}
        assert clamped == []


class TestBuilders:
    metrics = CollectionMetrics(
        total_documents=12, total_chunks=480, avg_chunk_size=650
    )

    def test_naive_default(self):
        # For 480 chunks (near second anchor at 500):
        # search_limit lerps to round(3 + 2*430/450) = round(4.91) = 5
        # similarity_threshold lerps to round(0.15 + 0.05*430/450, 3) = 0.198
        params, clamped = svc.build_naive_params(self.metrics, None)
        assert params.search_limit == 5
        assert params.similarity_threshold == pytest.approx(0.198, abs=0.005)
        assert clamped == []

    def test_naive_user_override_wins(self):
        params, _ = svc.build_naive_params(self.metrics, {"search_limit": 42})
        assert params.search_limit == 42

    def test_drift_props_leave_room_for_local_slice(self):
        # Worker derives local_prop = 1 - text_unit - community for the
        # entity/relationship/covariate slice; sum must stay <= 1.0 so that
        # slice is non-negative.
        params, _ = svc.build_graph_drift_params(self.metrics, 128_000, True, None)
        total = params.local_search_text_unit_prop + params.local_search_community_prop
        assert total <= 1.0 + 1e-9

    def test_drift_user_override_kept_when_safe(self):
        params, _ = svc.build_graph_drift_params(
            self.metrics,
            128_000,
            True,
            {"local_search_text_unit_prop": 0.7},
        )
        assert params.local_search_text_unit_prop == 0.7
        total = params.local_search_text_unit_prop + params.local_search_community_prop
        assert total <= 1.0 + 1e-9

    def test_drift_user_override_normalized_when_sum_exceeds_one(self):
        # text_unit=0.8 + formula community for 12 docs (0.20) = 1.0 — safe.
        # If user pushes text_unit higher AND community higher, sum > 1.0
        # must be normalized proportionally.
        params, _ = svc.build_graph_drift_params(
            self.metrics,
            128_000,
            True,
            {
                "local_search_text_unit_prop": 0.8,
                "local_search_community_prop": 0.6,
            },
        )
        total = params.local_search_text_unit_prop + params.local_search_community_prop
        assert abs(total - 1.0) < 1e-9

    def test_drift_category_one_fields_keep_pydantic_defaults(self):
        # reduce_temperature / *_temperature / top_p / local_search_n have no
        # formula — must inherit Pydantic defaults.
        params, _ = svc.build_graph_drift_params(self.metrics, 128_000, True, None)
        assert params.reduce_temperature == 0.0
        assert params.local_search_temperature == 0.0
        assert params.local_search_top_p == 1.0
        assert params.local_search_n == 1

    def test_drift_token_field_clamp_under_known_llm(self):
        params, clamped = svc.build_graph_drift_params(
            self.metrics, 16_000, True, {"data_max_tokens": 200_000}
        )
        assert params.data_max_tokens == 12_800
        assert "data_max_tokens" in clamped

    def test_drift_token_field_unclamped_when_untrusted(self):
        params, clamped = svc.build_graph_drift_params(
            self.metrics, 16_000, False, {"data_max_tokens": 200_000}
        )
        assert params.data_max_tokens == 200_000
        assert clamped == []

    def test_empty_collection_produces_valid_model(self):
        empty = CollectionMetrics(total_documents=0, total_chunks=0, avg_chunk_size=0.0)
        params, _ = svc.build_graph_drift_params(empty, 16_000, True, None)
        assert params.drift_k_followups == 3  # short-circuit on 0 chunks
        assert params.n_depth == 4  # ≤5 docs

    def test_huge_collection_does_not_crash(self):
        huge = CollectionMetrics(
            total_documents=100_000, total_chunks=10_000_000, avg_chunk_size=1500.0
        )
        params, _ = svc.build_graph_drift_params(huge, 16_000, True, None)
        # √N/3 grows without bound — formula clamps at 20
        assert 3 <= params.drift_k_followups <= 20

    def test_none_in_user_override_treated_as_not_supplied(self):
        params, _ = svc.build_naive_params(self.metrics, {"search_limit": None})
        # None → fall through to formula default
        assert params.search_limit == 5


class TestRegistry:
    def test_registry_has_four_methods(self):
        names = [s.method_name for s in svc.GRAPH_SEARCH_METHOD_REGISTRY]
        assert names == ["basic", "local", "global_search", "drift_search"]

    def test_get_graph_strategy_lookup(self):
        s = svc.get_graph_strategy("drift_search")
        assert s.method_name == "drift_search"
        assert s.builder is svc.build_graph_drift_params

    def test_get_graph_strategy_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown graph search method"):
            svc.get_graph_strategy("nope")

    def test_method_list_single_source_of_truth(self):
        """All four method-list sources must agree with the canonical
        GraphSearchMethod Literal (guards 2.2 — single source of truth)."""
        from typing import get_args

        from src.shared.models.adaptive_context import GraphSearchMethod
        from tables.models.knowledge_models.graphrag_models import AgentGraphRag
        from tables.serializers.adaptive_context_serializers import (
            GRAPH_SEARCH_METHODS,
        )

        canonical = set(get_args(GraphSearchMethod))
        assert set(GRAPH_SEARCH_METHODS) == canonical
        assert {s.method_name for s in svc.GRAPH_SEARCH_METHOD_REGISTRY} == canonical
        assert {v for v, _ in AgentGraphRag.SearchMethod.choices} == canonical


# ---------------------------------------------------------------------------
# Context window resolver
# ---------------------------------------------------------------------------


class TestResolveContextWindow:
    def test_known_model_is_trusted(self):
        ctx, warning, is_trusted = resolve_context_window("gpt-4o")
        assert ctx > 0
        assert warning is None
        assert is_trusted is True

    def test_unknown_model_no_override_falls_back_untrusted(self):
        ctx, warning, is_trusted = resolve_context_window("my-totally-custom-model-xyz")
        assert ctx == FALLBACK_CONTEXT_WINDOW
        assert warning is not None
        assert "my-totally-custom-model-xyz" in warning
        assert is_trusted is False

    def test_unknown_model_with_valid_override_uses_override_untrusted(self):
        ctx, warning, is_trusted = resolve_context_window(
            "my-custom-model", user_override=64_000
        )
        assert ctx == 64_000
        assert warning is None
        assert is_trusted is False

    def test_unknown_model_with_too_small_override_falls_back(self):
        ctx, warning, is_trusted = resolve_context_window(
            "my-custom-model", user_override=500
        )
        assert ctx == FALLBACK_CONTEXT_WINDOW
        assert warning is not None
        assert is_trusted is False

    def test_unknown_model_with_garbage_override_falls_back(self):
        ctx, warning, is_trusted = resolve_context_window(
            "my-custom-model",
            user_override="not-an-int",  # type: ignore[arg-type]
        )
        assert ctx == FALLBACK_CONTEXT_WINDOW
        assert warning is not None
        assert is_trusted is False

    def test_litellm_exception_caught(self, monkeypatch):
        import tables.utils.llm_context_windows as mod

        def boom(name):
            raise RuntimeError("simulated litellm crash")

        monkeypatch.setattr(mod.litellm, "get_model_info", boom)
        ctx, warning, is_trusted = resolve_context_window("anything")
        assert ctx == FALLBACK_CONTEXT_WINDOW
        assert warning is not None
        assert is_trusted is False


# ---------------------------------------------------------------------------
# Pydantic request validation
# ---------------------------------------------------------------------------


class TestRequestSchemas:
    def test_naive_request_requires_llm_config_id(self):
        with pytest.raises(ValidationError) as exc:
            NaiveRagSuggestRequest(knowledge_collection_id=1)
        assert any(e["loc"] == ("llm_config_id",) for e in exc.value.errors())

    def test_naive_request_rejects_extra_field(self):
        with pytest.raises(ValidationError) as exc:
            NaiveRagSuggestRequest(
                knowledge_collection_id=1, llm_config_id=1, bogus=True
            )
        assert any(e["type"] == "extra_forbidden" for e in exc.value.errors())

    def test_collection_id_must_be_positive(self):
        with pytest.raises(ValidationError):
            NaiveRagSuggestRequest(knowledge_collection_id=0, llm_config_id=1)

    def test_graph_request_invalid_search_method_rejected(self):
        with pytest.raises(ValidationError):
            GraphRagSuggestRequest(
                knowledge_collection_id=1,
                search_method="invalid",
                llm_config_id=1,
            )


# ---------------------------------------------------------------------------
# HTTP integration with mocked services
# ---------------------------------------------------------------------------


@pytest.fixture
def patched_services(monkeypatch):
    """Replace the service-layer dependencies with controllable doubles.

    Returns a state dict the test can mutate to simulate different ctx,
    metrics, warnings and exceptions.
    """
    state = {
        "ctx": 128_000,
        "llm_name": "gpt-4o",
        "warning": None,
        "is_trusted": True,
        "metrics": CollectionMetrics(
            total_documents=12, total_chunks=480, avg_chunk_size=650.0
        ),
        "metrics_exc": None,
    }

    def fake_resolve(llm_config_id):
        if isinstance(state["ctx"], Exception):
            raise state["ctx"]
        return state["ctx"], state["llm_name"], state["warning"], state["is_trusted"]

    def fake_metrics(collection_id, rag_type):
        if state["metrics_exc"] is not None:
            raise state["metrics_exc"]
        return state["metrics"]

    import tables.views.knowledge_views.adaptive_context_views as views

    monkeypatch.setattr(views, "_resolve_llm_ctx", fake_resolve)
    monkeypatch.setattr(
        views.CollectionManagementService,
        "get_collection_metrics",
        staticmethod(fake_metrics),
    )
    return state


@pytest.mark.django_db
class TestNaiveSuggestEndpoint:
    url = "/api/naive-rag/suggest-search-params/"

    def test_unauthenticated_request_blocked(self, api_client):
        response = api_client.post(
            self.url, {"knowledge_collection_id": 1, "llm_config_id": 1}, format="json"
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_happy_path(self, auth_client, patched_services):
        response = auth_client.post(
            self.url,
            {"knowledge_collection_id": 42, "llm_config_id": 17},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.content
        body = response.json()
        assert body["resolved_llm_name"] == "gpt-4o"
        assert body["llm_resolution_warning"] is None
        assert body["effective_llm_context_window"] == 128_000
        # trusted ctx (litellm-known) → no MAX_TOKEN_FIELD_VALUE cap → 128k×0.8
        assert body["safe_token_budget"] == 102_400
        assert body["suggested_params"]["rag_type"] == "naive"
        assert body["suggested_params"]["search_limit"] == 5
        assert body["clamped_fields"] == []

    def test_missing_llm_config_id_returns_400(self, auth_client, patched_services):
        response = auth_client.post(
            self.url, {"knowledge_collection_id": 1}, format="json"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["error"] == "Validation error"

    def test_extra_field_returns_400(self, auth_client, patched_services):
        response = auth_client.post(
            self.url,
            {"knowledge_collection_id": 1, "llm_config_id": 1, "bogus": True},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_collection_not_found_returns_404(self, auth_client, patched_services):
        patched_services["metrics_exc"] = CollectionNotFoundException(999)
        response = auth_client.post(
            self.url,
            {"knowledge_collection_id": 999, "llm_config_id": 17},
            format="json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_llm_not_found_returns_404(self, auth_client, patched_services):
        patched_services["ctx"] = LLMConfigNotFoundException(123)
        response = auth_client.post(
            self.url,
            {"knowledge_collection_id": 1, "llm_config_id": 123},
            format="json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestGraphSuggestEndpoint:
    url = "/api/graph-rag/suggest-search-params/"

    def _payload(self, **kwargs):
        base = {
            "knowledge_collection_id": 42,
            "search_method": "drift_search",
            "llm_config_id": 17,
        }
        base.update(kwargs)
        return base

    def test_happy_path_drift(self, auth_client, patched_services):
        response = auth_client.post(self.url, self._payload(), format="json")
        assert response.status_code == status.HTTP_200_OK, response.content
        body = response.json()
        assert body["suggested_params"]["search_method"] == "drift_search"
        assert body["resolved_llm_name"] == "gpt-4o"
        # text_unit + community <= 1.0 (leaving room for local slice)
        sp = body["suggested_params"]
        total = sp["local_search_text_unit_prop"] + sp["local_search_community_prop"]
        assert total <= 1.0 + 1e-9

    def test_unknown_search_method_returns_400(self, auth_client, patched_services):
        # Pydantic-level: Literal["basic","local","global_search","drift_search"]
        # rejects unknown methods before reaching the registry.
        response = auth_client.post(
            self.url, self._payload(search_method="weird"), format="json"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_no_graph_rag_returns_404(self, auth_client, patched_services):
        patched_services["metrics_exc"] = NoGraphRagForCollectionException(42)
        response = auth_client.post(self.url, self._payload(), format="json")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_graph_index_not_ready_returns_409(self, auth_client, patched_services):
        patched_services["metrics_exc"] = GraphRagIndexNotReadyException(42)
        response = auth_client.post(self.url, self._payload(), format="json")
        assert response.status_code == status.HTTP_409_CONFLICT

    def test_untrusted_mode_passes_overrides_unchanged(
        self, auth_client, patched_services
    ):
        # litellm did not recognise the model and we are using the fallback /
        # user-override path — the backend must NOT clamp user token overrides.
        patched_services["ctx"] = 16_000
        patched_services["llm_name"] = "my-custom"
        patched_services["warning"] = (
            "Unknown model 'my-custom', falling back to 16000."
        )
        patched_services["is_trusted"] = False
        response = auth_client.post(
            self.url,
            self._payload(user_custom_params={"data_max_tokens": 80_000}),
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["llm_resolution_warning"] is not None
        assert body["suggested_params"]["data_max_tokens"] == 80_000
        assert body["clamped_fields"] == []

    def test_token_override_clamped_under_known_llm(
        self, auth_client, patched_services
    ):
        patched_services["ctx"] = 16_000  # safe_budget = 12_800
        patched_services["is_trusted"] = True
        response = auth_client.post(
            self.url,
            self._payload(user_custom_params={"data_max_tokens": 80_000}),
            format="json",
        )
        body = response.json()
        assert body["suggested_params"]["data_max_tokens"] == 12_800
        assert "data_max_tokens" in body["clamped_fields"]

    def test_url_reverse_is_registered(self):
        # Sanity check that the route name is wired
        assert reverse("naive-rag-suggest-search-params").endswith(
            "/naive-rag/suggest-search-params/"
        )
        assert reverse("graph-rag-suggest-search-params").endswith(
            "/graph-rag/suggest-search-params/"
        )
