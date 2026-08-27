Telegram Trigger API Endpoints
==============================

This document describes the HTTP endpoints used to manage Telegram Trigger nodes
and to synchronize webhook registrations.

1. Manage Telegram Trigger Nodes
--------------------------------

- **Endpoint**: `/api/telegram-trigger-nodes/`  
- **Methods**: `GET`, `POST`, `PUT`, `PATCH`, `DELETE`

Use this endpoint to create and configure a Telegram Trigger node within a
graph. You can associate a specific `NgrokWebhookConfig` to handle the Telegram
webhook tunnel.

### 1.1 Create (POST) Request Body

```json
{
  "node_name": "My Telegram Trigger",
  "telegram_bot_api_key_secret_id": 42,
  "graph": 1,
  "fields": [
    {
      "parent": "message",
      "field_name": "text",
      "variable_path": "variables.telegram_data.user_input"
    }
  ],
  "webhook_trigger": 5
}
```

Note: the bot token is never accepted or returned as plaintext. Create a
`Secret` first (holding the actual Telegram bot token), then reference it by
id via `telegram_bot_api_key_secret_id`.

### 1.2 Field Descriptions

- **node_name**: Human‑readable name of the Telegram Trigger node.
- **telegram_bot_api_key_secret_id**: ID of the `Secret` holding the API
  token for the Telegram bot that will receive updates. Maps to the model's
  `telegram_bot_api_key_secret` foreign key (`on_delete=SET_NULL`); the
  plaintext token itself is only ever resolved server-side.
- **graph**: ID of the graph this trigger node belongs to.
- **fields**: List of mapping rules that describe how to extract data from
  the incoming Telegram payload into your graph state.
  - **parent**: Root object in the Telegram payload (for example, `message`).
  - **field_name**: Specific field inside the parent (for example, `text`).
  - **variable_path**: Target path in the graph state
    (for example, `variables.telegram_data.user_input`).
- **webhook_trigger**: ID of the related `WebhookTrigger` object. This links the
  Telegram node to a concrete webhook path and (indirectly) to its
  `NgrokWebhookConfig`.

### 1.3 Response Details

On successful creation or update, the API can return:

- **webhook_full_url** (read‑only): The fully qualified webhook URL generated
  automatically when an `NgrokWebhookConfig` is associated with the node.

### 1.4 Inbound Webhook Authentication

Nothing to configure here: registering (or resyncing) the node's webhook
automatically provisions a `WebhookNodeAuth` row that verifies every inbound
Telegram update via the `X-Telegram-Bot-Api-Secret-Token` header. This is
mandatory and entirely internal to how the node registers with Telegram
(via `setWebhook`'s `secret_token` parameter) -- it is not exposed as a
toggle on this endpoint the way it is for generic `WebhookTriggerNode`s. See
the Webhook Developer Guide's "Webhook Inbound Authentication
(`WebhookNodeAuth`)" section for details.

2. Register Webhooks (Global Sync)
----------------------------------

- **Endpoint**: `/api/register-webhooks/`  
- **Method**: `POST`

Use this endpoint to manually trigger a global synchronization of all configured
webhook tunnels via Redis.

### 2.1 Behavior

When a `POST` request is made:

1. All stored `NgrokWebhookConfig` instances are retrieved from the database.
2. Their settings are broadcast over the `REDIS_TUNNEL_CONFIG_CHANNEL`.
3. The FastAPI webhook listener receives these messages and (re)configures the
   active tunnels accordingly.