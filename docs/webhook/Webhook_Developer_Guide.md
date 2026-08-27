🛠️ Webhook Developer Guide
This guide covers the technical architecture and maintenance of the webhook system.

System Architecture
The webhook system is a three-part architecture that decouples the public-facing receiver from the internal graph execution.

Django Application (The "Core"):

Purpose: The main platform where users build graphs.

Components:


NgrokWebhookConfig (model): Defines custom Ngrok tunnel settings including name, `auth_token_secret` (a `ForeignKey` to `Secret`, `on_delete=SET_NULL` -- the token is never stored as plaintext on this model), domain, and region.



WebhookTrigger / WebhookTriggerNode (models): These link a Graph to the trigger. `WebhookTrigger` itself only has `path` and `provider_type`; the actual tunnel config lives on a separate row pointing back at it -- `NgrokWebhookConfig.trigger` (reverse accessor `trigger.ngrok`) or `LocalhostWebhookConfig.trigger` (reverse accessor `trigger.localhost`), selected by `provider_type`.

API ViewSets: Exposes CRUD endpoints to manage configurations and triggers (e.g., NgrokWebhookConfigViewSet and /api/webhook-trigger-nodes/).

Management & Signals: The backend registers tunnels dynamically by pushing config data to a Redis channel (REDIS_TUNNEL_CONFIG_CHANNEL) automatically when configurations are saved or deleted.


FastAPI Webhook Service (The "Receiver"):

Purpose: A standalone, lightweight service (run.py, main.py) that receives incoming webhooks from the public internet.


Tunneling (TunnelRegistry): Instead of a single static tunnel, the application uses a TunnelRegistry that listens to the REDIS_TUNNEL_CONFIG_CHANNEL to dynamically register, update, or remove multiple Ngrok tunnels on the fly. The tunnels also include an auto-reconnect background task if they fail.


Endpoints:

Public route: `@router.post("/webhooks/{custom_path:path}")` (`webhook_routes.handle_webhook`). `{custom_path}` is `WebhookTrigger.path` -- an opaque, intentionally-unguessable string routing key (like a Stripe/GitHub webhook URL) -- **not** a numeric trigger or node ID.

Tunnel URL lookup: there is no HTTP endpoint for this. Django reads the live public URL directly out of Redis -- `WebhookTriggerService._get_tunnel_url(config)` does `redis_client.hget(TUNNEL_URLS_HASH_KEY, config.get_redis_key())` against the hash the `webhook` FastAPI service writes to whenever a tunnel comes up. `get_tunnel_url`/`get_localhost_tunnel_url`/`get_tunnel_url_for_trigger` are thin wrappers around it (provider-specific or provider-agnostic via `WebhookTrigger.get_active_config()`), and `wait_for_tunnel_url`/`wait_for_localhost_tunnel_url` poll it with a timeout right after a trigger is created.

Core Logic: When a POST request hits `/webhooks/{custom_path}/`, the `webhook` FastAPI service has **no database access at all** -- there are no Django/DB imports anywhere in it. Routing and auth are resolved purely in-memory / via Redis, and Django only gets involved after the fact:

