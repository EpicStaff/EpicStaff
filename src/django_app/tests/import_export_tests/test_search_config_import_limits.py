"""An import holds knowledge search configs to the limits the API holds them to.

Knowledge nodes, shared surfaces and the inline surfaces of task nodes carry the same
five search configs. A value the API would refuse refuses the whole import; a valid
file imports with its values as given, and a setting the file leaves out gets the
model default.
"""

import io
import json
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

import pytest
from agents.models import (
    AgentDefinition,
    InlineSurface,
    InlineSurfaceKnowledge,
    Surface,
    SurfaceKnowledge,
)
from rest_framework.exceptions import ValidationError
from tables.import_export.enums import EntityType, NodeType
from tables.import_export.registry import entity_registry
from tables.import_export.services.export_service import ExportService
from tables.import_export.services.import_service import ImportService
from tables.models import Graph, KnowledgeNode, TaskNode
from tables.models.knowledge_models import (
    KNOWLEDGE_NODE_SEARCH_CONFIG_MODELS,
    SourceCollection,
)
from tables.import_export.utils import flatten_error_detail

from tests.helpers import UNRESTRICTED_EXPORT_POLICY
from tests.rbac_cross_org_fixtures import *  # noqa: F403

# Every setting at a non-default value the API accepts, several on a limit.
VALID_VALUES = {
    "naive_search_config": {
        "search_limit": 1000,
        "similarity_threshold": Decimal("1.00"),
        "is_suggested": True,
    },
    "graph_basic_search_config": {
        "prompt": "basic prompt",
        "k": 100,
        "max_context_tokens": 2_000_000,
        "is_suggested": True,
    },
    "graph_local_search_config": {
        "prompt": "local prompt",
        "text_unit_prop": 0.6,
        "community_prop": 0.4,
        "conversation_history_max_turns": 50,
        "top_k_entities": 1,
        "top_k_relationships": 100,
        "max_context_tokens": 100,
        "is_suggested": True,
    },
    "graph_global_search_config": {
        "map_prompt": "map prompt",
        "reduce_prompt": "reduce prompt",
        "knowledge_prompt": "knowledge prompt",
        "max_context_tokens": 5000,
        "data_max_tokens": 6000,
        "map_max_length": 10_000,
        "reduce_max_length": 1,
        "dynamic_community_selection": True,
        "dynamic_search_threshold": 5,
        "dynamic_search_keep_parent": True,
        "dynamic_search_num_repeats": 5,
        "dynamic_search_use_summary": True,
        "dynamic_search_max_level": 10,
        "is_suggested": True,
    },
    "graph_drift_search_config": {
        "prompt": "primer prompt",
        "reduce_prompt": "reduce prompt",
        "data_max_tokens": 3000,
        "reduce_max_tokens": 1,
        "reduce_temperature": 2.0,
        "reduce_max_completion_tokens": 2_000_000,
        "concurrency": 256,
        "drift_k_followups": 100,
        "primer_folds": 1,
        "primer_llm_max_tokens": 4000,
        "n_depth": 10,
        "community_level": 0,
        "local_search_text_unit_prop": 0.6,
        "local_search_community_prop": 0.4,
        "local_search_top_k_mapped_entities": 7,
        "local_search_top_k_relationships": 8,
        "local_search_max_data_tokens": 9000,
        "local_search_temperature": 0.5,
        "local_search_top_p": 0.0,
        "local_search_n": 10,
        "local_search_llm_max_gen_tokens": 500,
        "local_search_llm_max_gen_completion_tokens": 600,
        "is_suggested": True,
    },
}

# One value past a limit per config type, and the proportions summing past 1.
REFUSED_VALUES = [
    pytest.param("naive_search_config", "search_limit", 1001, id="naive limit"),
    pytest.param("naive_search_config", "similarity_threshold", "1.01", id="naive threshold"),
    pytest.param("graph_basic_search_config", "k", 101, id="basic k"),
    pytest.param("graph_basic_search_config", "k", 0, id="basic k below min"),
    pytest.param("graph_basic_search_config", "max_context_tokens", 2_000_001, id="basic tokens"),
    pytest.param("graph_local_search_config", "top_k_entities", 1_000_000, id="local top k"),
    pytest.param("graph_local_search_config", "max_context_tokens", 100_000_000, id="local tokens"),
    pytest.param("graph_local_search_config", "text_unit_prop", 50, id="local proportion"),
    pytest.param("graph_local_search_config", "text_unit_prop", 0.7, id="local proportions sum"),
    pytest.param(
        "graph_local_search_config",
        "conversation_history_max_turns",
        51,
        id="local turns",
    ),
    pytest.param("graph_global_search_config", "map_max_length", 10_001, id="global length"),
    pytest.param(
        "graph_global_search_config", "dynamic_search_threshold", 6, id="global threshold"
    ),
    pytest.param("graph_drift_search_config", "concurrency", 257, id="drift concurrency"),
    pytest.param("graph_drift_search_config", "local_search_top_p", 1.5, id="drift top p"),
]

