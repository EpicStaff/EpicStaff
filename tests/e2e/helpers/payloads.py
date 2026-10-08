"""Request bodies shared by several tests."""

import uuid

PYTHON_NODE_NAME = "e2e_python"
PYTHON_SUM_CODE = 'def main(a, b):\n    return {"sum": a + b}'


def python_flow_save_payload(
    graph_id: int, save_version: int, code: str = PYTHON_SUM_CODE
) -> dict:
    """Bulk-save body for flow A: Start -> Python (`a + b`) -> End.

    Run with `{"a": 2, "b": 3}` it ends with `variables.result == {"sum": 5}`. The
    Start -> Python edge is what makes Python the entrypoint. `temp_id`s are not echoed
    back; find the created python node by `PYTHON_NODE_NAME`. `code` replaces the node's
    code, keeping the `main(a, b)` entrypoint.
    """
    start_temp_id = str(uuid.uuid4())
    python_temp_id = str(uuid.uuid4())
    end_temp_id = str(uuid.uuid4())
    return {
        "save_version": save_version,
        "start_node_list": [{"temp_id": start_temp_id, "graph": graph_id, "variables": {}}],
        "python_node_list": [
            {
                "temp_id": python_temp_id,
                "graph": graph_id,
                "node_name": PYTHON_NODE_NAME,
                "input_map": {"a": "variables.a", "b": "variables.b"},
                "output_variable_path": "variables.result",
                "python_code": {
                    "code": code,
                    "entrypoint": "main",
                    "libraries": [],
                },
            }
        ],
        "end_node_list": [
            {"temp_id": end_temp_id, "graph": graph_id, "output_map": {"result": "variables.result"}}
        ],
        "edge_list": [
            {"graph": graph_id, "start_temp_id": start_temp_id, "end_temp_id": python_temp_id},
            {"graph": graph_id, "start_temp_id": python_temp_id, "end_temp_id": end_temp_id},
        ],
    }


KNOWLEDGE_NODE_NAME = "e2e_knowledge"
TASK_NODE_NAME = "e2e_task"
AGENT_RAG_QUESTION = "What is the token?"


def agent_rag_flow_save_payload(
    graph_id: int,
    save_version: int,
    *,
    collection_id: int,
    naive_rag_id: int,
    agent_definition_id: int,
    surface_id: int,
) -> dict:
    """Bulk-save body for flow B: Start -> Knowledge (naive RAG) -> Task (agent) -> End.

    The knowledge node writes the joined chunk texts to `variables.kb_hits`; the task node
    writes the agent's final answer text (a string) to `variables.answer`. The task node's
    `surface_list` is set explicitly: an agent's default surfaces are not applied at run time.
    """
    start_temp_id = str(uuid.uuid4())
    knowledge_temp_id = str(uuid.uuid4())
    task_temp_id = str(uuid.uuid4())
    end_temp_id = str(uuid.uuid4())
    question_input = {"question": "variables.question"}
    return {
        "save_version": save_version,
        "start_node_list": [
            {
                "temp_id": start_temp_id,
                "graph": graph_id,
                "variables": {"question": AGENT_RAG_QUESTION},
            }
        ],
        "knowledge_node_list": [
            {
                "temp_id": knowledge_temp_id,
                "graph": graph_id,
                "node_name": KNOWLEDGE_NODE_NAME,
                "source_collection": collection_id,
                "rag_type": "naive",
                "rag_id": naive_rag_id,
                "query": "{question}",
                "input_map": question_input,
                "output_variable_path": "variables.kb_hits",
                "search_configs": {"naive": {"search_limit": 3, "similarity_threshold": 0.2}},
            }
        ],
        "task_node_list": [
            {
                "temp_id": task_temp_id,
                "graph": graph_id,
                "node_name": TASK_NODE_NAME,
                "agent_definition": agent_definition_id,
                "surface_list": [surface_id],
                "instructions": "Question: {question}",
                "input_map": question_input,
                "output_variable_path": "variables.answer",
            }
        ],
        "end_node_list": [
            {"temp_id": end_temp_id, "graph": graph_id, "output_map": {"answer": "variables.answer"}}
        ],
        "edge_list": [
            {"graph": graph_id, "start_temp_id": start_temp_id, "end_temp_id": knowledge_temp_id},
            {"graph": graph_id, "start_temp_id": knowledge_temp_id, "end_temp_id": task_temp_id},
            {"graph": graph_id, "start_temp_id": task_temp_id, "end_temp_id": end_temp_id},
        ],
    }


def start_end_flow_save_payload(graph_id: int, save_version: int) -> dict:
    """Bulk-save body for the smallest runnable flow: Start -> End, no sandbox, no LLM."""
    start_temp_id = str(uuid.uuid4())
    end_temp_id = str(uuid.uuid4())
    return {
        "save_version": save_version,
        "start_node_list": [{"temp_id": start_temp_id, "graph": graph_id, "variables": {}}],
        "end_node_list": [{"temp_id": end_temp_id, "graph": graph_id, "output_map": {}}],
        "edge_list": [{"graph": graph_id, "start_temp_id": start_temp_id, "end_temp_id": end_temp_id}],
    }