1. It parses the JSON payload from the request body (a malformed body is rejected by FastAPI's own parsing with `422` before anything below runs).
2. It resolves `custom_path` to a registered tunnel config via `TunnelRegistry.resolve_by_path` -- an in-memory pool of `BaseTunnelConfigData` entries (populated from messages Django publishes on `REDIS_TUNNEL_CONFIG_CHANNEL` whenever a `WebhookTrigger`/tunnel config is saved or deleted), matched purely by `config.name == custom_path`. No match -> `404`. More than one tunnel config registered for the same path -> `409` (fails closed rather than guessing which one owns the request).
3. If the matched config carries any inbound auth credentials (`config.auths` -- one entry per node with an enabled `WebhookNodeAuth` sharing this path), it verifies the request against each in turn (`static_header` or `hmac_sha256` -- see "Webhook Inbound Authentication" below). No credential matches -> `401`, unless the path also has an auth-free node sharing it, in which case the request is forwarded scoped to that node only (fail-open passthrough, never for Telegram).
4. It republishes the payload -- plus the resolved `config_id` and, when one credential matched, that node's `auth_principal` -- to Redis for Django to pick up. No `SessionData`/graph knowledge lives in this service.
5. On the Django side, `WebhookTriggerService.handle_webhook_trigger` / `TelegramTriggerService.handle_telegram_trigger` resolve the actual `WebhookTriggerNode` / `TelegramTriggerNode` row(s) by filtering on `webhook_trigger__path` (plus org/provider scoping parsed out of `config_id`), read each matched node's `graph` and `node_name` as the entrypoint, and call `run_session(variables={"trigger_payload": payload}, ...)` (`telegram_payload` for Telegram).

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

Represents the logical webhook entry, including its path and its associated
tunnel configuration. Served by `WebhookTriggerNestedSerializer`; exactly one
of `ngrok_config` / `localhost_config` may be set, matching `provider_type`.

**Fields:**

- **path** *(string, required)*: Unique path part used by the FastAPI receiver.
  - Pattern: `^[a-zA-Z0-9]{1}[a-zA-Z0-9-_]*$`
  - Length: 1–255 characters.
- **provider_type** *(string, optional)*: `"ngrok"` or `"localhost"`.
- **ngrok_config** *(object, optional)*: Required when `provider_type` is
  `"ngrok"`. Nested `NgrokWebhookConfig` fields:
  - **name** *(string, required)*
  - **auth_token_secret_id** *(integer, optional)*: ID of the `Secret` holding
    the ngrok auth token.
  - **domain** *(string, optional)*
  - **region** *(string, optional)*: one of `NgrokWebhookConfig.Region`
    (`us`/`eu`/`ap`), defaults to `eu`.
- **localhost_config** *(object, optional)*: Required when `provider_type` is
  `"localhost"`. Nested `LocalhostWebhookConfig` fields:
  - **name** *(string, required)*
  - **domain** *(string, optional)*
- **live_url** *(string, read-only)*: Resolved public webhook URL
  (`{tunnel_base}/webhooks/{path}`), or `null` if the tunnel isn't up yet.

**Example `POST /api/webhook-triggers/` body:**

```json
{
  "path": "myWebhook123",
  "provider_type": "ngrok",
  "ngrok_config": {
    "name": "my-tunnel",
    "auth_token_secret_id": 2,
    "region": "eu"
  }
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
- **webhook_trigger** *(integer, optional, write)*: ID of an **existing**
  `WebhookTrigger` row to attach. This endpoint does not create a
  `WebhookTrigger` inline -- create it first via `POST /api/webhook-triggers/`
  (see above), then attach it here by id.
  - On `GET`/`list`/`retrieve` (`WebhookTriggerNodeReadSerializer`), this
    field is instead rendered as the full nested `WebhookTrigger`
    representation (`id`, `path`, `provider_type`, `ngrok_config`,
    `localhost_config`, `live_url` -- see `WebhookTrigger` fields above).

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
  "webhook_trigger": 5
}
```

Webhook Inbound Authentication (`WebhookNodeAuth`)
---------------------------------------------------

Every `TelegramTriggerNode` and `WebhookTriggerNode` can carry one
`WebhookNodeAuth` row (`tables.models.webhook_models.WebhookNodeAuth`, a
one-to-one keyed by exactly one of `telegram_trigger_node` /
`webhook_trigger_node`) that gates inbound requests on the shared
`/webhooks/{path}/` route. There are two schemes
(`WebhookAuthScheme`):

- **`static_header`** -- Telegram only. Mandatory and fully automatic:
  `TelegramTriggerService.register_telegram_trigger` mints a random token
  (`secrets.token_urlsafe(32)`), passes it as `secret_token` on Telegram's
  `setWebhook` call, and stores only a PBKDF2 hash of it
  (`WebhookNodeAuth.secret_hash`, via Django's `make_password` /
  `check_password`) -- the raw token is never persisted or exposed through
  the API. Telegram echoes the token back on every update as the
  `X-Telegram-Bot-Api-Secret-Token` header, which the `webhook` service
  verifies with `django_pbkdf2_sha256.verify` (run off the event loop via
  `run_in_threadpool`, since PBKDF2 verification is CPU-bound). There is
  nothing for the API consumer to configure.
- **`hmac_sha256`** -- generic `WebhookTriggerNode`s. Enabled by default but
  user-toggleable. `WebhookTriggerService.ensure_webhook_auth` generates a
  plaintext `signing_secret` (`secrets.token_hex(32)`) that **is** returned
  through the API (`WebhookNodeAuthSerializer.signing_secret`) so the
  developer can configure their sending system. The sender must compute:

  ```
  signature = hex(HMAC-SHA256(key=signing_secret, msg=f"{timestamp}.{raw_body}"))
  ```

  and send it as two headers:
  - `X-Webhook-Signature: <signature>`
  - `X-Webhook-Timestamp: <unix timestamp>`

  The `webhook` service (`webhook_routes.verify_hmac_signature`) recomputes
  the same HMAC and compares with `hmac.compare_digest`. A timestamp is only
  accepted within `tolerance_seconds` in the past (default `300`) and up to
  `CLOCK_SKEW_ALLOWANCE_SECONDS` (5s) in the future. A valid, fresh signature
  is also checked against a Redis-backed replay cache
  (`webhook:seen:<principal>:<signature>`, TTL = `tolerance_seconds`) so a
  captured request/signature pair can't be replayed.

**Toggling:** the only client-writable sub-field is `enabled`, via
`PATCH /api/webhook-trigger-nodes/{id}/` with body
`{"webhook_node_auth": {"enabled": false}}`. Every other field (`scheme`,
`header_name`, `signing_secret`, `secret_hash`, ...) is server-controlled --
`WebhookNodeAuthInputSerializer` accepts and validates only `enabled`,
silently ignoring anything else sent alongside it. Re-enabling reuses the
existing `signing_secret` rather than rotating it
(`WebhookTriggerService.ensure_webhook_auth` never disables an existing row
and only backfills a missing secret), so disabling and re-enabling never
breaks an already-configured sending system. `TelegramTriggerNode`'s auth is
not exposed for toggling at all -- it is always on.

**Response codes** from the `webhook` service's auth layer: `401` when no
credential on the path matches (and no auth-free node shares the path),
`409` when the requested path matches more than one registered tunnel
config (ambiguous routing), `422` when the request body is not valid JSON
(rejected by FastAPI's own body parsing before auth runs).