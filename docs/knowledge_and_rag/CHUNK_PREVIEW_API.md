# Chunk Preview API

Technical documentation for frontend implementation of document chunk preview feature.

## Overview

The Chunk Preview system allows users to test different chunking parameters before indexing. Users can adjust `chunk_size`, `chunk_overlap`, and `chunk_strategy`, then preview the resulting chunks without committing to the final index.

**Key behavior: "Last Request Wins"** - If multiple chunking requests are sent for the same document, only the last request's result is saved. Previous requests are automatically cancelled.

---

## Endpoints

### 1. Trigger Chunking

```
POST /api/naive-rag/{naive_rag_id}/document-configs/{document_config_id}/process-chunking/
```

Triggers document chunking and waits for completion.

#### Request
No body required.

#### Response

| Field | Type | Description |
|-------|------|-------------|
| `chunking_job_id` | string | UUID of this chunking job |
| `naive_rag_id` | int | NaiveRag ID |
| `document_config_id` | int | Document config ID |
| `status` | string | Job status (see below) |
| `chunk_count` | int/null | Number of chunks created |
| `message` | string/null | Error or info message |
| `elapsed_time` | float/null | Processing time in seconds |

#### Response Statuses

| Status | HTTP Code | Description | Action |
|--------|-----------|-------------|--------|
| `completed` | 200 | Chunking finished successfully | Call GET chunks endpoint |
| `cancelled` | 200 | Job was cancelled by newer request | Ignore, newer request will complete |
| `failed` | 500 | Processing error | Show error message to user |
| `timeout` | 202 | Request timed out (50s) | Retry or poll GET endpoint later |

#### Example Response (Success)
```json
{
  "chunking_job_id": "a56ef2e1-612a-4ebb-98c9-b0a6eaf5586c",
  "naive_rag_id": 7,
  "document_config_id": 30,
  "status": "completed",
  "chunk_count": 136,
  "message": null,
  "elapsed_time": 2.345
}
```

#### Example Response (Cancelled)
```json
{
  "chunking_job_id": "6922141c-08ed-40e8-af84-c28d53b12ee3",
  "naive_rag_id": 7,
  "document_config_id": 30,
  "status": "cancelled",
  "chunk_count": null,
  "message": "Job cancelled by newer request",
  "elapsed_time": 1.234
}
```

---

### 2. Get Chunks

```
GET /api/naive-rag/{naive_rag_id}/document-configs/{document_config_id}/chunks/
```

Retrieves chunks for a document config. Returns preview chunks or indexed chunks based on document status.

#### Query Parameters

| Parameter | Type | Default | Max | Description |
|-----------|------|---------|-----|-------------|
| `limit` | int | 50 | 500 | Number of chunks to return |
| `offset` | int | 0 | - | Number of chunks to skip |

#### Response

| Field | Type | Description |
|-------|------|-------------|
| `naive_rag_id` | int | NaiveRag ID |
| `document_config_id` | int | Document config ID |
| `status` | string | Document status |
| `total_chunks` | int | Total number of chunks available |
| `limit` | int | Requested limit |
| `offset` | int | Requested offset |
| `chunks` | array | Array of chunk objects |

#### Chunk Object

| Field | Type | Description |
|-------|------|-------------|
| `preview_chunk_id` / `chunk_id` | int | Chunk ID |
| `text` | string | Chunk content |
| `chunk_index` | int | Position in document (0-based) |
| `token_count` | int/null | Token count (if calculated) |
| `metadata` | object | Additional metadata |
| `created_at` | datetime | Creation timestamp |

#### Example Response
```json
{
  "naive_rag_id": 7,
  "document_config_id": 30,
  "status": "chunked",
  "total_chunks": 136,
  "limit": 50,
  "offset": 0,
  "chunks": [
    {
      "preview_chunk_id": 1,
      "text": "Chapter 1: Introduction...",
      "chunk_index": 0,
      "token_count": 512,
      "metadata": {},
      "created_at": "2024-01-27T10:30:00Z"
    }
  ]
}
```

---

## Document Status Flow

```
new → chunking → chunked → indexing → completed
         ↓          ↓         ↓
       failed     failed    failed
```

| Status | Description | Chunks Available |
|--------|-------------|------------------|
| `new` | No chunking performed | None |
| `chunking` | Chunking in progress | None (wait) |
| `chunked` | Preview chunks ready | Preview chunks |
| `indexing` | Creating embeddings | Preview chunks |
| `completed` | Fully indexed | Indexed chunks |
| `failed` | Error occurred | Depends on when failed |

---

## Frontend Implementation Guide

### Basic Flow

1. User adjusts chunking parameters (size, overlap, strategy)
2. User clicks "Preview Chunks"
3. Frontend calls POST `/process-chunking/`
4. On `status: "completed"` → call GET `/chunks/` with pagination
5. Display chunks with infinite scroll


### When to Fetch Chunks

| Chunking Response Status | Action |
|--------------------------|--------|
| `completed` | Immediately fetch chunks |
| `cancelled` | Do nothing (wait for newer request) |
| `failed` | Show error, do not fetch |
| `timeout` | Show warning, optionally poll later |

---

## Notes

- **Timeout**: Default 50 seconds. Large documents may timeout; chunking continues in background.
- **Concurrent Requests**: Safe to send multiple requests. Only the last one's data is saved.
- **Preview vs Indexed**: GET endpoint automatically returns the correct chunk type based on status.
- **Pagination**: Use `offset` and `limit` for endless scrolling. Max `limit` is 500.
