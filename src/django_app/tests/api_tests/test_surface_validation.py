import pytest

from agents.models import Surface
from tables.models.knowledge_models.collection_models import BaseRagType, SourceCollection
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

SURFACES_URL = "/api/surfaces/"
MAX_TOKENS = 2_000_000

# (config key, field, minimum, maximum, step used to step just outside the bounds)
SEARCH_CONFIG_BOUNDS = [
    ("naive_search_config", "search_limit", 1, 1000, 1),
    ("graph_basic_search_config", "k", 1, 100, 1),
    ("graph_basic_search_config", "max_context_tokens", 100, MAX_TOKENS, 1),
    ("graph_local_search_config", "text_unit_prop", 0.0, 1.0, 0.01),
    ("graph_local_search_config", "community_prop", 0.0, 1.0, 0.01),
    ("graph_local_search_config", "conversation_history_max_turns", 1, 50, 1),
    ("graph_local_search_config", "top_k_entities", 1, 100, 1),
    ("graph_local_search_config", "top_k_relationships", 1, 100, 1),
    ("graph_local_search_config", "max_context_tokens", 100, MAX_TOKENS, 1),
    ("graph_global_search_config", "max_context_tokens", 100, MAX_TOKENS, 1),
    ("graph_global_search_config", "data_max_tokens", 100, MAX_TOKENS, 1),
    ("graph_global_search_config", "map_max_length", 1, 10_000, 1),
    ("graph_global_search_config", "reduce_max_length", 1, 10_000, 1),
    ("graph_global_search_config", "dynamic_search_threshold", 0, 5, 1),
    ("graph_global_search_config", "dynamic_search_num_repeats", 1, 5, 1),
    ("graph_global_search_config", "dynamic_search_max_level", 0, 10, 1),
    ("graph_drift_search_config", "data_max_tokens", 100, MAX_TOKENS, 1),
    ("graph_drift_search_config", "reduce_max_tokens", 1, MAX_TOKENS, 1),
    ("graph_drift_search_config", "reduce_temperature", 0.0, 2.0, 0.01),
    ("graph_drift_search_config", "reduce_max_completion_tokens", 1, MAX_TOKENS, 1),
    ("graph_drift_search_config", "concurrency", 1, 256, 1),
    ("graph_drift_search_config", "drift_k_followups", 1, 100, 1),
    ("graph_drift_search_config", "primer_folds", 1, 100, 1),
    ("graph_drift_search_config", "primer_llm_max_tokens", 100, MAX_TOKENS, 1),
    ("graph_drift_search_config", "n_depth", 1, 10, 1),
    ("graph_drift_search_config", "community_level", 0, 10, 1),
    ("graph_drift_search_config", "local_search_text_unit_prop", 0.0, 1.0, 0.01),
    ("graph_drift_search_config", "local_search_community_prop", 0.0, 1.0, 0.01),
    ("graph_drift_search_config", "local_search_top_k_mapped_entities", 1, 100, 1),
    ("graph_drift_search_config", "local_search_top_k_relationships", 1, 100, 1),
    ("graph_drift_search_config", "local_search_max_data_tokens", 100, MAX_TOKENS, 1),
    ("graph_drift_search_config", "local_search_temperature", 0.0, 2.0, 0.01),
    ("graph_drift_search_config", "local_search_top_p", 0.0, 1.0, 0.01),
    ("graph_drift_search_config", "local_search_n", 1, 10, 1),
    ("graph_drift_search_config", "local_search_llm_max_gen_tokens", 1, MAX_TOKENS, 1),
    (
        "graph_drift_search_config",
        "local_search_llm_max_gen_completion_tokens",
        1,
        MAX_TOKENS,
        1,
    ),
]

# A proportion at its maximum only passes when its partner is zero (their sum must stay <= 1).
PROPORTION_PARTNERS = {
    "text_unit_prop": "community_prop",
    "community_prop": "text_unit_prop",
    "local_search_text_unit_prop": "local_search_community_prop",
    "local_search_community_prop": "local_search_text_unit_prop",
}

PROMPT_FIELDS = [
    ("graph_basic_search_config", "prompt"),
    ("graph_local_search_config", "prompt"),
    ("graph_global_search_config", "map_prompt"),
    ("graph_global_search_config", "reduce_prompt"),
    ("graph_global_search_config", "knowledge_prompt"),
    ("graph_drift_search_config", "prompt"),
    ("graph_drift_search_config", "reduce_prompt"),
]

