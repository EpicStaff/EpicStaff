# `knowledge_new` — Contributor Manual

Guide for backend developers about to change code in the `knowledge_new` service
(`src/knowledge_new/`). It answers three questions: **where does my code go**,
**what contracts must I honour**, and **how do I run and test it**.

It does *not* restate the general backend rules — Pydantic v2, loguru, Ruff,
async I/O — those live in [`docs/backend-conventions.md`](../backend-conventions.md).
When something here disagrees with a value in the code, the code wins; tell us so
we can fix the doc.

---

## 0. How to read this

- **New to the team / to hexagonal architecture:** read everything, start with §2.
- **Experienced, new to this service:** skip §2; jump to the layer map (§3),
  the ports (§4) and the recipes (§5). Skim §7 for the non-obvious traps.
- **Everyone, before your first PR:** §6 (run & test) and §7 (gotchas).

---

## 1. What this service owns

`knowledge_new` is the RAG (retrieval-augmented generation) service. It owns the
lifecycle of a knowledge collection:

```
ingest file → extract text → chunk → embed → index → search
```

It exposes an HTTP API (Litestar, uvicorn, port `8100`) and persists to Postgres
(SQLAlchemy async), MinIO/S3 (object storage) and LanceDB (vectors, for graph
RAG). It is driven by the Django `django_app` service over HTTP, not directly by
users.

It does **not** own: the flow editor, agent orchestration, LLM provider config,
or the document upload UI. It receives a `rag_id` + `document_id` and API keys,
and does the RAG work.

### Two strategies, asymmetric capabilities

Every endpoint is parameterised by a `RAGStrategy` (`naive` | `graph`). The two
strategies deliberately support **different** operations:

| Operation | `naive` | `graph` |
|-----------|:-------:|:-------:|
| prechunk  | ✅ | — |
| index     | ✅ | ✅ |
| search    | ✅ | ✅ |
| remove    | — | ✅ |
| metrics   | — | ✅ |

An unsupported combination raises `UnsupportedError` → HTTP 400. This asymmetry
is encoded in the per-operation factory registries (§5.1) — if a registry has no
entry for a strategy, that operation is unsupported for it *by design*.

### Request flow (index a document)

```
POST /rags/{strategy}/{rag_id}/index/
  → RagController.index                     (presentation/rest/controllers/rag.py)
  → build RunIndex command                  (application/commands.py)
  → build_indexer(strategy, uow)            (application/orchestrators/indexing/factory.py)
  → orchestrator.execute(command)           (application/orchestrators/base.py)
      → repositories via uow                (infrastructure/database/…)
      → MinIO / LanceDB / GraphRAG          (infrastructure/graphrag/…)
```

Everything flows inward through a port and back out through an adapter. Keep it
that way.

---

## 2. Architecture primer (skip if you know hexagons)

The service is a **hexagon** (ports & adapters). One rule governs everything:

> **Dependencies point inward.** `domain` depends on nothing. `application`
> depends on `domain`. `infrastructure` and `presentation` depend on
> `application` and `domain` — never the reverse.

Why we bother:

- The domain (business rules) is testable with no database, no MinIO, no HTTP.
- Adapters (Postgres, MinIO, a specific embedder) are swappable without touching
  business logic.
- A "port" is an abstract interface owned by the *inside*; an "adapter" is a
  concrete implementation living on the *outside*. The inside declares what it
  needs; the outside provides it, wired together in `bootstrap/`.

That is the whole idea. The rest of this doc is where each piece lives and how to
add one.

---

## 3. Layer map — where does my code go?

| Layer | Dir | Lives here | Must **not** contain |
|-------|-----|------------|----------------------|
| **Domain** | `domain/` | Entities (`Rag`, `Document`), value objects, enums, domain errors, repository **ports** | Any import of SQLAlchemy, Litestar, MinIO, graphrag |
| **Application** | `application/` | Use-case orchestrators, capability **ports** (chunker, embedder, …), commands & results | Concrete DB/HTTP/storage code |
| **Infrastructure** | `infrastructure/` | Adapters: SQLAlchemy repos + UoW, graphrag storages/vector-stores, naive chunkers/embedders, file extractors, task register | Business rules / use-case logic |
| **Presentation** | `presentation/rest/` | Litestar controllers, request/response schemas, error handlers | Business logic (controllers stay thin) |
| **Bootstrap** | `bootstrap/` | DI wiring (`di.py`), lifespans (`lifespans.py`) | Anything reusable — it's the composition root |
| **Common** | `common/` | Small cross-layer helpers with no layer identity | Domain rules or adapters |

