"""Tests for storage demand collector.

The collector performs a recursive traversal of a session graph, identifying
all nodes with StorageScopedData.use_storage=True and aggregating their scope
information (storage_allowed_paths, storage_org_prefix).
"""

import typing

import pytest

from src.shared.models.graph_nodes import (
    AgentNodeData,
    AudioTranscriptionNodeData,
    ClassificationDecisionTableNodeData,
    ConditionalEdgeData,
    EdgeData,
    EndNodeData,
    FileExtractorNodeData,
    GraphData,
    PythonNodeData,
    SubGraphData,
    TaskNodeData,
    WebhookTriggerNodeData,
)
from src.shared.models.sessions import SessionData
from src.shared.models.storage_scope import StorageCredentials
from src.shared.models.tools import BaseToolData, PythonCodeData, PythonCodeToolData
from storage_credentials.services.storage_demand_collector import collect_storage_demand


def _make_python_code_data(
    use_storage: bool = False,
    storage_allowed_paths: list[str] | None = None,
    storage_org_prefix: str | None = None,
) -> PythonCodeData:
    """Helper to create PythonCodeData with storage scope."""
    return PythonCodeData(
        venv_name="test",
        code="print('test')",
        entrypoint="run",
        libraries=[],
        use_storage=use_storage,
        storage_allowed_paths=storage_allowed_paths,
        storage_org_prefix=storage_org_prefix,
    )


def _make_session_data(graph: GraphData) -> SessionData:
    """Helper to create SessionData with a graph."""
    return SessionData(
        id=1,
        graph=graph,
        unique_subgraph_list=[],
    )


def _make_empty_graph() -> GraphData:
    """Create a minimal GraphData with no storage nodes."""
    return GraphData(
        graph_id=1,
        name="test_graph",
        entrypoint="start",
        end_node=EndNodeData(node_name="end", output_map={}),
    )


def test_session_without_storage_demands_no_storage():
    """A session with no storage-demanding nodes returns needs_storage=False."""
    graph = _make_empty_graph()
    session = _make_session_data(graph)

    needs_storage, union_paths, org_prefix = collect_storage_demand(session)

    assert needs_storage is False
    assert union_paths == []
    assert org_prefix is None


def test_python_node_with_storage_is_found():
    """A PythonNodeData with use_storage=True is detected."""
    graph = _make_empty_graph()
    graph.python_node_list = [
        PythonNodeData(
            node_name="py_node",
            python_code=_make_python_code_data(
                use_storage=True,
                storage_allowed_paths=["flow/data"],
                storage_org_prefix="org_1",
            ),
            input_map={},
        )
    ]
    session = _make_session_data(graph)

    needs_storage, union_paths, org_prefix = collect_storage_demand(session)

    assert needs_storage is True
    assert "flow/data" in union_paths
    assert org_prefix == "org_1"


def test_file_extractor_node_with_storage_is_found():
    """FileExtractorNodeData (always has use_storage=True) is detected."""
    graph = _make_empty_graph()
    graph.file_extractor_node_list = [
        FileExtractorNodeData(
            node_name="file_ext",
            input_map={},
            storage_allowed_paths=["uploads"],
            storage_org_prefix="org_2",
        )
    ]
    session = _make_session_data(graph)

    needs_storage, union_paths, org_prefix = collect_storage_demand(session)

    assert needs_storage is True
    assert "uploads" in union_paths
    assert org_prefix == "org_2"


def test_audio_transcription_node_with_storage_is_found():
    """AudioTranscriptionNodeData (always has use_storage=True) is detected."""
    graph = _make_empty_graph()
    graph.audio_transcription_node_list = [
        AudioTranscriptionNodeData(
            node_name="audio",
            input_map={},
            storage_allowed_paths=["audio/input"],
            storage_org_prefix="org_3",
        )
    ]
    session = _make_session_data(graph)

    needs_storage, union_paths, org_prefix = collect_storage_demand(session)

    assert needs_storage is True
    assert "audio/input" in union_paths
    assert org_prefix == "org_3"