NULLABLE_TOKEN_FIELDS = [
    "reduce_max_tokens",
    "reduce_max_completion_tokens",
    "local_search_llm_max_gen_tokens",
    "local_search_llm_max_gen_completion_tokens",
]


@pytest.fixture
def client(client_as, admin_acme, acme):
    api_client = client_as(admin_acme)
    api_client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return api_client


@pytest.fixture
def naive_collection(acme):
    collection = SourceCollection.objects.create(org=acme, collection_name="naive-kb")
    BaseRagType.objects.create(source_collection=collection, rag_type=BaseRagType.RagType.NAIVE)
    return collection


@pytest.fixture
def graph_collection(acme):
    collection = SourceCollection.objects.create(org=acme, collection_name="graph-kb")
    BaseRagType.objects.create(source_collection=collection, rag_type=BaseRagType.RagType.GRAPH)
    return collection


@pytest.fixture
def post_config(client, naive_collection, graph_collection):
    def _post(config_key, config):
        collection = naive_collection if config_key == "naive_search_config" else graph_collection
        return client.post(
            SURFACES_URL,
            {
                "name": "knowledge-surface",
                "knowledge": [{"collection": collection.pk, config_key: config}],
            },
            format="json",
        )

    return _post


def _config_with(field_name, value):
    config = {field_name: value}
    if field_name in PROPORTION_PARTNERS:
        config[PROPORTION_PARTNERS[field_name]] = 0.0
    return config


def _assert_invalid(response, *fragments):
    assert response.status_code == 400, response.data
    for fragment in fragments:
        assert fragment in response.data["message"]


@pytest.mark.django_db
class TestSurfaceKnowledgeBounds:
    @pytest.mark.parametrize("config_key,field_name,minimum,maximum,step", SEARCH_CONFIG_BOUNDS)
    def test_bounds_are_inclusive(
        self, post_config, config_key, field_name, minimum, maximum, step
    ):
        for value in (minimum, maximum):
            response = post_config(config_key, _config_with(field_name, value))

            assert response.status_code == 201, (value, response.data)
            stored_config = response.data["knowledge"][0][config_key]
            assert stored_config[field_name] == value
            Surface.objects.all().delete()

    @pytest.mark.parametrize("config_key,field_name,minimum,maximum,step", SEARCH_CONFIG_BOUNDS)
    def test_values_outside_bounds_are_rejected(
        self, post_config, config_key, field_name, minimum, maximum, step
    ):
        for value in (minimum - step, maximum + step):
            _assert_invalid(post_config(config_key, _config_with(field_name, value)), field_name)

        assert not Surface.objects.exists()

    @pytest.mark.parametrize("value,accepted", [("0.00", True), ("1.00", True), ("-0.01", False), ("1.01", False)])
    def test_similarity_threshold_bounds(self, post_config, value, accepted):
        response = post_config("naive_search_config", {"similarity_threshold": value})

        assert (response.status_code == 201) is accepted, response.data

    @pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
    @pytest.mark.parametrize(
        "config_key,field_name",
        [
            ("naive_search_config", "similarity_threshold"),
            ("graph_local_search_config", "text_unit_prop"),
            ("graph_drift_search_config", "reduce_temperature"),
            ("graph_drift_search_config", "local_search_top_p"),
        ],
    )
    def test_non_finite_values_are_rejected(self, post_config, config_key, field_name, value):
        _assert_invalid(post_config(config_key, _config_with(field_name, value)), field_name)

        assert not Surface.objects.exists()

    @pytest.mark.parametrize("field_name", NULLABLE_TOKEN_FIELDS)
    def test_nullable_drift_token_fields_accept_null(self, post_config, field_name):
        response = post_config("graph_drift_search_config", {field_name: None})

        assert response.status_code == 201, response.data
        assert response.data["knowledge"][0]["graph_drift_search_config"][field_name] is None


@pytest.mark.django_db
class TestSurfaceKnowledgeProportionSum:
    @pytest.mark.parametrize(
        "config_key,first_field,second_field",
        [
            ("graph_local_search_config", "text_unit_prop", "community_prop"),
            (
                "graph_drift_search_config",
                "local_search_text_unit_prop",
                "local_search_community_prop",
            ),
        ],
    )
    def test_sum_above_one_is_rejected(self, post_config, config_key, first_field, second_field):
        response = post_config(config_key, {first_field: 0.6, second_field: 0.5})

        _assert_invalid(response, first_field, second_field)

    @pytest.mark.parametrize(
        "config_key,first_field,second_field",
        [
            ("graph_local_search_config", "text_unit_prop", "community_prop"),
            (
                "graph_drift_search_config",
                "local_search_text_unit_prop",
                "local_search_community_prop",
            ),
        ],
    )
    @pytest.mark.parametrize("first_value,second_value", [(0.7, 0.3), (0.5, 0.5), (0.1, 0.2)])
    def test_sum_up_to_one_is_accepted(
        self, post_config, config_key, first_field, second_field, first_value, second_value
    ):
        response = post_config(config_key, {first_field: first_value, second_field: second_value})

        assert response.status_code == 201, response.data