# Keys an export never carries in a config, and the import must not take from a file:
# the row's own id, a link to another owner, and the soft-delete state.
FOREIGN_KEYS = {
    "id": 999_999,
    "knowledge_node": 999_999,
    "surface_knowledge": 999_999,
    "active": False,
    "not_a_field": 1,
}


@pytest.fixture
def collection(default_org):
    return SourceCollection.objects.create(
        collection_name="Handbook", description="HR docs", org=default_org
    )


@pytest.fixture
def graph(default_org):
    return Graph.objects.create(
        name="knowledge flow", metadata={"nodes": [], "edges": []}, org=default_org
    )


def _create_configs(config_model_of, owner_kwargs: dict) -> None:
    for block, values in VALID_VALUES.items():
        config_model_of(block).objects.create(**owner_kwargs, **values)


def _config_model_of(knowledge_model):
    return lambda block: knowledge_model._meta.get_field(block).related_model


def _graph_node_entry(export_data: dict, node_type: str) -> dict:
    [entry] = [
        node for node in export_data[EntityType.GRAPH][0]["nodes"] if node["node_type"] == node_type
    ]
    return entry


@dataclass(frozen=True)
class Owner:
    """Something carrying search configs, and where they sit in its export and after import."""

    entity_type: str
    create: Callable  # (graph, collection) -> exported entity id
    configs_in_file: Callable  # export data -> the dict holding the config blocks
    imported_owner: Callable  # (id mapper, exported entity id) -> holder of the config rows


def _create_knowledge_node(graph, collection) -> int:
    node = KnowledgeNode.objects.create(graph=graph, node_name="Lookup")
    _create_configs(KNOWLEDGE_NODE_SEARCH_CONFIG_MODELS.get, {"knowledge_node": node})
    return graph.id


def _imported_knowledge_node(id_mapper, graph_id) -> KnowledgeNode:
    return KnowledgeNode.objects.get(graph_id=id_mapper.get(EntityType.GRAPH, graph_id))


def _create_surface(graph, collection) -> int:
    surface = Surface.objects.create(org=graph.org, name="research", instructions="look up")
    row = SurfaceKnowledge.objects.create(surface=surface, collection=collection)
    _create_configs(_config_model_of(SurfaceKnowledge), {"surface_knowledge": row})
    return surface.id


def _imported_surface_knowledge(id_mapper, surface_id) -> SurfaceKnowledge:
    return SurfaceKnowledge.objects.get(surface_id=id_mapper.get(EntityType.SURFACE, surface_id))


def _create_task_inline_surface(graph, collection) -> int:
    agent = AgentDefinition.objects.create(org=graph.org, name="node agent")
    task_node = TaskNode.objects.create(graph=graph, agent_definition=agent, instructions="t")
    inline = InlineSurface.objects.create(task_node=task_node, instructions="b")
    row = InlineSurfaceKnowledge.objects.create(inline_surface=inline, collection=collection)
    _create_configs(_config_model_of(InlineSurfaceKnowledge), {"surface_knowledge": row})
    return graph.id


def _task_inline_knowledge_entry(export_data: dict) -> dict:
    task_entry = _graph_node_entry(export_data, NodeType.TASK_NODE)
    return task_entry["inline_surface"]["knowledge"][0]


def _imported_task_inline_knowledge(id_mapper, graph_id) -> InlineSurfaceKnowledge:
    task_node = TaskNode.objects.get(graph_id=id_mapper.get(EntityType.GRAPH, graph_id))
    return task_node.inline_surface.knowledge.get()


OWNERS = [
    pytest.param(
        Owner(
            EntityType.GRAPH,
            _create_knowledge_node,
            lambda data: _graph_node_entry(data, NodeType.KNOWLEDGE_NODE),
            _imported_knowledge_node,
        ),
        id="knowledge node",
    ),
    pytest.param(
        Owner(
            EntityType.SURFACE,
            _create_surface,
            lambda data: data[EntityType.SURFACE][0]["knowledge"][0],
            _imported_surface_knowledge,
        ),
        id="shared surface",
    ),
    pytest.param(
        Owner(
            EntityType.GRAPH,
            _create_task_inline_surface,
            _task_inline_knowledge_entry,
            _imported_task_inline_knowledge,
        ),
        id="task node inline surface",
    ),
]


def _export(entity_type, entity_id) -> dict:
    data = (
        ExportService(entity_registry)
        .export_entities(entity_type, [entity_id], policy=UNRESTRICTED_EXPORT_POLICY)
        .data
    )
    return json.loads(json.dumps(data))