def test_classification_node_pre_python_code_with_storage_is_found():
    """ClassificationDecisionTableNodeData.pre_python_code is checked."""
    graph = _make_empty_graph()
    graph.classification_decision_table_node_list = [
        ClassificationDecisionTableNodeData(
            node_name="classify",
            pre_python_code=_make_python_code_data(
                use_storage=True,
                storage_allowed_paths=["classify/pre"],
                storage_org_prefix="org_4",
            ),
        )
    ]
    session = _make_session_data(graph)

    needs_storage, union_paths, org_prefix = collect_storage_demand(session)

    assert needs_storage is True
    assert "classify/pre" in union_paths
    assert org_prefix == "org_4"


def test_classification_node_post_python_code_with_storage_is_found():
    """ClassificationDecisionTableNodeData.post_python_code is checked."""
    graph = _make_empty_graph()
    graph.classification_decision_table_node_list = [
        ClassificationDecisionTableNodeData(
            node_name="classify",
            post_python_code=_make_python_code_data(
                use_storage=True,
                storage_allowed_paths=["classify/post"],
                storage_org_prefix="org_5",
            ),
        )
    ]
    session = _make_session_data(graph)

    needs_storage, union_paths, org_prefix = collect_storage_demand(session)

    assert needs_storage is True
    assert "classify/post" in union_paths
    assert org_prefix == "org_5"


def test_agent_node_tool_python_code_with_storage_is_found():
    """AgentNodeData.tools[].data.python_code is traversed."""
    graph = _make_empty_graph()
    graph.agent_node_list = [
        AgentNodeData(
            node_name="agent",
            input_map={},
            tools=[
                BaseToolData(
                    unique_name="python-code-tool:1",
                    data=PythonCodeToolData(
                        id=1,
                        name="tool",
                        description="",
                        python_code=_make_python_code_data(
                            use_storage=True,
                            storage_allowed_paths=["agent/tool"],
                            storage_org_prefix="org_6",
                        ),
                    ),
                )
            ],
        )
    ]
    session = _make_session_data(graph)

    needs_storage, union_paths, org_prefix = collect_storage_demand(session)

    assert needs_storage is True
    assert "agent/tool" in union_paths
    assert org_prefix == "org_6"


def test_task_node_tool_python_code_with_storage_is_found():
    """TaskNodeData.tools[].data.python_code is traversed."""
    graph = _make_empty_graph()
    graph.task_node_list = [
        TaskNodeData(
            node_name="task",
            input_map={},
            tools=[
                BaseToolData(
                    unique_name="python-code-tool:2",
                    data=PythonCodeToolData(
                        id=2,
                        name="tool",
                        description="",
                        python_code=_make_python_code_data(
                            use_storage=True,
                            storage_allowed_paths=["task/tool"],
                            storage_org_prefix="org_7",
                        ),
                    ),
                )
            ],
        )
    ]
    session = _make_session_data(graph)

    needs_storage, union_paths, org_prefix = collect_storage_demand(session)

    assert needs_storage is True
    assert "task/tool" in union_paths
    assert org_prefix == "org_7"


def test_conditional_edge_python_code_with_storage_is_found():
    """ConditionalEdgeData.python_code is checked."""
    graph = _make_empty_graph()
    graph.conditional_edge_list = [
        ConditionalEdgeData(
            source="node1",
            python_code=_make_python_code_data(
                use_storage=True,
                storage_allowed_paths=["edge/code"],
                storage_org_prefix="org_8",
            ),
            input_map={},
        )
    ]
    session = _make_session_data(graph)

    needs_storage, union_paths, org_prefix = collect_storage_demand(session)

    assert needs_storage is True
    assert "edge/code" in union_paths
    assert org_prefix == "org_8"


def test_webhook_trigger_node_with_storage_is_found():
    """WebhookTriggerNodeData.python_code is checked."""
    graph = _make_empty_graph()
    graph.webhook_trigger_node_data_list = [
        WebhookTriggerNodeData(
            node_name="webhook",
            python_code=_make_python_code_data(
                use_storage=True,
                storage_allowed_paths=["webhook/payload"],
                storage_org_prefix="org_9",
            ),
        )
    ]
    session = _make_session_data(graph)

    needs_storage, union_paths, org_prefix = collect_storage_demand(session)

    assert needs_storage is True
    assert "webhook/payload" in union_paths
    assert org_prefix == "org_9"


