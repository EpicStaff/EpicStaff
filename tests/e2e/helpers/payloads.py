"""Request bodies shared by several tests."""

import uuid

PYTHON_NODE_NAME = "e2e_python"
PYTHON_SUM_CODE = 'def main(a, b):\n    return {"sum": a + b}'


def python_flow_save_payload(graph_id: int, save_version: int) -> dict:
    """Bulk-save body for flow A: Start -> Python (`a + b`) -> End.

    Run with `{"a": 2, "b": 3}` it ends with `variables.result == {"sum": 5}`. The
    Start -> Python edge is what makes Python the entrypoint. `temp_id`s are not echoed
    back; find the created python node by `PYTHON_NODE_NAME`.
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
                    "code": PYTHON_SUM_CODE,
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
