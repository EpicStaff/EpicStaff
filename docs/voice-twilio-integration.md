# Voice & Twilio Integration

This document covers the end-to-end implementation of voice call handling via Twilio MediaStream and browser WebSocket realtime conversations, including the frontend configuration UI, Django backend API, and the FastAPI realtime audio bridge.

For provider-specific audio routing and adapter internals see [realtime-providers.md](realtime-providers.md).

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Setup & Configuration](#setup--configuration)
4. [Data Model](#data-model)
5. [Django Backend API](#django-backend-api)
6. [FastAPI Realtime Service](#fastapi-realtime-service)
7. [Audio Bridge: VoiceCallService](#audio-bridge-voicecallservice)
8. [RealtimeAgentChatData Contract](#realtimeagentchatdata-contract)
9. [Cache Invalidation Flow](#cache-invalidation-flow)
10. [Troubleshooting](#troubleshooting)
11. [Migration from legacy (VoiceSettings)](#migration-from-legacy-voicesettings)

---

## Overview

The voice feature allows a `RealtimeAgent` to answer inbound phone calls routed through Twilio and to hold live voice conversations in the browser. When a user calls the configured Twilio phone number:

1. Twilio sends a webhook `POST /voice/{channel_token}` to the realtime service.
2. The realtime service returns TwiML directing Twilio to open a MediaStream WebSocket at `/voice/{channel_token}/stream`.
3. `VoiceCallService` bridges g711-ulaw audio between Twilio and the configured AI realtime provider.

Browser conversations follow the same session bootstrap (`POST /init-realtime/` → `connection_key` → `WS /realtime/`) without the Twilio step.

The feature is configured through the **Voice & Channel Settings** section of the application's configure-models dialog. Each channel gets its own Twilio account, phone number, and assigned agent — a deployment can run many channels simultaneously.

> **Status:** Supersedes the legacy global `VoiceSettings` singleton design — see [Migration from legacy](#migration-from-legacy-voicesettings).

---

## Architecture

```
Browser (UI)
  └─ Voice & Channel Settings
       ├─ Channel + Twilio config → Django (realtime-channels/, twilio-channels/)
       └─ Webhook setup          → Django (twilio/configure-webhook/)

Twilio
  └─ Inbound call
       ├─ POST /voice/{token}          → FastAPI (webhook + TwiML response)
       └─ WS   /voice/{token}/stream   → FastAPI (audio bridge)

Browser (chats page)
  └─ POST /init-realtime/ → Django → Redis pub/sub → WS /realtime/

FastAPI (realtime service)
  ├─ /voice/{token}/stream
  │    ├─ Resolves agent from RealtimeChannel via Django API
  │    ├─ Calls init-realtime to create a session
  │    ├─ Polls ConnectionRepository for agent config (via Redis pub/sub)
  │    └─ VoiceCallService: bridges Twilio audio ↔ AI realtime provider
  └─ /realtime/
       └─ ConversationService: browser WebSocket ↔ AI realtime provider

Django
  ├─ GET/POST/PATCH /realtime-channels/  — RealtimeChannel CRUD
  ├─ GET/POST/PATCH /twilio-channels/    — TwilioChannel CRUD
  ├─ GET/POST/PATCH /openai|elevenlabs|gemini-realtime-configs/
  ├─ GET  /twilio/phone-numbers/         — proxy to Twilio REST API
  ├─ POST /twilio/configure-webhook/     — sets VoiceUrl on a Twilio number
  └─ POST /init-realtime/               — creates session, publishes to Redis
```

---

## Setup & Configuration

### Prerequisites

| Requirement | Notes |
|---|---|
| Twilio account | Account SID + Auth Token |
| Twilio phone number | Must support inbound voice |
| ngrok (or other tunnel) | Exposes the realtime service to the public internet |
| Provider config | `OpenAIRealtimeConfig`, `ElevenLabsRealtimeConfig`, or `GeminiRealtimeConfig` with `api_key` and `model_name` |
| `RealtimeAgent` | Must have exactly one provider config FK set |

### Step-by-step

1. **Create a provider config** — in the configure-models UI open the realtime config dialog, pick a provider (OpenAI / ElevenLabs / Gemini), set `api_key` and `model_name`. Saved to `/<provider>-realtime-configs/`.

2. **Attach the config to a `RealtimeAgent`** — set exactly one of `openai_config` / `elevenlabs_config` / `gemini_config` on the `RealtimeAgent`. Also set `voice`, and optionally `wake_word` / `stop_prompt`.

3. **Ensure an ngrok config exists** — with a `domain` (or a running tunnel that provides a `live_url`). Required for Twilio calls to reach the realtime service.

4. **Add a channel** — in the Voice & Channel Settings section click Add Channel: set a name, `channel_type = twilio`, assign the `realtime_agent`, and enter Twilio credentials (`account_sid`, `auth_token_secret_id` referencing a `Secret`, `phone_number`, `webhook_trigger`). The server generates the `token`.

5. **Configure the webhook** — the dialog calls `POST /twilio/configure-webhook/` on save, which sets the Twilio number's `VoiceUrl` to `{tunnel}/voice/{token}`. Can also be set manually in the Twilio console.

6. **Make a call** — dial the Twilio number. Twilio POSTs `POST /voice/{token}` → realtime service returns TwiML → Twilio opens `WS /voice/{token}/stream` → `init-realtime` session → `VoiceCallService` bridges audio to the AI provider. Recordings and end metadata are written back to Django on disconnect.

7. **Browser test** — in the chats page select the agent and connect. The browser path uses `POST /init-realtime/` + `WS /realtime/` without Twilio.

---

## Data Model

Model files:
- `src/django_app/tables/models/webhook_models.py` — `RealtimeChannel`, `TwilioChannel`, `NgrokWebhookConfig`
- `src/django_app/tables/models/realtime_models.py` — provider configs, `RealtimeAgent`, `RealtimeAgentChat`, `ConversationRecording`

### `RealtimeChannel` (`db_table = "realtime_channel"`)

| Field | Type | Description |
|---|---|---|
| `name` | CharField(250) | Display name |
| `channel_type` | CharField(50) choices | `"twilio"` (default). Future: whatsapp, telegram |
| `token` | UUIDField | Auto-generated UUID, unique, not editable. Used in all webhook URLs |
| `realtime_agent` | FK → `RealtimeAgent` | `SET_NULL` nullable. The agent that handles calls on this channel |
| `is_active` | BooleanField | default `True` |

### `TwilioChannel` (`db_table = "twilio_channel"`)

| Field | Type | Description |
|---|---|---|
| `channel` | OneToOneField → `RealtimeChannel` | **Primary key** (`primary_key=True`). `CASCADE`, `related_name="twilio"` |
| `account_sid` | CharField(255) | Twilio account SID |
| `auth_token_secret` | FK → `Secret` | `SET_NULL` nullable. Twilio auth token is no longer stored as plaintext — it's resolved through `Secret` at the point of use (e.g. to validate `X-Twilio-Signature`) |
| `phone_number` | CharField(50) | nullable, `unique=True`, E.164 format e.g. `+15551234567` |
| `webhook_trigger` | FK → `WebhookTrigger` | `SET_NULL` nullable. Replaces the old direct `ngrok_config` FK — the tunnel (ngrok or localhost) now hangs off the shared `WebhookTrigger`, the same model backing generic/Telegram webhook triggers |

`voice_stream_url` is **not** a database field — the frontend computes it as `wss://{ngrok_domain}/voice/{channel.token}/stream` from the ngrok config nested under `channel.twilio.webhook_trigger`.

### `NgrokWebhookConfig`

| Field | Notes |
|---|---|
| `name` | unique |
| `auth_token_secret` | FK → `Secret`, `SET_NULL` nullable — the ngrok dashboard token is no longer a plaintext field |
| `domain` | nullable; static public domain |
| `region` | `us` / `eu` / `ap`, default `eu` |

`get_webhook_url()` returns `https://{domain}`. A runtime `live_url` (running tunnel URL) is resolved by `WebhookTriggerService().get_tunnel_url(...)` and exposed via the read serializer's `ngrok_config: {id, domain, live_url}` expansion.

### Provider config models

**`OpenAIRealtimeConfig`** (`db_table = "openai_realtime_config"`):

| Field | Default |
|---|---|
| `custom_name` | — |
| `api_key` | null |
| `model_name` | `"gpt-realtime-1.5"` |
| `transcription_model_name` | `"whisper-1"` |
| `transcription_api_key` | null |
| `voice_recognition_prompt` | null |

**`ElevenLabsRealtimeConfig`** (`db_table = "elevenlabs_realtime_config"`):

| Field | Default |
|---|---|
| `custom_name` | — |
| `api_key` | null |
| `model_name` | `"eleven_turbo_v2_5"` |
| `language` | null (ISO-639-1, e.g. `en`) |

**`GeminiRealtimeConfig`** (`db_table = "gemini_realtime_config"`):

| Field | Default |
|---|---|
| `custom_name` | — |
| `api_key` | null |
| `model_name` | `"gemini-3.1-flash-live-preview"` |
| `voice_recognition_prompt` | null |

### `RealtimeAgent` (`db_table = "realtime_agent"`)

| Field | Notes |
|---|---|
| `agent` | OneToOneField → `Agent`, `primary_key=True`, `related_name="realtime_agent"` |
| `wake_word` | null; defaults to `agent.role` or `"agent"` on save |
| `stop_prompt` | default `"stop"` |
| `voice` | default `"alloy"` |
| `openai_config` | FK → `OpenAIRealtimeConfig`, nullable |
| `elevenlabs_config` | FK → `ElevenLabsRealtimeConfig`, nullable |
| `gemini_config` | FK → `GeminiRealtimeConfig`, nullable |

**At most one** provider config FK may be set — enforced in `clean()` and `RealtimeAgentWriteSerializer.validate()`. Helpers: `active_provider_config` → returns the non-null config; `provider_name` → `"openai"` / `"elevenlabs"` / `"gemini"` / `None`.

### `RealtimeAgentChat` — session snapshot

Created once per call/conversation; captures the agent's config at session start so later edits don't affect a live call. Key fields: `rt_agent` (FK, SET_NULL), `connection_key` (TextField), `created_at`, `ended_at`, `duration_seconds`, `end_reason` (`completed` / `error` / `cancelled` / `timeout`), `wake_word` / `stop_prompt` / `voice`, `language` / `voice_recognition_prompt`, `input_audio_format` / `output_audio_format` (`pcm16` / `g711_ulaw` / `g711_alaw`, default `pcm16`), and nullable FK snapshots `openai_config` / `elevenlabs_config` / `gemini_config`.

### `ConversationRecording`

| Field | Notes |
|---|---|
| `rt_agent_chat` | FK → `RealtimeAgentChat`, CASCADE |
| `file` | `upload_to="recordings/%Y/%m/%d/"` |
| `recording_type` | `inbound` (user audio) / `outbound` (agent audio) |
| `audio_format` | default `"wav"` |
| `duration_seconds` | nullable |
| `file_size` | nullable |
| `created_at` | auto_now_add |

---

## Django Backend API

Base path: `/api/`. Router in `src/django_app/tables/urls.py`; viewsets in `views/model_view_sets.py`; serializers in `serializers/model_serializers.py`.

### `GET|POST|PATCH|PUT|DELETE /realtime-channels/`

Full `ModelViewSet`. Permission: `IsAuthenticatedOrApiKey`. Queryset: `RealtimeChannel.objects.select_related("twilio")`.

Filterable: `realtime_agent`, `channel_type`, `is_active`, `token`. The `?token=` filter is how the FastAPI service resolves a channel.

Read serializer expands `twilio` inline, which further expands `webhook_trigger` to its nested `WebhookTrigger` representation — `{id, path, provider_type, ngrok_config, localhost_config, live_url}` (see `WebhookTriggerNestedSerializer`).

Example response item:
```json
{
  "id": 12,
  "name": "Support line",
  "channel_type": "twilio",
  "token": "f2c1...uuid",
  "realtime_agent": 7,
  "is_active": true,
  "twilio": {
    "channel": 12,
    "account_sid": "AC...",
    "auth_token_secret_id": 7,
    "phone_number": "+15551234567",
    "webhook_trigger": {
      "id": 5,
      "path": "myvoicebot123",
      "provider_type": "ngrok",
      "ngrok_config": { "name": "prod", "auth_token_secret_id": 9, "domain": "example.ngrok.app", "region": "eu" },
      "localhost_config": null,
      "live_url": "https://example.ngrok.app/webhooks/myvoicebot123"
    }
  }
}
```

Create request: `{ "name", "channel_type": "twilio", "realtime_agent": <id|null>, "is_active": true }`. `token` is server-generated.

---

### `GET|POST|PATCH|PUT|DELETE /twilio-channels/`

Full `ModelViewSet`. PK is `channel` (the `RealtimeChannel` id).

`create()` is an **upsert** — if a `TwilioChannel` already exists for the posted `channel` id, it is updated and returned with `200 OK`.

Request body:
```json
{ "channel": 12, "account_sid": "AC...", "auth_token_secret_id": 7, "phone_number": "+15551234567", "webhook_trigger": 5 }
```

`auth_token_secret_id` (source `auth_token_secret`) points at a pre-existing
`Secret` holding the plaintext Twilio auth token — the token itself is never
accepted or returned as plaintext through this endpoint. Note: the write
serializer (`TwilioChannelSerializer`) expects `webhook_trigger` as a plain
id; the expanded read variant (`_TwilioChannelReadSerializer`, used on
`RealtimeChannel`'s nested `twilio`) returns the full nested
`WebhookTrigger` object shown above (including its `live_url` and nested
`ngrok_config`/`localhost_config`, which still only expose the ngrok token
as an `auth_token_secret_id`, never resolved). Detail routes are keyed by
`channel` id, e.g. `PATCH /twilio-channels/12/`.

---

### Provider config endpoints

| Route | Description |
|---|---|
| `GET\|POST\|PATCH\|DELETE /openai-realtime-configs/` | Full CRUD for `OpenAIRealtimeConfig` |
| `GET\|POST\|PATCH\|DELETE /elevenlabs-realtime-configs/` | Full CRUD for `ElevenLabsRealtimeConfig` |
| `GET\|POST\|PATCH\|DELETE /gemini-realtime-configs/` | Full CRUD for `GeminiRealtimeConfig` |

---

### `GET /twilio/phone-numbers/`

Proxies the Twilio REST API to list incoming phone numbers. Credentials passed via request headers: `X-Twilio-Account-Sid`, `X-Twilio-Auth-Token`.

**Response:**
```json
{ "results": [ { "sid": "PN...", "phone_number": "+15551234567", "friendly_name": "...", "voice_url": "" } ] }
```

`400` if headers are missing; `502` on upstream Twilio error.

---

### `POST /twilio/configure-webhook/`

Sets the Twilio number's `VoiceUrl` to point to the channel's voice webhook.

**Request:**
```json
{ "phone_sid": "PN...", "channel_token": "<uuid>" }
```

Flow:
1. Look up `RealtimeChannel` by `token` (404 if not found, or if it doesn't belong to the active org).
2. Read the channel's Twilio credentials — 400 if `account_sid` is missing or `auth_token_secret_id` is `None`; the plaintext auth token is resolved on demand via `secret_resolver.resolve(...)`.
3. Resolve the tunnel URL via `WebhookTriggerService().get_tunnel_url_for_trigger(webhook_trigger)` (provider-agnostic: works for ngrok or localhost), falling back to `webhook_trigger.get_active_config().get_webhook_url()` (400 if neither is available). `webhook_trigger` here is `TwilioChannel.webhook_trigger`, the same `WebhookTrigger` model backing generic/Telegram triggers — not a direct ngrok FK.
4. Compute `webhook_url = "{tunnel}/voice/{channel_token}"` and POST to Twilio `IncomingPhoneNumbers/{phone_sid}.json` with `VoiceUrl` + `VoiceMethod=POST`.

**Response:** `{ "webhook_url": "..." }`.

---

### `POST /init-realtime/`

Bootstraps a realtime session. Used by both the browser path and the Twilio stream handler. Permission: `IsAuthenticatedOrApiKey`.

**Request:**
```json
{ "agent_id": <int, required>, "config": { ...optional overrides... } }
```

Flow (in `RealtimeService.init_realtime`):
1. Load `RealtimeAgent`, validate an `active_provider_config` exists.
2. Generate `connection_key` (uuid4), persist `RealtimeAgentChat` snapshot.
3. Build `RealtimeAgentChatData` via `ConverterService.convert_rt_agent_chat_to_pydantic()`.
4. Apply any `config` overrides (the Twilio path overrides `input_audio_format` / `output_audio_format` to `g711_ulaw`).
5. Publish JSON to Redis channel `realtime_agents:schema`.

**Response `201`:** `{ "connection_key": "<uuid>" }`.

---

## FastAPI Realtime Service

File: `src/realtime/api/main.py`. Settings: `src/realtime/core/config.py`.

On startup: starts `redis_listener()` and `voice_settings_invalidation_listener()` — both wrapped in `_run_forever()` (2s restart on crash).

`redis_listener()` subscribes to `"realtime_agents:schema"`, deserializes each message into `RealtimeAgentChatData`, stores in `ConnectionRepository` keyed by `connection_key`.

### `POST /voice/{channel_token}` — Twilio webhook

Called by Twilio on an inbound call.

**Security:** Requests are validated using Twilio's `X-Twilio-Signature` header and the auth token resolved from `TwilioChannel.auth_token_secret`. Invalid signature → `403`. No auth token configured → validation skipped with a warning. URL for validation is reconstructed from `x-forwarded-proto` and `x-forwarded-host` headers.

Flow:
1. `get_channel_config(token)` fetches `GET /realtime-channels/?token={token}` from Django (60s cache). No `realtime_agent` in the result → `404`.
2. Computes the MediaStream WS URL from `ngrok.live_url` → `ngrok.domain` → `settings.VOICE_STREAM_URL` (in that order). Missing all → `503`.
3. Mints a single-use `stream_token` (`StreamTokenRepository.mint(bound_key=channel_token)`) and returns TwiML embedding it in a nested `<Parameter>`:
   ```xml
   <?xml version="1.0" encoding="UTF-8"?>
   <Response>
     <Connect>
       <Stream url="{voice_stream_url}">
         <Parameter name="stream_token" value="{stream_token}" />
       </Stream>
     </Connect>
   </Response>
   ```
   (The token is also appended as a `?stream_token=...` query param on the `<Stream url="...">` itself, but that is a harmless, best-effort fallback only — confirmed in production that Twilio does not forward `<Stream>` URL query parameters to the actual Media Stream WebSocket connection.)

### Media Stream WS auth: `stream_token` (`StreamTokenRepository`)

Twilio's Media Stream WebSocket leg carries none of Twilio's verifiable request headers (no `X-Twilio-Signature`), so — unlike the TwiML webhook above — the stream endpoint itself has no way to authenticate the caller from headers alone. This is closed with a short-lived, single-use token instead:

- **Minted** by the paired, signature-validated TwiML webhook handler (`_twilio_voice_webhook`) right before it builds the TwiML response, bound to the channel token (`stream_bound_key`).
- **TTL**: `STREAM_TOKEN_TTL_SECONDS` (`src/realtime/core/config.py`, default `120` seconds).
- **Delivered** to the WS leg via the nested `<Parameter name="stream_token" value="...">` element — Twilio surfaces this inside the first `start` event's `customParameters`, which is why it can only be read *after* the WebSocket handshake, not used to gate `.accept()` itself. A `?stream_token=...` query string is honored only as a fallback (e.g. for direct test tooling), since Twilio does not reliably forward it.
- **Validated** in `_voice_stream_handler` immediately after accepting the socket and reading the first `start` message — `StreamTokenRepository.consume(token, bound_key=channel_token)` atomically checks and invalidates it (single-use, whether or not it's valid) before any Django (`init-realtime`), provider, or audio work happens. Missing/invalid/expired/already-used token → the socket is closed without ever reaching a live media bridge.

This closes what was previously an unauthenticated WebSocket route: before this token existed, any caller who guessed or observed a `channel_token` could open the Media Stream WS directly with no Twilio-side proof of origin.

### `WebSocket /voice/{channel_token}/stream` — Twilio MediaStream bridge

Twilio opens this WebSocket immediately after the TwiML response.

1. Resolve `(agent_id, channel)` from token; close if no agent.
2. Accept the WebSocket, read the first Twilio frames (`connected` → `start`) to capture `streamSid`, then validate `stream_token` as described above — closing the connection here if it's missing, invalid, expired, or already used.
3. **POST `/init-realtime/`** with `{ "agent_id", "config": { "input_audio_format": "g711_ulaw", "output_audio_format": "g711_ulaw" } }` → receives `connection_key`.
4. **Poll `ConnectionRepository`** up to 20× at 0.1s (≈2s) for the `RealtimeAgentChatData` delivered via Redis. Close WS if it never arrives.
5. Instantiate `VoiceCallService` and call `execute()`.

### `WebSocket /realtime/` — browser session

Auth via query params `token` (introspected against Django `/api/auth/introspect/`) and `connection_key`.

- Missing `token` or failed introspection → close `1008`.
- Missing `connection_key` → close `1008`.
- `ConnectionRepository.get_connection(connection_key)` returns `None` → close `1011`.
- Runs `ConversationService.execute()`. For `rt_provider == "elevenlabs"` the chat-mode controller is disabled (ElevenLabs handles VAD internally; StopAgent not supported).

### Per-channel config cache

`get_channel_config(channel_token)` results are cached in `_channel_cache` with **TTL = 60s**. Cache invalidation is push-based: Django publishes a token to `voice_settings:invalidate` and the listener evicts that single entry (or clears all if the message contains no token).

### Relevant settings (`src/realtime/core/config.py`)

| Setting | Purpose |
|---|---|
| `REDIS_HOST` / `REDIS_PORT` / `REDIS_PASSWORD` | Redis connection |
| `REALTIME_AGENTS_SCHEMA_CHANNEL` | `"realtime_agents:schema"` — session snapshot channel |
| `DJANGO_HOST` / `DJANGO_PORT` | derive `DJANGO_API_BASE_URL` |
| `INIT_API_URL` | `{DJANGO_API_BASE_URL}/init-realtime/` |
| `DJANGO_API_KEY` | sent as `X-API-Key` on all Django calls |
| `VOICE_STREAM_URL` | fallback MediaStream URL when no ngrok live URL / domain |

---

## Audio Bridge: VoiceCallService

**File:** `src/realtime/application/voice_call_service.py`

`VoiceCallService` bridges audio between Twilio and the AI realtime provider. It is **provider-agnostic** — all format conversion is handled inside provider adapters.

### Audio Flow

```
Twilio → /voice/{token}/stream (WS)
  │
  │  base64 g711-ulaw chunks (8 kHz)
  │  accumulated until ≥ 2000 bytes (MIN_CHUNK_SIZE)
  │
  ▼
client.send_audio(b64)          ← IRealtimeAgentClient
  │
  │  OpenAI:     pass through (g711_ulaw is native)
  │  ElevenLabs: ulaw → pcm16k inside adapter
  │  Gemini:     ulaw → pcm16k inside adapter
  │
  ▼
AI provider WebSocket

AI provider WebSocket
  │
  │  response.audio.delta event
  │  (adapter pre-converts output to g711_ulaw when is_twilio=True)
  │
  ▼
_send_audio_to_twilio()
  │
  ▼
Twilio MediaStream (base64 g711-ulaw 8 kHz)
```

### Interruption Handling

When the AI provider emits `input_audio_buffer.speech_started` (OpenAI) or `interruption` (ElevenLabs), `_clear_twilio_buffer()` sends a `clear` event to Twilio to stop playback of any buffered TTS audio, preventing the AI speaking over itself.

### Recording on Disconnect

On WebSocket close `VoiceCallService`:
1. Records `end_reason` (`completed` / `cancelled` / `error`).
2. Builds inbound and outbound µ-law WAV files from the accumulated audio buffers (`_build_ulaw_wav`).
3. **POST `/conversation-recordings/`** for each file (with `connection_key`).
4. **POST `/realtime-agent-chats/end/`** with `duration_seconds` and `end_reason`.

### Factory / Provider Flag

`VoiceCallService` calls `factory.create(..., is_twilio=True)`. The `is_twilio=True` flag signals provider adapters to force `g711_ulaw` audio format for both input and output. `VoiceCallService` itself has zero `if provider == "..."` branches.

---

## RealtimeAgentChatData Contract

**File:** `src/shared/models/agents.py`

This Pydantic model is the **single payload** that crosses the Django → Redis → realtime service boundary. It is imported by both Django (`RedisService.publish_realtime_agent_chat`) and the realtime service (`redis_listener`, `ConnectionRepository`, `ConversationService`, `VoiceCallService`).

Because the same module is imported on both ends, the schema cannot drift silently — but adding a **required** field on one consumer without updating the model breaks Pydantic deserialization in the Redis listener, logged as `Error processing embedding:`.

Key fields and failure modes:

| Field | Source | What breaks if wrong |
|---|---|---|
| `connection_key` | `RealtimeAgentChat.connection_key` | Session never starts — browser closes `1011`; Twilio stream drops after ~2s poll |
| `rt_provider` (`openai`/`elevenlabs`/`gemini`) | active config FK via converter | Wrong adapter; ElevenLabs branch disables StopAgent |
| `rt_model_name` (required) | active config `model_name` | Pydantic validation fails → snapshot never saved |
| `rt_api_key` (required) | active config `api_key` | Pydantic validation fails **or** provider auth error |
| `input_audio_format` / `output_audio_format` | snapshot; overridden to `g711_ulaw` on Twilio path | Non-`g711_ulaw` on Twilio → garbled audio |
| `voice` | snapshot | Unsupported voice → provider error or silent fallback |
| `wake_word` / `stop_prompt` | snapshot | StopAgent / LISTEN wake-word never fires |
| `language` | ElevenLabs only | ElevenLabs language selection broken |
| `tools` | `_get_agent_base_tools` | Tool not registered → "not found" at call time |

---

## Cache Invalidation Flow

```
User saves channel settings in UI
  │
  ▼
PATCH /realtime-channels/ or /twilio-channels/ (Django)
  │
  ├─ Saves to DB
  └─ (optional) redis_client.publish("voice_settings:invalidate", "<token>")
         │
         ▼
  voice_settings_invalidation_listener (FastAPI)
  │  if data contains a token → evict that single entry from _channel_cache
  │  if data is empty          → clear entire _channel_cache
         │
         ▼
  next call to /voice/{token} or /voice/{token}/stream
  fetches fresh channel config from Django
```

Note: the current channel write path relies on the **60s TTL** expiry unless a token is explicitly published on `voice_settings:invalidate`. The legacy `VoiceSettingsView.update()` still publishes to the same channel (without a token, clearing the full cache) on every settings save.

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Call returns 404 at `/voice/{token}` | Channel has no `realtime_agent` assigned, or token is wrong. Check `GET /realtime-channels/?token=...` |
| 403 Invalid Twilio signature | The `Secret` referenced by `TwilioChannel.auth_token_secret` doesn't match the Twilio account's actual auth token; or the URL reconstructed from `x-forwarded-proto` / `x-forwarded-host` differs from what Twilio signed. Verify the proxy forwards those headers and the `VoiceUrl` in Twilio matches exactly |
| 503 "No voice stream URL configured" | No ngrok `live_url` / `domain` and no `VOICE_STREAM_URL` fallback. Start the tunnel or set a domain on the ngrok config |
| Stream connects then drops after ~2s | `VoiceCallService` polled `ConnectionRepository` and never found the snapshot. Check that `redis_listener` is running (`redis_listener: connected to Redis` on startup), and that `init-realtime` succeeded. The agent must have a provider config |
| Stream WS closes immediately after `start` | `stream_token` missing/invalid/expired/already consumed. TTL is only `STREAM_TOKEN_TTL_SECONDS` (120s default) — a long delay between the TwiML response and Twilio opening the Media Stream WS, or a retried/duplicated call to the TwiML webhook, can exhaust it before the stream connects |
| `init-realtime` returns 400 | `RealtimeAgent` has no `active_provider_config`, or `agent_id` is invalid |
| Garbled phone audio | `input_audio_format` / `output_audio_format` not `g711_ulaw` on the Twilio path. The stream handler forces these via the `init-realtime` `config` override |
| Stale channel after edit | Per-channel cache has 60s TTL. Restart the service, wait it out, or publish the channel token on `voice_settings:invalidate` to evict that single entry |
| Pydantic error in `redis_listener` | A required `RealtimeAgentChatData` field (`rt_model_name`, `rt_api_key`) was null. Ensure the provider config has both set |
| Recordings or end metadata missing | `VoiceCallService` POSTs with `connection_key`; a missing `RealtimeAgentChat` row returns 404 and the recording is dropped. Confirm the chat row exists |
| Phone numbers not loading in dialog | `account_sid` and `auth_token` must both be present. Numbers are fetched lazily — open the dropdown to trigger. Cache resets when credentials change |
| Browser WS closes with `1011` | `connection_key` not found in `ConnectionRepository` — Redis snapshot never arrived. Check Redis connectivity and that `init-realtime` returned `201` before opening the WS |

---

## Migration from legacy (`VoiceSettings`)

The deprecated singleton `VoiceSettings` (`db_table = "voice_settings"`, fields `twilio_account_sid`, `twilio_auth_token`, `voice_agent`, `ngrok_config`) and its tokenless routes — Django `GET/PUT /voice-settings/` and FastAPI `POST /voice` + `WS /voice/stream` — remain in the codebase for backward compatibility only. They are explicitly marked **DEPRECATED** in `webhook_models.py`.

They support a single global Twilio account/agent. Do not build new integrations on them.

**The only live cross-over:** `VoiceSettingsView.update()` still publishes an empty payload to `voice_settings:invalidate`, which clears the entire `_channel_cache` in the realtime service as a side effect.

**Migrate by:** creating a `RealtimeChannel` + `TwilioChannel` per phone number (see [Setup & Configuration](#setup--configuration)) and pointing each Twilio number's `VoiceUrl` at `/voice/{token}` instead of `/voice`. The old singleton can then be ignored.