def _import(export_data, entity_type, org):
    id_mapper, _ = ImportService(entity_registry).import_data(
        export_data, main_entity=entity_type, org_id=org.id
    )
    return id_mapper


def _stored_values(owner_row, block: str) -> dict:
    config = getattr(owner_row, block)
    return {field: getattr(config, field) for field in VALID_VALUES[block]}


def test_the_valid_values_cover_every_knowledge_node_search_config():
    assert set(VALID_VALUES) == set(KNOWLEDGE_NODE_SEARCH_CONFIG_MODELS)


@pytest.mark.django_db
@pytest.mark.parametrize("owner", OWNERS)
def test_a_valid_file_imports_its_search_configs_as_given(owner, graph, collection, default_org):
    entity_id = owner.create(graph, collection)
    export_data = _export(owner.entity_type, entity_id)
    for block in VALID_VALUES:
        owner.configs_in_file(export_data)[block].update(FOREIGN_KEYS)

    id_mapper = _import(export_data, owner.entity_type, default_org)

    imported = owner.imported_owner(id_mapper, entity_id)
    for block, expected in VALID_VALUES.items():
        assert _stored_values(imported, block) == expected, block


@pytest.mark.django_db
@pytest.mark.parametrize("owner", OWNERS)
@pytest.mark.parametrize(("block", "field", "value"), REFUSED_VALUES)
def test_a_value_past_the_api_limit_refuses_the_import(
    owner, block, field, value, graph, collection, default_org
):
    entity_id = owner.create(graph, collection)
    export_data = _export(owner.entity_type, entity_id)
    owner.configs_in_file(export_data)[block][field] = value
    graphs_before, surfaces_before = Graph.objects.count(), Surface.objects.count()

    with pytest.raises(ValidationError) as refused:
        _import(export_data, owner.entity_type, default_org)

    message = flatten_error_detail(refused.value.detail)
    assert block in message
    assert field in message
    assert (Graph.objects.count(), Surface.objects.count()) == (graphs_before, surfaces_before)


@pytest.mark.django_db
@pytest.mark.parametrize("owner", OWNERS)
def test_a_setting_the_file_leaves_out_gets_the_model_default(
    owner, graph, collection, default_org
):
    entity_id = owner.create(graph, collection)
    export_data = _export(owner.entity_type, entity_id)
    owner.configs_in_file(export_data)["graph_basic_search_config"] = {"k": 42}

    id_mapper = _import(export_data, owner.entity_type, default_org)

    imported = owner.imported_owner(id_mapper, entity_id)
    assert _stored_values(imported, "graph_basic_search_config") == {
        "prompt": None,
        "k": 42,
        "max_context_tokens": 12000,
        "is_suggested": False,
    }


@pytest.mark.django_db
@pytest.mark.parametrize("owner", OWNERS)
def test_a_proportion_summing_past_one_with_the_default_refuses_the_import(
    owner, graph, collection, default_org
):
    # The file leaves community_prop out; its default 0.15 plus 0.9 is past 1.
    entity_id = owner.create(graph, collection)
    export_data = _export(owner.entity_type, entity_id)
    owner.configs_in_file(export_data)["graph_local_search_config"] = {"text_unit_prop": 0.9}

    with pytest.raises(ValidationError) as refused:
        _import(export_data, owner.entity_type, default_org)

    message = flatten_error_detail(refused.value.detail)
    assert "graph_local_search_config" in message
    assert "text_unit_prop + community_prop must not exceed 1" in message


# --- through the endpoint ----------------------------------------------------------------


@pytest.mark.django_db
def test_the_flow_import_endpoint_answers_400_naming_the_node_and_field(
    client_as, admin_acme, acme
):
    flow = Graph.objects.create(name="Shared flow", metadata={"nodes": [], "edges": []}, org=acme)
    KnowledgeNode.objects.create(graph=flow, node_name="Lookup")
    export_data = _export(EntityType.GRAPH, flow.id)
    _graph_node_entry(export_data, NodeType.KNOWLEDGE_NODE)["graph_local_search_config"] = {
        "top_k_entities": 1_000_000,
        "max_context_tokens": 100_000_000,
        "text_unit_prop": 50,
    }
    upload = io.BytesIO(json.dumps(export_data).encode())
    upload.name = "flow.json"
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

    response = client.post("/api/graphs/import/", {"file": upload}, format="multipart")

    assert response.status_code == 400, response.content
    attrs = [error["attr"] for error in response.json()["errors"]]
    assert all(attr.startswith('Knowledge node "Lookup".graph_local_search_config.') for attr in attrs)
    assert any(attr.endswith(".top_k_entities") for attr in attrs)
    assert Graph.objects.filter(org=acme).count() == 1
