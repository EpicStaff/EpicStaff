# Quickstart API

Quickstart is a one-call setup that creates all required model configs for a given provider. It is designed to get a new installation working immediately without manually configuring individual models.

---

## Table of Contents

1. [Overview](#overview)
2. [Supported Providers](#supported-providers)
3. [What Quickstart Creates](#what-quickstart-creates)
4. [Endpoints](#endpoints)
   - [GET /api/quickstart/](#get-apiquickstart)
   - [POST /api/quickstart/](#post-apiquickstart)
   - [POST /api/quickstart/apply/](#post-apiquickstartapply)
5. [Typical Workflow](#typical-workflow)
6. [The `quickstart:latest` Tag](#the-quickstartlatest-tag)
7. [Running Quickstart Multiple Times](#running-quickstart-multiple-times)

---

## Overview

Quickstart works in two steps:

1. **Create configs** — `POST /api/quickstart/` creates LLM, embedding, realtime, and transcription configs for the chosen provider using the provided API key.
2. **Apply configs** — `POST /api/quickstart/apply/` sets those configs as the active defaults used by agents, memory, voice, and transcription.

These are intentionally separate actions so you can review what was created before activating it.

---

## Supported Providers

| Provider | LLM Model | Embedding Model | Voice (realtime / transcription) | System One |
|----------|-----------|-----------------|----------------------------------|------------|
| `openai` | gpt-6-luna | text-embedding-3-small | gpt-realtime-1.5 / whisper-1 | gpt-6-luna |
| `gemini` | gemini-3.8-flash | gemini-embedding-001 | gemini-3.1-flash-live-preview / — | — |
| `cohere` | command-a-03-2025 | embed-english-v3.0 | — | — |
| `mistral` | mistral-large-latest | mistral-embed | — | — |

The models are set in `QuickstartService.PROVIDER_CONFIGS` (`src/django_app/tables/services/quickstart_service.py`); the voice models are the defaults of `OpenAIRealtimeConfig` / `GeminiRealtimeConfig`. Each LLM and embedding config starts with the model's catalog defaults, with two exceptions:

- **OpenAI LLM:** `reasoning_effort: low` and `max_tokens: 100000`. gpt-6-luna's reasoning tokens count against `max_tokens`, so the default 4096 can cut a long agent step short.
- **Gemini embedding:** `dimensions: 1536`, the size the GraphRAG vector store in `knowledge_new` holds (the model returns 3072 by default).

---

## What Quickstart Creates

For each run, quickstart creates the following configs in the database:

- **LLMConfig** — used by agents and memory LLM
- **EmbeddingConfig** — used by memory embedding
- **OpenAIRealtimeConfig** — voice, with whisper-1 for transcription (OpenAI only)
- **GeminiRealtimeConfig** — voice (Gemini only)
- **SystemOneConfig** — System One decisions (OpenAI only)

All configs share one secret holding the API key. The LLM and embedding configs receive the predefined tag `quickstart:latest`, which is automatically moved to the newest config on every subsequent quickstart run.

---

## Endpoints

### GET /api/quickstart/

Returns the current quickstart status: supported providers, the last created quickstart config, and whether it is applied to the system defaults.

**Request:** no body required.

**Response:**

```json
{
  "supported_providers": ["openai", "gemini", "cohere", "mistral"],
  "last_config": {
    "config_name": "quickstart_openai",
    "llm_config": { "id": 1, "custom_name": "quickstart_openai", ... },
    "embedding_config": { "id": 1, "custom_name": "quickstart_openai", ... },
    "realtime_config": { "id": 1, "custom_name": "quickstart_openai", ... },
    "realtime_transcription_config": { "id": 1, "custom_name": "quickstart_openai", ... }
  },
  "is_synced": false
}
```

**`last_config`** is `null` if quickstart has never been run.

**`is_synced`** is `true` when all system defaults (DefaultModels) currently point to the configs carrying the `quickstart:latest` tag. It becomes `false` again if you run quickstart again without applying, or if the defaults are changed manually.

---

### POST /api/quickstart/

Creates configs for the given provider and API key. Does **not** apply them to the system defaults automatically.

**Request:**

```json
{
  "provider": "openai",
  "api_key": "sk-..."
}
```

**Response `200 OK`:**

```json
{
  "config_name": "quickstart_openai",
  "configs": {
    "llm_config": { "id": 1, "custom_name": "quickstart_openai", ... },
    "embedding_config": { "id": 1, "custom_name": "quickstart_openai", ... },
    "realtime_config": { "id": 1, "custom_name": "quickstart_openai", ... },
    "realtime_transcription_config": { "id": 1, "custom_name": "quickstart_openai", ... }
  }
}
```

**Response `400 Bad Request`** — if the provider is not in the supported list:

```json
{
  "provider": ["Provider 'xyz' does not exist."]
}
```

**Notes:**
- Quickstart attaches the key to the provider's built-in catalog model when one exists, and otherwise to the organization's own model of the same name. Its configs have an empty `connection`, so the key goes to the provider's own endpoint. An organization's own model row is locked until quickstart commits, so a concurrent rename of that model cannot redirect the key.
- Instead of `api_key`, the body may carry `api_key_secret_id` to reuse an existing secret. Referencing a secret this way needs the `Use` permission on Secrets (a plain `api_key` does not); without it the response is a `400` whose `message` names `api_key_secret_id`.
- After this call, `GET /api/quickstart/` will show `is_synced: false` until apply is called.
- Each call creates a new set of configs with a unique name (see [Running Quickstart Multiple Times](#running-quickstart-multiple-times)).

---

### POST /api/quickstart/apply/

Applies the current quickstart configs (the ones tagged `quickstart:latest`) to the system defaults. No body is required.

This sets the following fields on `DefaultModels`:

| DefaultModels field | Set to |
|---|---|
| `agent_llm_config` | LLMConfig with `quickstart:latest` |
| `agent_fcm_llm_config` | LLMConfig with `quickstart:latest` |
| `project_manager_llm_config` | LLMConfig with `quickstart:latest` |
| `memory_llm_config` | LLMConfig with `quickstart:latest` |
| `memory_embedding_config` | EmbeddingConfig with `quickstart:latest` |
| `voice_llm_config` | RealtimeConfig with `quickstart:latest` |
| `transcription_llm_config` | RealtimeTranscriptionConfig with `quickstart:latest` |

**Request:** no body required (or empty `{}`).

**Response `200 OK`** — the updated DefaultModels object:

```json
{
  "agent_llm_config": { "id": 1, ... },
  "agent_fcm_llm_config": { "id": 1, ... },
  "project_manager_llm_config": { "id": 1, ... },
  "memory_llm_config": { "id": 1, ... },
  "memory_embedding_config": { "id": 1, ... },
  "voice_llm_config": { "id": 1, ... },
  "transcription_llm_config": { "id": 1, ... }
}
```

**Response `404 Not Found`** — if quickstart has never been run:

```json
{
  "detail": "No quickstart config found. Run POST /quickstart/ first."
}
```

After a successful apply, `GET /api/quickstart/` will return `is_synced: true`.

---

## Typical Workflow

### First-time setup

```
POST /api/quickstart/   { "provider": "openai", "api_key": "sk-..." }
POST /api/quickstart/apply/
```

Check status:

```
GET /api/quickstart/    →  is_synced: true
```

### Update API key or re-run quickstart

```
POST /api/quickstart/   { "provider": "openai", "api_key": "sk-new-key" }
```

At this point `is_synced` becomes `false` — the new configs exist but are not applied yet.

```
GET /api/quickstart/    →  is_synced: false
POST /api/quickstart/apply/
GET /api/quickstart/    →  is_synced: true
```

---

## The `quickstart:latest` Tag

Every time `POST /api/quickstart/` runs, a predefined tag `quickstart:latest` is moved to the newly created configs. This tag:

- Is predefined — it cannot be added or removed manually via the tags API.
- Always sits on exactly one set of configs at a time (the most recent quickstart run).
- Is used by `POST /api/quickstart/apply/` to find which configs to activate.
- Is used by `GET /api/quickstart/` to populate `last_config` and compute `is_synced`.

---

## Running Quickstart Multiple Times

Each call to `POST /api/quickstart/` creates a **new** set of configs with a unique name:

| Run | Config name |
|-----|------------|
| 1st | `quickstart_openai` |
| 2nd | `quickstart_openai_1` |
| 3rd | `quickstart_openai_2` |

Old configs are not deleted — they remain in the database and can be used independently. Only the `quickstart:latest` tag moves to the newest one.