def test_webhook_trigger_node_without_storage_is_ignored():
    """WebhookTriggerNodeData with use_storage=False does not contribute to demand."""
    graph = _make_empty_graph()
    graph.webhook_trigger_node_data_list = [
        WebhookTriggerNodeData(
            node_name="webhook",
            python_code=_make_python_code_data(
                use_storage=False,
                storage_allowed_paths=["should/be/ignored"],
                storage_org_prefix="org_9",
            ),
        )
    ]
    session = _make_session_data(graph)

    needs_storage, union_paths, org_prefix = collect_storage_demand(session)

    assert needs_storage is False
    assert union_paths == []
    assert org_prefix is None


def test_webhook_trigger_node_in_subgraph_is_found():
    """Webhook trigger nodes inside subgraphs are traversed."""
    subgraph_data = GraphData(
        graph_id=2,
        name="subgraph",
        entrypoint="start",
        end_node=EndNodeData(node_name="end", output_map={}),
        webhook_trigger_node_data_list=[
            WebhookTriggerNodeData(
                node_name="sub_webhook",
                python_code=_make_python_code_data(
                    use_storage=True,
                    storage_allowed_paths=["subgraph/webhook"],
                    storage_org_prefix="org_9",
                ),
            )
        ],
    )

    session = SessionData(
        id=1,
        graph=_make_empty_graph(),
        unique_subgraph_list=[SubGraphData(id=2, data=subgraph_data)],
    )

    needs_storage, union_paths, org_prefix = collect_storage_demand(session)

    assert needs_storage is True
    assert "subgraph/webhook" in union_paths
    assert org_prefix == "org_9"


def test_every_storage_capable_node_list_is_collected():
    """Every GraphData list that can reach StorageScopedData contributes to the demand.

    Regression guard: a node list dropped from the collector's traversal silently
    stops its storage demand from being issued credentials.
    """
    graph = _make_empty_graph()
    graph.webhook_trigger_node_data_list = [
        WebhookTriggerNodeData(
            node_name="webhook",
            python_code=_make_python_code_data(
                use_storage=True, storage_allowed_paths=["p/webhook"]
            ),
        )
    ]
    graph.python_node_list = [
        PythonNodeData(
            node_name="py",
            python_code=_make_python_code_data(
                use_storage=True, storage_allowed_paths=["p/python"]
            ),
            input_map={},
        )
    ]
    graph.file_extractor_node_list = [
        FileExtractorNodeData(
            node_name="extractor", input_map={}, storage_allowed_paths=["p/extractor"]
        )
    ]
    graph.audio_transcription_node_list = [
        AudioTranscriptionNodeData(
            node_name="audio", input_map={}, storage_allowed_paths=["p/audio"]
        )
    ]
    graph.classification_decision_table_node_list = [
        ClassificationDecisionTableNodeData(
            node_name="classify",
            pre_python_code=_make_python_code_data(
                use_storage=True, storage_allowed_paths=["p/classify_pre"]
            ),
            post_python_code=_make_python_code_data(
                use_storage=True, storage_allowed_paths=["p/classify_post"]
            ),
        )
    ]
    graph.agent_node_list = [
        AgentNodeData(
            node_name="agent",
            input_map={},
            tools=[
                BaseToolData(
                    unique_name="python-code-tool:1",
                    data=PythonCodeToolData(
                        id=1,
                        name="tool",
                        description="",
                        python_code=_make_python_code_data(
                            use_storage=True, storage_allowed_paths=["p/agent_tool"]
                        ),
                    ),
                )
            ],
        )
    ]
    graph.task_node_list = [
        TaskNodeData(
            node_name="task",
            input_map={},
            tools=[
                BaseToolData(
                    unique_name="python-code-tool:2",
                    data=PythonCodeToolData(
                        id=2,
                        name="tool",
                        description="",
                        python_code=_make_python_code_data(
                            use_storage=True, storage_allowed_paths=["p/task_tool"]
                        ),
                    ),
                )
            ],
        )
    ]
    graph.conditional_edge_list = [
        ConditionalEdgeData(
            source="node1",
            python_code=_make_python_code_data(
                use_storage=True, storage_allowed_paths=["p/conditional_edge"]
            ),
            input_map={},
        )
    ]
    session = _make_session_data(graph)

    needs_storage, union_paths, _ = collect_storage_demand(session)

    assert needs_storage is True
    assert set(union_paths) == {
        "p/webhook",
        "p/python",
        "p/extractor",
        "p/audio",
        "p/classify_pre",
        "p/classify_post",
        "p/agent_tool",
        "p/task_tool",
        "p/conditional_edge",
    }


