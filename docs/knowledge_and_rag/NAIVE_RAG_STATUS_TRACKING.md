# NaiveRag Document Status Tracking

> **Branch:** `feature/EST-1682-knowledge-statuses` | **Base:** `main`
> **Scope:** backend (Django `tables`, `knowledge` service, `src/shared`); UI is a consumer only.

---

## 0. Why This Exists

Previously, the `NaiveRag` object had a single aggregate status (`new / processing / completed / failed`) with no visibility into which specific documents failed or why. A single bad document (e.g. a file with an unsupported format or a temporary embedder rate-limit) would silently drag the entire RAG into `failed`, giving no actionable feedback.

This feature adds per-document status lifecycle, structured error codes, snapshot-based idempotency, and targeted re-indexing so operators and agents can:
- See exactly which document failed and with what error.
- Retry only the failed documents without re-indexing the already-completed ones.
- Skip re-indexing altogether when chunk parameters haven't changed since the last successful run.

---

## 1. Document Status Lifecycle

Each `NaiveRagDocumentConfig` now has its own `status` field following this flow:

```
new ──► chunking ──► chunked ──► indexing ──► completed
         │                         │
         └──────────────► failed ◄─┘
                          warning
```

| Status      | Meaning |
|-------------|---------|
| `new`       | Document registered, not yet processed. |
| `chunking`  | Chunk-preview worker is running. |
| `chunked`   | Preview chunks created; no active worker. User may tune parameters. |
| `indexing`  | Embedding worker is running. |
| `completed` | Chunks and embeddings exist in the vector store. |
| `failed`    | An unrecoverable error occurred; `error_code` and `error_message` are set. |
| `warning`   | Aggregate RAG-level only; individual documents are `failed` or `completed` in mixed states. |

