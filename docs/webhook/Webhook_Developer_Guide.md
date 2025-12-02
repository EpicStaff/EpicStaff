##`Webhook_Developer_Guide.md`


# 🛠️ Webhook Developer Guide

This guide covers the technical architecture and maintenance of the webhook system.

## System Architecture

The webhook system is a **three-part architecture** that decouples the public-facing receiver from the internal graph execution.

1.  **Django Application (The "Core"):**
    * **Purpose:** The main platform where users build graphs.
    * **Components:**
        * `WebhookTriggerNode` (model): Defined in `tables.models.graph_models`. This model links a `Graph` to the node.
        * `WebhookTriggerNodeViewSet` (API): Defined in `tables.views.model_view_sets`. This exposes a CRUD endpoint (e.g., `/api/webhook-trigger-nodes/`) for the UI to create, read, and configure these nodes.

2.  **FastAPI Webhook Service (The "Receiver"):**
    * **Purpose:** A standalone, lightweight service (`run.py`, `main.py`) that receives incoming webhooks from the public internet. It is designed to be the *only* service exposed publicly, enhancing security.
    * **Tunneling:** It uses `pyngrok` (managed by `WebhookService` in `webhook_service.py`) to create a secure public URL on startup if configured.
    * **Endpoint:** It includes routes (from `webhook_routes.py`) that define the public endpoint, e.g., `@router.post("/webhooks/{trigger_id}/")`.
    * **Core Logic:** When a `POST` request hits `/webhooks/{trigger_id}/`:
        1.  It extracts the `trigger_id` from the URL.
        2.  It parses the JSON payload from the request body.
        3.  It must query the Django database to find the `WebhookTriggerNode` matching the `trigger_id`.
        4.  From this node, it retrieves the associated `Graph` schema.
        5.   It identifies the `node_name` of the `WebhookTriggerNode` (e.g., `"webhook_trigger_123"`) to use as the graph's `entrypoint`.
        6.  It constructs a `SessionData` object. The `initial_state["variables"]` are set to the parsed JSON payload.
        7.  It publishes this `SessionData` object as a JSON string to the `session_schema_channel` on Redis.

## Execution Flow of the WebhookTriggerNode

This is how the webhook payload is processed *inside* the graph:

1.  **Graph Start:** The `GraphSessionManagerService` starts the session, and `langgraph` immediately jumps to the graph's entrypoint, which is the `node_name` of the `WebhookTriggerNode`.

2.  **Node Execution:** `WebhookTriggerNode.run()` is called.

3.  **Get Input:** The `BaseNode.get_input()` method is called. Because the `WebhookTriggerNode` hardcodes `input_map="__all__"`, this method returns the *entire* `state["variables"]` object, which contains the original JSON payload from the webhook.

4.  **Run Code:** `WebhookTriggerNode.execute()` is called. It passes the `state["variables"]` (as the `inputs` kwarg) to the `python_code_executor_service`, along with the specific Python code stored on that node.

5.  **Process Payload:** The node's Python code runs, using the webhook payload as its `inputs` variable. It can perform any validation or transformation.

6.  **Set Output:** The Python code *must* return a dictionary. The `BaseNode`'s `run` method captures this dictionary. Because `WebhookTriggerNode` hardcodes `output_variable_path="variables"`, this returned dictionary *replaces* the entire `state["variables"]` object.

7.  **Continue Graph:** The graph execution proceeds to the next connected node, but now using the new, processed state returned by the `WebhookTriggerNode`.

### Key Files Summary

* **`run.py`**: Entrypoint for the FastAPI "Receiver" service.
* **`main.py`**: FastAPI app factory; includes routes and the `/api/tunnel-url` helper.
* **`webhook_service.py`**: Orchestrates `uvicorn` and the `pyngrok` tunnel for the Receiver.
* **`graph_session_manager_service.py`**: The "Worker" service. Listens to Redis `session_schema_channel` and manages the session lifecycle.
* **`graph_builder.py`**: Compiles the `langgraph` graph from the schema, adding the `WebhookTriggerNode` as a runnable node.
* **`webhook_trigger_node.py`**: The `langgraph` node implementation. Executes Python code to process the incoming payload.
* **`base_node.py`**: Provides the base `run` logic, including the `input_map="__all__"` and `output_variable_path="variables"` handling.
* **`model_view_sets.py` / `urls.py`**: Define the Django API endpoint for creating and managing `WebhookTriggerNode` models in the "Core" application.