def test_graph_data_has_no_untriaged_node_lists():
    """Every GraphData list field is triaged as storage-capable or not.

    Tripwire: adding a list to GraphData fails here until its storage reachability
    is decided, so a new node type carrying PythonCodeData cannot be added without
    also being added to the collector.
    """
    storage_capable = {
        "webhook_trigger_node_data_list",
        "python_node_list",
        "file_extractor_node_list",
        "audio_transcription_node_list",
        "classification_decision_table_node_list",
        "agent_node_list",
        "task_node_list",
        "conditional_edge_list",
    }
    no_storage_fields = {
        "knowledge_node_list",
        "key_value_node_list",
        "subgraph_node_list",
        "edge_list",
        "decision_table_node_list",
        "telegram_trigger_node_data_list",
        "schedule_trigger_node_data_list",
    }

    actual_list_fields = {
        name
        for name, field in GraphData.model_fields.items()
        if typing.get_origin(field.annotation) is list
    }

    assert actual_list_fields == storage_capable | no_storage_fields


def test_multiple_storage_nodes_union_paths():
    """Multiple storage nodes contribute to the union of allowed_paths."""
    graph = _make_empty_graph()
    graph.python_node_list = [
        PythonNodeData(
            node_name="py1",
            python_code=_make_python_code_data(
                use_storage=True,
                storage_allowed_paths=["path1", "path2"],
                storage_org_prefix="org_1",
            ),
            input_map={},
        ),
        PythonNodeData(
            node_name="py2",
            python_code=_make_python_code_data(
                use_storage=True,
                storage_allowed_paths=["path2", "path3"],
                storage_org_prefix="org_1",
            ),
            input_map={},
        ),
    ]
    session = _make_session_data(graph)

    needs_storage, union_paths, org_prefix = collect_storage_demand(session)

    assert needs_storage is True
    assert set(union_paths) == {"path1", "path2", "path3"}
    assert org_prefix == "org_1"


def test_multiple_node_types_combined():
    """A graph with various storage-demanding node types."""
    graph = _make_empty_graph()
    graph.python_node_list = [
        PythonNodeData(
            node_name="py",
            python_code=_make_python_code_data(
                use_storage=True,
                storage_allowed_paths=["flow/py"],
                storage_org_prefix="org_1",
            ),
            input_map={},
        )
    ]
    graph.file_extractor_node_list = [
        FileExtractorNodeData(
            node_name="extractor",
            input_map={},
            storage_allowed_paths=["flow/extract"],
            storage_org_prefix="org_1",
        )
    ]
    graph.audio_transcription_node_list = [
        AudioTranscriptionNodeData(
            node_name="audio",
            input_map={},
            storage_allowed_paths=["flow/audio"],
            storage_org_prefix="org_1",
        )
    ]
    session = _make_session_data(graph)

    needs_storage, union_paths, org_prefix = collect_storage_demand(session)

    assert needs_storage is True
    assert set(union_paths) == {"flow/py", "flow/extract", "flow/audio"}
    assert org_prefix == "org_1"


def test_subgraph_with_storage_is_found():
    """Storage nodes in subgraphs are traversed and detected."""
    main_graph = _make_empty_graph()

    subgraph_data = GraphData(
        graph_id=2,
        name="subgraph",
        entrypoint="start",
        end_node=EndNodeData(node_name="end", output_map={}),
        python_node_list=[
            PythonNodeData(
                node_name="sub_py",
                python_code=_make_python_code_data(
                    use_storage=True,
                    storage_allowed_paths=["subgraph/path"],
                    storage_org_prefix="org_1",
                ),
                input_map={},
            )
        ],
    )

    session = SessionData(
        id=1,
        graph=main_graph,
        unique_subgraph_list=[SubGraphData(id=2, data=subgraph_data)],
    )

    needs_storage, union_paths, org_prefix = collect_storage_demand(session)

    assert needs_storage is True
    assert "subgraph/path" in union_paths
    assert org_prefix == "org_1"