The aggregate `NaiveRag.rag_status` is derived automatically from all per-document statuses via [`compute_rag_status()`](../../src/shared/models/knowledge_status.py#L77).

---

## 2. New Fields on `NaiveRagDocumentConfig`

Defined in [`tables/models/knowledge_models/naive_rag_models.py`](../../src/django_app/tables/models/knowledge_models/naive_rag_models.py#L163):

| Field | Type | Purpose |
|-------|------|---------|
| `error_code` | `CharField` (choices) | Categorical error code (see §3). Default: `none`. |
| `error_message` | `TextField` | Human-readable truncated error message (max 2 000 chars). |
| `failed_at` | `DateTimeField` | Timestamp of the failure. |
| `indexed_chunk_strategy` | `CharField` | Snapshot of `chunk_strategy` at last successful index. |
| `indexed_chunk_size` | `PositiveIntegerField` | Snapshot of `chunk_size` at last successful index. |
| `indexed_chunk_overlap` | `PositiveIntegerField` | Snapshot of `chunk_overlap` at last successful index. |
| `indexed_additional_params` | `JSONField` | Snapshot of `additional_params` at last successful index. |

Snapshot fields are `null` until the first successful indexing run. They are compared against the live parameters to decide whether re-indexing is actually needed (see §5).

---

## 3. Error Codes

Defined as `DocumentErrorCode` in [`src/shared/models/knowledge_status.py`](../../src/shared/models/knowledge_status.py#L37) (shared between Django and the knowledge worker):

| Code | Meaning |
|------|---------|
| `none` | No error (default / cleared on recovery). |
| `chunking_failed` | Document could not be split into chunks. |
| `embedding_failed` | Embedding API returned an error. |
| `embedder_auth` | Embedder authentication failed (invalid API key). |
| `embedder_rate_limit` | Embedder rate-limit hit. |
| `unknown` | Unexpected error that does not fit any specific category. |

Classification is done by [`IndexingErrorClassifier`](../../src/knowledge/utils/indexing_error_classifier.py) in the knowledge worker. It returns a `(error_code, message)` tuple and is called from the two error paths in [`naive_rag_strategy.py`](../../src/knowledge/rag/naive_rag_strategy.py).

---

## 4. Shared Status Rules (`src/shared/`)

All status-derivation logic lives in [`src/shared/models/knowledge_status.py`](../../src/shared/models/knowledge_status.py) and is imported by **both** `django_app` and the `knowledge` worker — the single source of truth.

### `compute_rag_status(doc_statuses)`
Rolls a list of per-document status strings up to a single `RagStatus` string (first match wins):
1. Empty or all `new` → `new`
2. Any in `{chunking, chunked, indexing}` → `processing`
3. All `completed` → `completed`
4. All `failed` → `failed`
5. Mixed → `warning`

### `summarize_rag_error(doc_statuses)`
Returns a short human-readable summary (e.g. `"2 of 5 document(s) failed or produced warnings."`) when at least one document is `failed`/`warning`, or `None` otherwise.

### `is_snapshot_current(live, indexed)`
Returns `True` iff every chunk param field has a non-null indexed snapshot equal to the current live value. Used for idempotency (§5).

### `format_error_message(exc)`
Extracts the most useful human-readable message from an exception:
- For provider errors (OpenAI-style `APIError`): extracts `exc.body["message"]`.
- For DB errors: prefers `exc.orig` to avoid leaking SQL + bound params into logs.
- Fallback: `"TypeName: str(exc)"`.
- Always truncated to `ERROR_MESSAGE_MAX_LENGTH = 2000` characters.

### `AGGREGATION_IN_PROGRESS` vs `RACE_GUARD_IN_PROGRESS`
Two related frozensets with a deliberate difference:

| Set | Contains | Purpose |
|-----|----------|---------|
| `AGGREGATION_IN_PROGRESS` | `chunking, chunked, indexing` | Used by `compute_rag_status` to roll up to `processing`. `chunked` is included because preview-only state still means "in progress" from the user's perspective. |
| `RACE_GUARD_IN_PROGRESS` | `chunking, indexing` | Used by `apply_param_updates()` to refuse status realignment while an active worker is running. `chunked` is intentionally **excluded** — no worker is active, so params can be freely changed. |

---

## 5. Snapshot-Based Idempotency

When `POST /api/index-rag/` is called, [`IndexingService._prepare_naive_rag_indexing()`](../../src/django_app/tables/services/knowledge_services/indexing_service.py#L65) partitions each document config into three groups:

| Group | Condition | Action |
|-------|-----------|--------|
| `accepted` | Live params differ from snapshot (or snapshot is null). | Bulk-updated to `indexing`; sent to the worker. |
| `skipped_completed` | Snapshot already matches live params. | Flipped to `completed` locally; no worker dispatch. |
| `skipped_in_progress` | A worker is already running (`chunking` or `indexing`). | Left untouched. |

The response includes all three lists so the caller can show accurate feedback without an extra status poll.

---

## 6. Targeted Re-indexing

The indexing endpoint now accepts an optional `document_config_ids` list in the request body:

```json
POST /api/index-rag/
{
  "rag_id": 42,
  "rag_type": "naive",
  "document_config_ids": [101, 205]   // optional; omit to index all
}
```

When provided, only those specific configs are considered. The same three-group partition (accepted / skipped_completed / skipped_in_progress) still applies within the subset.

---

## 7. Chunk Parameter Validation

`NaiveRagDocumentConfigValidator` (in [`tables/validators/chunk_parameter_validator.py`](../../src/django_app/tables/validators/chunk_parameter_validator.py)) is the single source of chunk-parameter validation rules, shared between:
- The single-document update endpoint (calls `validate_or_raise`).
- The bulk-update endpoint (calls `collect_errors`, aggregates per-config).

### Constraints
| Param | Limit |
|-------|-------|
| `chunk_size` | 20 – 8 000 |
| `chunk_overlap` | 0 – 1 000 |
| Cross-field | `chunk_overlap < chunk_size` |

### Strategy ↔ File-Type Rules
| Strategy | Allowed for |
|----------|-------------|
| `token`, `character` | All file types |
| `json` | `.json` only |
| `markdown` | `.md` only |
| `html` | `.html` only |
| `csv` | `.csv` only |

---

## 8. Model Methods (`NaiveRagDocumentConfig`)

| Method | What it does |
|--------|-------------|
| `is_snapshot_current()` | Returns `True` iff all four snapshot fields match live params. |
| `apply_param_updates(updates)` | Mutates params in-memory; if a worker is not running, realigns status to `completed` (snapshot matches) or `new` (snapshot differs). Returns `True` if anything changed. |
| `start_attempt(new_status)` | Flips status and clears stale error fields (in-memory; caller persists). |
| `mark_completed(processed_at)` | Sets `completed`, clears error fields. |
| `mark_failed(error_code, exc)` | Sets `failed`, stores code/message/timestamp, returns the formatted message. |

---

## 9. Service Methods (`NaiveRagService`)

| Method | What it does |
|--------|-------------|
| `begin_attempt(config, new_status)` | Calls `start_attempt` + saves `status, error_message, error_code, failed_at`. |
| `mark_config_failed_and_get_message(config, error_code, exc)` | Calls `mark_failed` + saves failure fields; returns the message for surfacing to the caller. |
| `_persist_param_updates(config)` | Drops stale preview chunks and saves the config after `apply_param_updates` returned `True`. |

---

## 10. Data Flow: Indexing a Document

```
POST /api/index-rag/
    │
    ▼
IndexingService.validate_and_prepare_indexing()
    │  partition: accepted / skipped_completed / skipped_in_progress
    │  bulk-update accepted → INDEXING
    ▼
Redis publish  (channel: NAIVE_RAG_PROCESS_INDEXING)
    │
    ▼  (knowledge worker)
naive_rag_strategy.process_rag_indexing()
    │  for each accepted config_id:
    │    acquire per-doc lock
    │    _already_indexed? → skip
    │    _chunk_and_embed_doc()
    │      on chunk error → IndexingErrorClassifier.for_chunking()
    │                       NaiveRagService.mark_config_failed_and_get_message()
    │      on embed error → IndexingErrorClassifier.for_embedding()
    │                       _persist_doc_failure()
    │    on success → update_naive_rag_status()
    │                  write snapshot fields + COMPLETED
    ▼
update_naive_rag_status()
    │  compute_rag_status(all doc statuses) → NaiveRag.rag_status
    │  summarize_rag_error()               → NaiveRag.error_message
    ▼
Redis publish  (channel: NAIVE_RAG_STATUS_UPDATE)
    │
    ▼  (django_app listener)
SSE → client
```

---

## 11. Document Download & Preview

New endpoints in `naive_rag_views.py` let clients download or preview individual source documents:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/collections/{id}/documents/{doc_id}/download/` | GET | Download as attachment (original file). |
| `/api/collections/{id}/documents/{doc_id}/preview/` | GET | Serve inline (for supported types: PDF, TXT, CSV, JSON, HTML, MD, DOCX). |
| `/api/collections/{id}/documents/archive/` | GET | Download multiple documents as a ZIP archive. |

Serving logic is centralised in [`tables/utils/document_serving.py`](../../src/django_app/tables/utils/document_serving.py). Previewable MIME types are declared once in `PREVIEW_CONTENT_TYPES` in [`knowledge_constants.py`](../../src/django_app/tables/constants/knowledge_constants.py#L9).

---

## 12. API Response Changes

`GET /api/naive-rag/{id}/configs/` now includes error fields per document config:

```json
{
  "naive_rag_document_id": 101,
  "status": "failed",
  "error_code": "embedding_failed",
  "error_message": "AuthenticationError: Incorrect API key …",
  "failed_at": "2026-06-19T10:23:45Z",
  "indexed_chunk_strategy": null,
  "indexed_chunk_size": null,
  "indexed_chunk_overlap": null,
  "indexed_additional_params": null
}
```

When re-indexing succeeds, `error_code` resets to `none` and `error_message` / `failed_at` clear to `null`. Snapshot fields populate on first successful index and update on each subsequent successful run.
