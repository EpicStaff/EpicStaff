🚀 Webhook User Guide
This guide explains how to use Webhook Triggers to start your graphs from
external applications or services.

How to Set Up Your Webhook
--------------------------
The process involves two main steps:

1. In the Graph Editor: Add and configure the `WebhookTriggerNode` and select
   your desired Tunnel Configuration (for example, an Ngrok domain/token).
2. In your external service: Get the public URL and send data to it.

Step 1: Add and Configure the WebhookTriggerNode
------------------------------------------------
1. Open the graph you want to trigger.
2. From the node menu, find and drag a `WebhookTriggerNode` onto your canvas.
3. Link your Tunnel Configuration:
   - Choose an existing Ngrok configuration (with your specific domain and
     auth token) to associate with this webhook.
4. Set the node as the entrypoint for your graph.
5. Select the node to configure its built‑in Python code (if applicable).
6. Connect the `WebhookTriggerNode` to the next node in your workflow.

Step 2: Get Your Public Webhook URL
-----------------------------------
The webhook service generates a unique public URL dynamically based on the
Ngrok configuration you linked.

1. **Find your Base URL**  
   - Because the system supports multiple tunnels concurrently, your Base URL
     corresponds to the domain configured in your selected Ngrok configuration  
     (for example, `https://your-custom-domain.ngrok.app`).

2. **Find your Path**  
   - Requests are routed by `WebhookTrigger.path`, not by the node's numeric
     ID -- there is no trigger/node ID anywhere in the URL. The path is a
     string you assign when creating the webhook trigger, and it doubles as
     your only routing secret: it's intentionally unguessable, and should be
     treated the same way you'd treat a Stripe or GitHub webhook URL (don't
     share it or log it anywhere public).
   - You can find the current path -- and the full ready-to-use address, as
     `live_url` -- on the node's webhook trigger details in the graph editor
     or via the API.

3. **Combine them**  
   - Your final public webhook URL has the format:  
     `[Base URL]/webhooks/[path]/`

Step 3: Send Data to the URL
----------------------------
You can now configure your external service to send an HTTP `POST` request with
a JSON body to your final URL.

Example:

```http
POST https://your-custom-domain.ngrok.app/webhooks/x7k2mQ9vLp3z/
Content-Type: application/json

{
  "example": "payload",
  "any": "data your graph expects"
}
```

Inbound Request Authentication
-------------------------------
By default, requests to your webhook URL must be authenticated:

- **Generic webhook triggers** (`WebhookTriggerNode`) require a secret set at
  the trigger level: create a `Secret` (at least 32 characters) and point
  the webhook trigger's `auth_secret_id` at it with `auth_kind: "webhook"`
  via `/api/webhook-triggers/`. Your sending system must then send that
  secret back on every request as an `EPICSTAFF_API_KEY` header. This is
  mandatory -- there is no way to disable auth for a trigger; every trigger
  either has a configured secret or requests to it are rejected with `401`.
  See the Developer Guide's "Webhook Inbound Authentication" section for
  details.
- **Telegram triggers** are always auth-protected automatically, with
  nothing for you to configure -- the secret-token exchange happens entirely
  between this platform and Telegram when the bot's webhook is registered.