Rule of thumb: if you're importing `sqlalchemy`, `litestar`, `miniopy_async`, or
`graphrag`, you're in `infrastructure` or `presentation` — never in `domain` or
`application`.

---

## 4. The ports — the seams you plug into

Ports are abstract classes. To extend the service you implement a port and
register the adapter. There are two families.

### Repository ports (`domain/ports/repositories.py`)

Owned by the domain; implemented by SQLAlchemy in `infrastructure/database/`.

- **`AbstractNaiveRagRepository`** — vector-similarity RAG persistence.
  Key methods: `get_rag`, `update_rag`, `get_embedding_config`, `get_document(s)`,
  `save_preview_chunks`, `save_indexed_chunks`, `update_document`,
  `search_chunks(rag_id, vector, limit, similarity_threshold)`,
  `get_document_content(rag_id, document_id) -> tuple[bytes, FileExtensionEnum]`.
- **`AbstractGraphRagRepository`** — graph RAG persistence.
  Key methods: `get_rag`, `update_rag`, `get_documents`,
  `get_indexed_documents_excluding`, `get_config(rag_id, slot) -> GraphRagConfig`,
  `update_status_of_documents`, `remove_rag`.

All methods are `async`.

### Capability ports (`application/ports/`)

Owned by the application layer; implemented by adapters in `infrastructure/`.
Each follows the **template-method** convention: a public method that translates
exceptions to a domain error, and a protected `_method` that subclasses
implement.

| Port | File | Contract | Adapter lives in |
|------|------|----------|------------------|
| `AbstractChunker` | `ports/chunker.py` | `chunk(text) -> list[PreviewChunk]`; implement `_chunk`; errors → `ChunkingError` | `infrastructure/naive/chunkers/` |
| `AbstractEmbedder` | `ports/embedder.py` | `embed(text) -> list[float]`; implement `_embed`; errors → `EmbeddingError` | `infrastructure/naive/embedders/` |
| `AbstractFileTextExtractor` | `ports/file_text_extractor.py` | `extract(bytes) -> str`; implement `_extract`; errors → `FileTextExtractingError` | `infrastructure/file_text_extractors/` |
| `AbstractTaskRegister` | `ports/task_register.py` | `register(key, task)`, `cancel(key)` — async task lifecycle (sync methods) | `infrastructure/task_register.py` |
| `AbstractUnitOfWork` | `ports/unit_of_work.py` | async context manager; `commit()`, `rollback()`, `.naive_rag_repo`, `.graph_rag_repo` | `infrastructure/database/unit_of_work.py` |

---

## 5. Recipes

### 5.1 Add a new RAG strategy (or an operation to one)

Operations are orchestrators, one abstract base per operation, concrete
strategies dispatched by a factory keyed on `RAGStrategy`.

1. Add the member to `RAGStrategy` (in `src/shared/enums/knowledge_new`).
2. Write the concrete orchestrator under
   `application/orchestrators/<operation>/strategies/`, subclassing the
   operation's abstract base (e.g. `AbstractIndexOrchestrator`). Implement
   **`on_execute(command)`**; optionally override `on_cancel` / `on_error`.
3. Register it in that operation's factory registry, e.g.
   `application/orchestrators/indexing/factory.py`:
   ```python
   _REGISTRY = {
       RAGStrategy.NAIVE: NaiveIndexOrchestrator,
       RAGStrategy.GRAPH: GraphIndexOrchestrator,
       # RAGStrategy.MY_NEW: MyNewIndexOrchestrator,
   }
   ```
   A strategy absent from a registry is *unsupported* for that operation and
   yields `UnsupportedError` → HTTP 400. That's the mechanism, not a bug.

Never call an orchestrator directly from a controller — always go through the
`build_<operation>(strategy, uow)` factory.

### 5.2 Add a chunker / embedder / file-text-extractor

Same shape for all three — implement the port, register in the factory:

