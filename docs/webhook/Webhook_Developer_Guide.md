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
3. The matched config carries a single inbound auth strategy (`config.auth`, resolved from that trigger's `WebhookTriggerAuth` row -- one per `WebhookTrigger`, not per node). It reads the header named by `auth.header_name` and compares it against `auth.secret` with `hmac.compare_digest` (see "Webhook Inbound Authentication" below). If `config.auth` is `None`, or the header is missing/doesn't match -> `401`. There is no auth-free passthrough: every trigger either has auth configured or the request is rejected (fail-closed).
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

Webhook Inbound Authentication (`WebhookTriggerAuth`)
------------------------------------------------------

Auth is configured once per `WebhookTrigger`, not per node. Each
`WebhookTrigger` can carry one `WebhookTriggerAuth` row
(`tables.models.webhook_models.WebhookTriggerAuth`, a one-to-one on
`trigger`) that gates every inbound request on that trigger's
`/webhooks/{path}/` route. There are three fixed strategies
(`WebhookTriggerAuthKind`), each with a code-constant header name
(`WebhookTriggerAuth.HEADER_NAMES`):

- **`webhook`** -- generic `WebhookTriggerNode`s. Header:
  `EPICSTAFF_API_KEY`. User-settable: the client points `auth_secret_id` at
  an existing `Secret` (holding the plaintext key the sender must send back
  in that header) via `WebhookTriggerService.set_trigger_auth_secret`.
- **`telegram`** -- `TelegramTriggerNode`s. Header:
  `X-Telegram-Bot-Api-Secret-Token`. Also user-settable via
  `set_trigger_auth_secret`, but in practice it is normally auto-provisioned
  and kept in sync by `TelegramTriggerService.register_telegram_trigger`
  (which passes the resolved plaintext to Telegram's `setWebhook` as
  `secret_token`); Telegram echoes it back on every update, and the
  `webhook` service compares it against the stored secret.
- **`twilio`** -- reserved via `set_trigger_auth_secret(kind="twilio")` as a
  bare, secret-less claim on the trigger (it rejects an explicit `secret`
  argument for this kind); the row is filled in once a `TwilioChannel`
  claims the trigger and syncs its own `auth_token_secret` onto it. This
  kind has **no** `src/webhook`-side header check at all
  (`WebhookTriggerAuth.header_name` returns `None` for it) -- Twilio inbound
  requests are authenticated separately, in `src/realtime`, by verifying the
  `X-Twilio-Signature` header against `TwilioChannel.auth_token_secret` (see
  `src/realtime/utils/twilio_signature.py`).

For both user-settable kinds, the resolved plaintext secret must be at
least `AUTH_SECRET_MIN_LENGTH = 32` characters
(`webhook_trigger_service.AUTH_SECRET_MIN_LENGTH`); `telegram` additionally
runs `validate_telegram_secret_token` (1-256 chars, `[A-Za-z0-9_-]` only) on
top of the length check. `set_trigger_auth_secret` also enforces: a trigger's
`kind` can't be changed once set (must delete/recreate the auth row to
switch strategies) and a trigger can only be claimed by nodes/channels of
one kind at a time -- `kind="webhook"` is rejected if a Telegram node is
already attached (and vice versa), and `kind="twilio"` is rejected if either
a webhook or Telegram node is already attached. Cross-type conflicts are
also enforced at the node-attach layer (`trigger_serializers.py`
validation) and orphaned `WebhookTriggerAuth` rows are cleaned up by
signals in `webhook_signals.py`/`telegram_signals.py` when the last node of
a kind is detached.

**Configuring it:** via `/api/webhook-triggers/` (`WebhookTriggerNestedSerializer`
in `tables/serializers/base_serializers.py`), write-only fields
`auth_kind` (`webhook` / `telegram` / `twilio`) and `auth_secret_id` (id of
an existing `Secret`). The read-only nested `auth` object on the trigger
representation exposes `{"kind": ..., "secret_tail": ...}` -- the resolved
secret's plaintext is never returned through the API, only its `tail`
(a truncated preview) via `Secret.tail`.

**Response codes** from the `webhook` service's auth layer: `401` when the
trigger has no `WebhookTriggerAuth` configured, or the request's header is
missing or doesn't match the stored secret (fail-closed -- there is no
auth-free passthrough), `409` when the requested path matches more than one
registered tunnel config (ambiguous routing), `422` when the request body
is not valid JSON (rejected by FastAPI's own body parsing before auth
runs).