def test_python_node_without_storage_is_ignored():
    """PythonNodeData with use_storage=False does not contribute to demand."""
    graph = _make_empty_graph()
    graph.python_node_list = [
        PythonNodeData(
            node_name="py_no_storage",
            python_code=_make_python_code_data(
                use_storage=False,
                storage_allowed_paths=["should/be/ignored"],
                storage_org_prefix="org_1",
            ),
            input_map={},
        )
    ]
    session = _make_session_data(graph)

    needs_storage, union_paths, org_prefix = collect_storage_demand(session)

    assert needs_storage is False
    assert union_paths == []
    assert org_prefix is None


def test_classification_node_with_both_pre_and_post_codes():
    """Both pre_python_code and post_python_code are checked."""
    graph = _make_empty_graph()
    graph.classification_decision_table_node_list = [
        ClassificationDecisionTableNodeData(
            node_name="classify",
            pre_python_code=_make_python_code_data(
                use_storage=True,
                storage_allowed_paths=["classify/pre"],
                storage_org_prefix="org_1",
            ),
            post_python_code=_make_python_code_data(
                use_storage=True,
                storage_allowed_paths=["classify/post"],
                storage_org_prefix="org_1",
            ),
        )
    ]
    session = _make_session_data(graph)

    needs_storage, union_paths, org_prefix = collect_storage_demand(session)

    assert needs_storage is True
    assert set(union_paths) == {"classify/pre", "classify/post"}
    assert org_prefix == "org_1"


def test_org_prefix_is_first_found():
    """When multiple nodes exist, org_prefix is the first one found (not None)."""
    graph = _make_empty_graph()
    graph.python_node_list = [
        PythonNodeData(
            node_name="py1",
            python_code=_make_python_code_data(
                use_storage=True,
                storage_allowed_paths=["path1"],
                storage_org_prefix="org_A",
            ),
            input_map={},
        ),
        PythonNodeData(
            node_name="py2",
            python_code=_make_python_code_data(
                use_storage=True,
                storage_allowed_paths=["path2"],
                storage_org_prefix="org_B",
            ),
            input_map={},
        ),
    ]
    session = _make_session_data(graph)

    needs_storage, union_paths, org_prefix = collect_storage_demand(session)

    assert needs_storage is True
    assert org_prefix == "org_A"


def test_node_with_none_storage_allowed_paths():
    """A node with use_storage=True but None storage_allowed_paths is still detected."""
    graph = _make_empty_graph()
    graph.python_node_list = [
        PythonNodeData(
            node_name="py",
            python_code=_make_python_code_data(
                use_storage=True,
                storage_allowed_paths=None,
                storage_org_prefix="org_1",
            ),
            input_map={},
        )
    ]
    session = _make_session_data(graph)

    needs_storage, union_paths, org_prefix = collect_storage_demand(session)

    assert needs_storage is True
    assert union_paths == []
    assert org_prefix == "org_1"


def test_complex_graph_with_mixed_storage_and_non_storage_nodes():
    """A complex graph with mix of storage and non-storage nodes."""
    graph = _make_empty_graph()
    graph.python_node_list = [
        PythonNodeData(
            node_name="py_with_storage",
            python_code=_make_python_code_data(
                use_storage=True,
                storage_allowed_paths=["path1"],
                storage_org_prefix="org_1",
            ),
            input_map={},
        ),
        PythonNodeData(
            node_name="py_without_storage",
            python_code=_make_python_code_data(
                use_storage=False,
                storage_allowed_paths=["ignored"],
                storage_org_prefix="org_1",
            ),
            input_map={},
        ),
    ]
    graph.file_extractor_node_list = [
        FileExtractorNodeData(
            node_name="extractor",
            input_map={},
            storage_allowed_paths=["path2"],
            storage_org_prefix="org_1",
        )
    ]
    session = _make_session_data(graph)

    needs_storage, union_paths, org_prefix = collect_storage_demand(session)

    assert needs_storage is True
    assert set(union_paths) == {"path1", "path2"}
    assert org_prefix == "org_1"