1. Subclass the port (`AbstractChunker` / `AbstractEmbedder` /
   `AbstractFileTextExtractor`); implement the protected `_chunk` / `_embed` /
   `_extract`. Do **not** catch-and-swallow — let the base translate to the
   domain error.
2. Register in the matching factory registry:
   - `infrastructure/naive/chunkers/factory.py` — keyed by `ChunkStrategyEnum`
   - `infrastructure/naive/embedders/factory.py` — keyed by `EmbedderProviderEnum`
   - `infrastructure/file_text_extractors/factory.py` — keyed by `FileExtensionEnum`

   Unregistered key → `UnsupportedError`. If you add a file type, add it to
   `FileExtensionEnum` too.

### 5.3 Add a GraphRAG storage or vector-store adapter

GraphRAG resolves storage/vector backends through its own factory. We register
custom MinIO-backed adapters at import time:

- Storage: `infrastructure/graphrag/storages.py` — implement the graphrag
  `Storage` interface, then `register_storage("<name>", MyStorage)`. The config
  is produced by `create_storage_config(rag_id, subdir)`.
- Vector store: `infrastructure/graphrag/vector_stores.py` — extend
  `LanceDBVectorStore`, then `register_vector_store("<name>", MyStore)`. Config
  from `create_vector_store_config(...)`.

The `endpoint` passed to both is the **full MinIO URL** (`http://host:port`) —
see §7 on the endpoint contract.

### 5.4 Add a REST endpoint

1. Add the route method to the relevant controller in
   `presentation/rest/controllers/` (e.g. `RagController`, base path
   `/rags/{strategy:str}/`). Keep it thin: build a command, call a factory, run
   the orchestrator, return a schema.
2. Add request/response schemas in `presentation/rest/schemas/`.
3. If the handler can raise a new domain error, map it in
   `presentation/rest/error_handlers.py` via `@registry(MyError)` → the right
   HTTP status. Unmapped `KnowledgeError` subclasses fall through to the 500
   catch-all.

---

## 6. Run & test locally

### Run

The service runs in Docker Compose from `src/`:

```bash
cd src && docker compose up -d knowledge_new
```

Config comes from environment variables, sourced from `src/.env`. **`.env` is
generated** from `src/env.yaml` — edit the YAML, then regenerate:

```bash
python scripts/envtool.py --dev   # local defaults
```

`settings.py` loads those vars through the shared `Env` helper
(`src/shared/envtools.py`), building `DATABASE_DNS` and `MINIO_ENDPOINT` from
their parts.

> **The image is baked, not bind-mounted.** Editing a `.py` file on the host and
> running `docker compose restart knowledge_new` does **nothing** — the container
> keeps running the old code. To see code changes you must rebuild:
> `docker compose up -d --build knowledge_new`. Env-var changes (via `.env`) only
> need `up -d` (recreate), no rebuild.

### Test

Tests live in `tests/`, grouped by seam:

- `tests/orchestrators/` — one folder per operation (indexing, prechunking,
  searching, metrics, removing).
- `tests/repositories/` — SQLAlchemy repository tests.
- `tests/services/` — adapter tests: `chunkers/`, `embedders/`,
  `file_text_extractors/`.

Conventions:

- Fakes are hand-written in-memory implementations of the ports (e.g.
  `FakeNaiveRagRepo` in `tests/orchestrators/indexing/`), not mocks — assert on
  real outcomes.
- Fixture builders (`make_config(...)`) live in per-folder `conftest.py`.
- `tests/conftest.py` provides `offload_to_process(...)` for exercising the real
  `ProcessPoolExecutor` path.

Run from the service dir: `cd src/knowledge_new && pytest`.

---

## 7. Service-specific conventions & gotchas

Things that are *not* in `backend-conventions.md` and have already bitten people.

### Config contract

- **`env.yaml` is the source of truth**; `.env` is generated. Never hand-edit
  `.env` as a permanent fix — change `env.yaml` and regenerate, or the next
  generation reverts you.
- `DATABASE_DNS` and `MINIO_ENDPOINT` are **assembled** from parts in
  `settings.py` via `Env`. The `Env.dns(...)` helper takes env-var *names*
  positionally (`provider, host, port, user, password, name`) — order matters and
  a wrong order fails silently (empty password → `fe_sendauth: no password
  supplied`).