@pytest.mark.django_db
class TestSurfaceKnowledgePrompts:
    @pytest.mark.parametrize("config_key,field_name", PROMPT_FIELDS)
    def test_prompt_of_10000_characters_or_null_is_accepted(
        self, post_config, config_key, field_name
    ):
        for value in ("p" * 10_000, None):
            response = post_config(config_key, {field_name: value})

            assert response.status_code == 201, response.data
            assert response.data["knowledge"][0][config_key][field_name] == value
            Surface.objects.all().delete()

    @pytest.mark.parametrize("config_key,field_name", PROMPT_FIELDS)
    def test_blank_or_oversized_prompt_is_rejected(self, post_config, config_key, field_name):
        for value in ("", "p" * 10_001):
            _assert_invalid(post_config(config_key, {field_name: value}), field_name)


@pytest.mark.django_db
class TestSurfaceHttpMethods:
    def test_put_is_not_allowed(self, client, acme):
        surface = Surface.objects.create(organization=acme, name="surface")

        response = client.put(f"{SURFACES_URL}{surface.id}/", {"name": "renamed"}, format="json")

        assert response.status_code == 405
        surface.refresh_from_db()
        assert surface.name == "surface"

    def test_patch_updates_surface(self, client, acme):
        surface = Surface.objects.create(organization=acme, name="surface")

        response = client.patch(f"{SURFACES_URL}{surface.id}/", {"name": "renamed"}, format="json")

        assert response.status_code == 200, response.data
        assert response.data["name"] == "renamed"

    def test_patch_out_of_range_knowledge_config_is_rejected(
        self, client, acme, graph_collection
    ):
        surface = Surface.objects.create(organization=acme, name="surface")

        response = client.patch(
            f"{SURFACES_URL}{surface.id}/",
            {
                "knowledge": [
                    {
                        "collection": graph_collection.pk,
                        "graph_basic_search_config": {"max_context_tokens": MAX_TOKENS + 1},
                    }
                ]
            },
            format="json",
        )

        _assert_invalid(response, "max_context_tokens")
        assert not surface.knowledge.exists()

    def test_patch_other_organization_surface_is_not_found(self, client, beta):
        foreign_surface = Surface.objects.create(organization=beta, name="foreign")

        response = client.patch(
            f"{SURFACES_URL}{foreign_surface.id}/", {"name": "hijacked"}, format="json"
        )

        assert response.status_code == 404
        foreign_surface.refresh_from_db()
        assert foreign_surface.name == "foreign"


@pytest.mark.django_db
class TestSurfaceKnowledgeProportionSumOnPatch:
    @pytest.mark.parametrize(
        "config_key,config",
        [
            ("graph_local_search_config", {"text_unit_prop": 0.9}),
            ("graph_drift_search_config", {"local_search_community_prop": 0.2}),
        ],
    )
    def test_omitted_partner_counts_with_its_default(
        self, client, acme, graph_collection, config_key, config
    ):
        surface = Surface.objects.create(organization=acme, name="surface")

        response = client.patch(
            f"{SURFACES_URL}{surface.id}/",
            {"knowledge": [{"collection": graph_collection.pk, config_key: config}]},
            format="json",
        )

        _assert_invalid(response, *config)
        assert not surface.knowledge.exists()

    def test_omitted_partner_within_sum_is_accepted(self, client, acme, graph_collection):
        surface = Surface.objects.create(organization=acme, name="surface")

        response = client.patch(
            f"{SURFACES_URL}{surface.id}/",
            {
                "knowledge": [
                    {
                        "collection": graph_collection.pk,
                        "graph_local_search_config": {"text_unit_prop": 0.85},
                    }
                ]
            },
            format="json",
        )

        assert response.status_code == 200, response.data
        stored_config = response.data["knowledge"][0]["graph_local_search_config"]
        assert stored_config["text_unit_prop"] == 0.85
        assert stored_config["community_prop"] == 0.15
