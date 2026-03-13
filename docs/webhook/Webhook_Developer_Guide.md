🛠️ Webhook Developer Guide
This guide covers the technical architecture and maintenance of the webhook system.

System Architecture
The webhook system is a three-part architecture that decouples the public-facing receiver from the internal graph execution.

Django Application (The "Core"):

Purpose: The main platform where users build graphs.

Components:


NgrokWebhookConfig (model): Defines custom Ngrok tunnel settings including name, auth_token, domain, and region.



WebhookTrigger / WebhookTriggerNode (models): These link a Graph to the trigger and optionally map to a specific NgrokWebhookConfig via the ngrok_webhook_config foreign key.

API ViewSets: Exposes CRUD endpoints to manage configurations and triggers (e.g., NgrokWebhookConfigViewSet and /api/webhook-trigger-nodes/).

Management & Signals: The backend registers tunnels dynamically by pushing config data to a Redis channel (REDIS_TUNNEL_CONFIG_CHANNEL) automatically when configurations are saved or deleted.


FastAPI Webhook Service (The "Receiver"):

Purpose: A standalone, lightweight service (run.py, main.py) that receives incoming webhooks from the public internet.


Tunneling (TunnelRegistry): Instead of a single static tunnel, the application uses a TunnelRegistry that listens to the REDIS_TUNNEL_CONFIG_CHANNEL to dynamically register, update, or remove multiple Ngrok tunnels on the fly. The tunnels also include an auto-reconnect background task if they fail.


Endpoints:

Public route: e.g., @router.post("/webhooks/{trigger_id}/")

Tunnel URL helper: /api/tunnel-url/{unique_id} dynamically fetches the public URL of a specific tunnel.

Core Logic: When a POST request hits /webhooks/{trigger_id}/:

It extracts the trigger_id from the URL.

It parses the JSON payload from the request body.

It queries the Django database to find the WebhookTriggerNode matching the trigger_id.

From this node, it retrieves the associated Graph schema.

It identifies the node_name of the WebhookTriggerNode to use as the graph's entrypoint.

It constructs a SessionData object. The initial_state["variables"] are set to the parsed JSON payload.

It publishes this SessionData object as a JSON string to the session_schema_channel on Redis.

Key Files Summary
run.py: Entrypoint for the FastAPI "Receiver" service.


main.py: FastAPI app factory; sets up the lifespan context to subscribe to Redis tunnel configurations.


tunnel_registry.py: Replaces the old webhook_service.py to maintain a pool of multiple AbstractTunnelProvider instances.



provider_factory.py / ngrok_tunnel.py: Factories and implementation for configuring robust Ngrok connections.


graph_session_manager_service.py: The "Worker" service. Listens to Redis session_schema_channel and manages the session lifecycle.

graph_builder.py: Compiles the langgraph graph from the schema.

webhook_trigger_node.py: Executing Python code to process the incoming payload.

model_view_sets.py / urls.py: Define Django API endpoints for creating configs and triggers.


Webhook-Related API Endpoints
-----------------------------

This section summarizes the REST API endpoints and payloads relevant to
webhook triggers.

WebhookTrigger
~~~~~~~~~~~~~~

- **Endpoint**: `/api/webhook-triggers/`  
- **Methods**: `GET`, `POST`, `PUT`, `PATCH`, `DELETE`

Represents the logical webhook entry, including its path and associated Ngrok
configuration.

**Fields:**

- **path** *(string, required)*: Unique path part used by the FastAPI receiver.
  - Pattern: `^[a-zA-Z0-9]{1}[a-zA-Z0-9-_]*$`
  - Length: 1–255 characters.
- **ngrok_webhook_config** *(integer, optional)*: ID of the `NgrokWebhookConfig`
  that defines the tunnel (domain, token, region).

**Example `POST /api/webhook-triggers/` body:**

```json
{
  "path": "myWebhook123",
  "ngrok_webhook_config": 2
}
```

WebhookTriggerNode
~~~~~~~~~~~~~~~~~~

- **Endpoint**: `/api/webhook-trigger-nodes/`  
- **Methods**: `GET`, `POST`, `PUT`, `PATCH`, `DELETE`

Represents a node in the graph that starts execution when a webhook is
received.

**Fields:**

- **node_name** *(string, required)*: Display name of the node (1–255 chars).
- **graph** *(integer, required)*: ID of the graph that owns this node.
- **python_code** *(object, required)*: Python code executed when the webhook
  fires.
  - **libraries** *(string[])*: List of library names to import.
  - **code** *(string, required)*: Source code.
  - **entrypoint** *(string, required)*: Name of the function to call.
  - **global_kwargs** *(object, optional)*: Arbitrary key/value pairs available
    to the code.
- **webhook_trigger** *(object, optional)*: Nested `WebhookTrigger` definition.
  - **path** *(string, required)*: Webhook path (see `WebhookTrigger` above).
  - **ngrok_webhook_config** *(integer, optional)*: ID of the associated
    `NgrokWebhookConfig`.

**Example `POST /api/webhook-trigger-nodes/` body:**

```json
{
  "node_name": "My Webhook Trigger",
  "graph": 1,
  "python_code": {
    "libraries": ["requests", "json"],
    "code": "def handler(event, context):\n    # your logic here\n    return event",
    "entrypoint": "handler",
    "global_kwargs": {
      "some_flag": true
    }
  },
  "webhook_trigger": {
    "path": "myWebhook123",
    "ngrok_webhook_config": 2
  }
}
```