- **MinIO endpoint is a full URL** (`http://host:port`), not a bare host. The
  MinIO client strips the scheme (`_parse_endpoint`); the LanceDB vector store
  passes the whole URL as `aws_endpoint`. One value serves both.
- **Bucket names must be S3-valid**: lowercase, digits, hyphens, dots — **no
  underscores** (`epicstaff_knowledge` → `InvalidBucketName`; use
  `epicstaff-knowledge`).

### Error flow — how an exception becomes an HTTP response

1. A repository method throws. The `BaseSQLAlchemyRepositoryMixin` auto-wraps
   every public async repo method (via `__init_subclass__`) and re-raises any
   non-`RepositoryError` as `RepositoryError`.
2. Orchestrator `.execute()` catches `asyncio.CancelledError`, `RepositoryError`
   and generic `Exception`, dispatching to `on_cancel` / `on_error`.
3. Domain errors that reach the controller are mapped to HTTP by the registry in
   `presentation/rest/error_handlers.py`:
   - not-found family (`RagNotFoundError`, `DocumentNotFoundError`, …) → **404**
   - `UnsupportedError` → **400**
   - `KnowledgeError` (base) → **500** (logged)

   Response body: `{"code": "...", "detail": "..."}`.

Define errors as `KnowledgeError` subclasses in `domain/errors.py`; map them in
the handler registry. Don't build ad-hoc HTTP responses in controllers.

### Runtime / packaging

- **venv lives at `/app/.venv`, outside the app dir.** nltk ≥ 3.9 ships an
  import-security hook that blocks modules resolving *under* the process CWD; a
  venv nested in the WORKDIR would trip it. Keep it a sibling (see the Dockerfile
  comment before touching `UV_PROJECT_ENVIRONMENT`).
- GraphRAG config models (`StorageConfig`, `VectorStoreConfig`) are
  `ConfigDict(extra="allow")` — extra fields like `endpoint`, `bucket`,
  `access_key` pass through untyped to the adapter constructor. That's why the
  field name on the config must match the adapter's kwarg exactly; a rename in
  one place silently drops the value in the other.

---

## 8. External dependencies that shape the code

- **GraphRAG 3.1.1** + companion packages `graphrag_storage`, `graphrag_vectors`,
  `graphrag_common` — factory-based storage/vector registration
  (`register_storage`, `register_vector_store`). We plug MinIO/LanceDB adapters
  into these factories; the pipeline (`graphrag.api.build_index`) is upstream
  code — read its docs rather than documenting internals here.
- **MinIO** (`miniopy_async`) — S3 object storage for both graph inputs/outputs
  and vector data.
- **LanceDB** — vector store for graph RAG, S3-backed via `aws_endpoint`.
- **LiteLLM** — the embedder adapters route provider calls through it.
- **Litestar** — HTTP framework; auto-generates OpenAPI (the endpoint reference
  lives at `/schema`, not in this doc).

---

## 9. Known gaps (as of 2026-09-10)

> This section dates fast. Each item should name a tracking ticket. The target
> architecture above is the canon; this is the delta between it and reality.

- **GraphRAG version leakage** — some V1/V5 graphrag-specific assumptions still
  leak across the hexagon boundary. _(fill in ticket)_
- **Contract DTOs / container / import-linter** — the strict-boundary enforcement
  (import-linter contracts, a formal DI container, contract DTOs at layer
  edges) is not yet in place. _(fill in ticket)_
- **Config validation at startup** — DSN/endpoint/bucket are only validated when
  a request reaches the relevant code, so misconfiguration surfaces late. A
  fail-fast startup check + CI smoke test would catch the whole class. _(fill in
  ticket)_

_Add / prune items here as the restructure lands. When an item is resolved,
delete it — don't leave a "done" note._

---

## 10. Pointers

- General backend rules: [`docs/backend-conventions.md`](../backend-conventions.md)
- Team-wide policy (commits, branches, PR scope): `CLAUDE.md`
- Env variables (source of truth): `src/env.yaml`
- Live API reference: the service's `/schema` (OpenAPI) endpoint
- GraphRAG upstream docs for pipeline/workflow internals
