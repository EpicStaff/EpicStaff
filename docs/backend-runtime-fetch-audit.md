# Backend Runtime External-Fetch Audit (EST-3245)

Purpose: identify every backend code path that silently contacts a third-party host at
**runtime** (model/tokenizer downloads, telemetry phone-home, hidden metadata fetches),
so the LICENSE/EULA "no third-party data flows at runtime" claim is accurate. Build-time
fetches (`poetry install`, Docker image builds) are out of scope — those happen before
the customer ever runs the product and are disclosed separately as build dependencies.

User-configured LLM/embedding providers (OpenAI, Cohere, HuggingFace Inference API, etc.)
are an explicit user choice made through the product UI — out of scope for "silent"
classification, listed as an EULA carve-out at the end of this doc.

Scope: `src/django_app`, `src/crew` (incl. vendored `libraries/mem0`, `libraries/crewAI`),
`src/knowledge` (incl. vendored `libraries/graphrag`), `src/realtime`,
`src/sandbox`, `src/shared`.

---

## Summary table

| Component | Trigger | Reachable in default deploy? | Data sent/pulled | Disposition | Action needed |
|---|---|---|---|---|---|
| chonkie `TokenChunker(tokenizer="gpt2")` — naive RAG default chunker | First document chunked with `chunk_strategy="token"` (the default strategy) | **YES** — default chunking strategy, `tokenizers` 0.23.1 is installed in the knowledge image | Downloads `gpt2/tokenizer.json` from huggingface.co | **Reachable — must fix** | Pre-cache the tokenizer file at image build (`RUN python -c "from tokenizers import Tokenizer; Tokenizer.from_pretrained('gpt2')"`) + set `HF_HUB_OFFLINE=1` at runtime, or switch the chunker to a bundled/vendored tokenizer file |
| GraphRAG `TiktokenTokenizer` (fallback when no `encoding_model` override) | First `rag_type="graph"` indexing/search when a model config doesn't set `encoding_model` | **YES if a customer creates a GraphRAG collection** — the `graphrag` Poetry group is **not** marked `optional`, so it ships in every knowledge image | Downloads BPE rank file from `openaipublic.blob.core.windows.net` (tiktoken's default download host) | **Reachable — must fix** | Pre-cache tiktoken encodings at image build (`RUN python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"`) and set `TIKTOKEN_CACHE_DIR` to a baked-in path |
| `realtime` chat-buffer tokenizer (`tiktoken.encoding_for_model("gpt-4o")`) | Every realtime/voice session that uses `ChatSummarizedBuffer` | **YES** — hardcoded default `model="gpt-4o"` | Same tiktoken BPE download as above | **Reachable — must fix** | Same tiktoken pre-cache/`TIKTOKEN_CACHE_DIR` fix, applied to the `realtime` image too |
| mem0 `HuggingFaceEmbedding` (crew memory embedder, catalog entry `huggingface/microsoft/codebert-base`) | User selects `provider="huggingface"` for Crew memory embedder | **NO (currently)** — `sentence-transformers` is not installed in the `crew` image; the class raises `ImportError` before any network call | Would be a `SentenceTransformer(model)` local download from huggingface.co if the dependency were ever added | **User-opt-in path, but currently broken / misleading catalog entry** | Either remove the `huggingface` embedder catalog entry (`embedding_models.json:38-40`) since it can never work, or if genuinely desired, add `sentence-transformers` as a dependency **and** pre-cache the model at build time |
| crewAI `RAGStorage` / chromadb default embedding function (`EmbeddingConfigurator._create_default_embedding_function`) | Would only trigger if `ShortTermMemory`/`EntityMemory` fell through to the `RAGStorage` branch | **NO** — `crew_parser_service.py` always sets `memory_config["provider"] = "local_mem0"` when `crew_data.memory=True`, so `ShortTermMemory`/`EntityMemory`/`UserMemory` always take the `LocalMem0Storage` branch, never `RAGStorage` | N/A — unreachable | **Unreachable in our config** | None (chromadb + posthog remain transitive deps of `crewai_tools`/mem0 but their embedding/vector-store code paths are never instantiated) |
| chromadb default embedding function (`OpenAIEmbeddingFunction` when `embedder_config=None`) — note: crewAI overrides chromadb's real default (ONNX MiniLM auto-download) with an OpenAI API embedder | Same `RAGStorage` path as above | **NO** — same reason (RAGStorage never instantiated) | N/A | **Unreachable in our config** | None — but flag for future: if `RAGStorage` is ever wired in, crewAI's override already avoids chromadb's local ONNX auto-download; only its own bundled `OpenAIEmbeddingFunction` default would apply, which needs `OPENAI_API_KEY` (an explicit user credential) |
| chromadb posthog telemetry | Only fires if a chromadb `Client()`/`PersistentClient()` is instantiated | **NO** — never instantiated (see above) | N/A | **Unreachable in our config** | None |
| mem0 `AnonymousTelemetry` (posthog) | Any `mem0.Memory` operation (add/search) | **Reachable path, but disabled by default** | Anonymous usage properties (os, python version, mem0 version) to mem0's posthog project | **Disabled via config — verify env propagation** | `docker-compose.yaml:232` sets `MEM0_TELEMETRY: ${MEM0_TELEMETRY:-False}` on the `crew` service (upstream mem0 default is `"True"` if unset — confirm this env var is always present in production compose/K8s manifests, not just the reference compose file) |
| crewAI telemetry (`Telemetry` → `ServerStrategy`/`LoggerStrategy`) | Every `Crew()` construction | **NO third-party endpoint by default** — EpicStaff forked crewAI's telemetry module; default `MonitoringType.LOCAL` writes to a local log file, never contacts a network endpoint. Only `MonitoringType.SERVER` sends OTLP traces, to `MONITORING_SERVER` (an operator-configured endpoint, not a hardcoded third party) | Trace spans (crew/task metadata; full payload only if `crew.share_crew=True`, which EpicStaff does not set) | **Not a runtime third-party flow by default** | None required; note the `MONITORING_TYPE` (code) vs `MONITORING_MODE` (env files) name mismatch as a follow-up cleanup — currently harmless because it fails safe to LOCAL |
| embedchain telemetry (posthog) | Only if `embedchain.App`/`vectordb.chroma` classes are instantiated | **NO** — `embedchain` is vendored under `libraries/mem0/embedchain/` but is not imported anywhere in `src/crew`'s own service code | N/A | **Unreachable in our config** | None |
| `litellm` model-price JSON fetch (`model_prices_and_context_window.json`, fetched from a GitHub raw URL) | **Every** `import litellm` — module-level, not lazy: `litellm/__init__.py:406` runs `model_cost = get_model_cost_map(url=model_cost_map_url)` unconditionally at import time. Hit by `crew` (via crewAI's `LLM`/`PatchedLLM`, mem0's `litellm.py`), `django_app`'s `litellm_client.py`, and `knowledge` (transitively via the non-optional `graphrag` poetry group, whose `language_model/providers/litellm/*` imports litellm) | **YES — confirmed by runtime trace (2026-07-03)** | Outbound GET to `https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json`; no EpicStaff/customer data leaves, but it is a real unconditional network call on every process start | **Reachable — must fix (confirmed, was previously "unconfirmed")** | Verified two ways against the pinned `litellm==1.75.7` installed in `src/crew/.venv`: (1) read `litellm/litellm_core_utils/get_model_cost_map.py` — with `LITELLM_LOCAL_MODEL_COST_MAP` unset it always calls `httpx.get(url, timeout=5)` before falling back to the bundled `model_prices_and_context_window_backup.json` on any exception; (2) monkeypatched `socket.socket.connect` and ran `import litellm` — observed 3 connect attempts to `185.199.10{8,9,10}.133:443` (GitHub Pages/raw's Fastly IPs) with the env var unset, and **zero** connect attempts with `LITELLM_LOCAL_MODEL_COST_MAP=True` set (import succeeded, `litellm.model_cost` still populated with 1319 entries from the local backup JSON). Fix: `LITELLM_LOCAL_MODEL_COST_MAP=True` baked into the `crew`, `knowledge`, and `django_app` Dockerfiles' runtime `ENV` (done in EST-3245 unit 4). |
| Knowledge-service embedders (openai/gemini/cohere/mistral/together_ai) | Naive RAG indexing/search, `src/knowledge/embedder/*.py` | Reachable, but these are hosted **API** calls with an explicit provider/model chosen by the user in the Knowledge UI | Chunk text / query text to the user's configured provider | **User-opt-in (EULA carve-out)** | None — document as carve-out |
| Crew memory LLM/embedder (openai/gemini/cohere/etc. via `parse_memory_llm`/`parse_memory_embedder`) | Crew memory feature enabled with a real provider | Reachable, user-configured, requires the user to assign `memory_llm`/`embedder` explicitly (`crew_parser_service.py:186-194` raises `ValueError` if missing) | Memory text to the user's configured LLM/embedder provider | **User-opt-in (EULA carve-out)** | None |
| `agent_crew_llm.py:152` HuggingFace LLM provider (`HuggingFaceEndpoint`) | Agent LLM provider set to `huggingface` | Reachable, user-configured, requires `HUGGINGFACEHUB_API_TOKEN` | Prompt to HuggingFace's hosted Inference API | **User-opt-in (EULA carve-out)** | None |
| GraphRAG embedding/LLM config (`GraphRagConfigBuilder`) | `rag_type="graph"` collections | Reachable, backed by the same `Provider`/`EmbeddingConfig`/`LLMConfig` DB rows as naive RAG — user-configured | Document/query text to the user's configured provider | **User-opt-in (EULA carve-out)** | None |

---

## Detail per finding

### 1. chonkie `TokenChunker` — hidden HuggingFace tokenizer download (default chunker)

- `src/knowledge/chunkers/token_chunker.py:8-9` — `ChonkieTokenChunker(tokenizer="gpt2", chunk_size=chunk_size, chunk_overlap=chunk_overlap)`.
- Per `wiki/services/knowledge.md:129` this is the **default** chunker (`"token"` strategy) for `NaiveRagDocumentConfig.chunk_strategy`.
- chonkie's tokenizer resolution (`src/knowledge/.venv/Lib/site-packages/chonkie/tokenizer.py:270-297`, package version `chonkie 1.3.1`) tries, in order: `tokenizers.Tokenizer.from_pretrained("gpt2")` → `tiktoken.get_encoding("gpt2")` → `transformers.AutoTokenizer.from_pretrained("gpt2")`.
- Confirmed installed in the knowledge image (`src/knowledge/.venv/Lib/site-packages/`): `tokenizers-0.23.1`, `tiktoken-0.12.0`, `huggingface_hub-1.13.0`. Since `tokenizers` is present, the **first branch wins** — `Tokenizer.from_pretrained("gpt2")` calls out to `huggingface.co` to fetch `gpt2/tokenizer.json` on the very first chunk operation in a fresh container, then caches to `HF_HOME`/`~/.cache/huggingface`.
- `src/knowledge/Dockerfile.knowledge:34` only runs `poetry install --no-ansi --no-root` — no pre-warm step. Nothing bakes the tokenizer file into the image.

### 2. GraphRAG `TiktokenTokenizer` fallback

- `src/knowledge/libraries/graphrag/graphrag/tokenizer/get_tokenizer.py:34-41` — if the caller doesn't pass a `model_config` with `encoding_model` set, `get_tokenizer()` returns `TiktokenTokenizer(encoding_name=encoding_model)` (default `ENCODING_MODEL`, `graphrag/config/defaults.py`, typically `cl100k_base`).
- `tiktoken.get_encoding(...)` downloads the BPE rank file from `openaipublic.blob.core.windows.net` on first use per-process, cached to `TIKTOKEN_CACHE_DIR` (defaults to a temp dir) after.
- The `graphrag` Poetry group (`src/knowledge/pyproject.toml:38-39`) has **no** `optional = true` marker, so `poetry install --no-ansi --no-root` (`Dockerfile.knowledge:34`) installs it in every build — it is not gated behind an opt-in extra.
- Reachability is still gated by product usage: a customer must create a `rag_type="graph"` collection (an explicit UI choice), but the tokenizer fetch itself is not something the UI surfaces or the EULA carve-out covers — it's a hidden dependency of that feature, not a "configure your own LLM provider" flow.

### 3. `realtime` chat-buffer tokenizer

- `src/realtime/utils/tokenizer.py:1,18` — `tiktoken.encoding_for_model(model)`, called from `src/realtime/application/conversation_service.py:220` with a hardcoded default `model: str = "gpt-4o"` in `_initialize_buffer`.
- Same tiktoken download mechanism as finding #2, but reachable on essentially every realtime/voice session that uses the summarized chat buffer, independent of which LLM/voice provider the user actually configured for the session.

### 4. mem0 `HuggingFaceEmbedding` — currently broken, not silently reachable

- `src/crew/libraries/mem0/mem0/embeddings/huggingface.py:3,15` — `from sentence_transformers import SentenceTransformer` then `SentenceTransformer(self.config.model, ...)`, which would download model weights from huggingface.co on first construction.
- `src/django_app/tables/provider_models/embedding_models.json:38-40` still lists a `"huggingface"` embedder catalog entry (`huggingface/microsoft/codebert-base`), which is loaded into the `Provider` table by `src/django_app/tables/management/commands/upload_models.py` and is selectable in the UI for Crew memory embedder.
- Checked `src/crew/.venv/Lib/site-packages/` — `sentence-transformers` is **not installed**. If a user selects this catalog entry today, `mem0.embeddings.huggingface.HuggingFaceEmbedding.__init__` raises `ImportError` immediately, before any network call. So today this is a broken UI option, not a silent data flow — but it's a landmine: adding `sentence-transformers` later (e.g. to fix the crash) would silently reintroduce a real local-model download unless paired with build-time caching.

### 5. crewAI memory (`RAGStorage`/chromadb) — confirmed unreachable

- `src/crew/services/crew/crew_parser_service.py:180-204` — whenever `crew_data.memory` is true, `memory_config["provider"]` is hardcoded to `"local_mem0"` (`src/crew/settings.py:7-8`, `PGVECTOR_MEMORY_CONFIG`), and the vector store is hardcoded to `pgvector` (`src/crew/settings.py:11-13`), not chromadb.
- Checked `ShortTermMemory.__init__` (`src/crew/libraries/crewAI/src/crewai/memory/short_term/short_term_memory.py:18-30`), `EntityMemory.__init__` (`.../entity/entity_memory.py:14-26`), and `create_crew_memory` (`.../crew.py:255-291`) — all three branch on `memory_config.get("provider")`; with `"local_mem0"` they always take the `LocalMem0Storage` branch, never the `RAGStorage`/chromadb branch. `LongTermMemory` (`local_long_term_memory.py:17-30`) is even stricter: it raises `AttributeError` if the provider isn't `"local_mem0"`.
- Since `RAGStorage` (and therefore `EmbeddingConfigurator` → chromadb's default embedding function, and chromadb's `PersistentClient`/posthog telemetry) is never instantiated in EpicStaff's current usage, this entire path is unreachable — confirmed by reading the actual dispatch logic, not just by config intent.
- No `knowledge_sources`/`KnowledgeStorage` usage found anywhere in `src/crew` (grep returned zero matches) — crewAI's separate "Agent Knowledge" feature (which also uses chromadb/`RAGStorage`) is not wired up at all.

### 6. Telemetry — mem0 posthog and crewAI OTLP

- mem0: `src/crew/libraries/mem0/mem0/memory/telemetry.py:11,29-30` — `MEM0_TELEMETRY` env var defaults to `"True"` **upstream**, but `src/docker-compose.yaml:232` sets `MEM0_TELEMETRY: ${MEM0_TELEMETRY:-False}` on the `crew` service, which disables `self.posthog.disabled = True` at construction. Verify this same default is present in whatever compose/Helm/K8s manifest ships to customers (not just this reference `docker-compose.yaml`).
- crewAI: `src/crew/libraries/crewAI/src/crewai/telemetry/telemetry.py:38-56` — this is a **forked** version of crewAI's telemetry, not upstream. Default `MonitoringType.LOCAL` writes spans to a local file (`LoggerStrategy`/`FileLogger`) — no network call at all. Only `MonitoringType.SERVER` (triggered by `MONITORING_TYPE=server` env var) builds an `OTLPSpanExporter` pointed at `MONITORING_SERVER` — an operator-supplied endpoint, not a hardcoded third party.
- Gotcha found during this audit: the code reads `MONITORING_TYPE` (`telemetry.py:40`) but every env file in the repo (`src/.env.example:104`, `src/debug.env:63`, `src/docker-compose.yaml:233`) defines `MONITORING_MODE` instead. This mismatch means `MONITORING_TYPE` is never actually set by the shipped config, so the code always falls through to `MonitoringType.LOCAL` regardless of what operators put in `MONITORING_MODE`. Currently harmless (fails safe to local-only), but confusing and worth fixing so the `MONITORING_MODE=server` documented option actually works.

### 7. litellm model-cost JSON — confirmed by runtime trace (2026-07-03, EST-3245 unit 4)

- `litellm==1.75.7` is a direct dependency of `src/crew/pyproject.toml:33` and is used inside crewAI's `LLM` class (`src/crew/libraries/crewAI/src/crewai/llm.py`) which `PatchedLLM` (`src/crew/utils/llm_wrapper.py`) wraps; also used by `src/django_app/tables/services/llm_clients/litellm_client.py` and GraphRAG's `graphrag/language_model/providers/litellm/*` (pulled into the `knowledge` image via the non-optional `graphrag` poetry group).
- Confirmed the fetch is **unconditional at import time**, not gated behind a specific cost/usage API call: `litellm/__init__.py:406` runs `model_cost = get_model_cost_map(url=model_cost_map_url)` as a module-level statement during `import litellm`.
- Read `litellm/litellm_core_utils/get_model_cost_map.py`: with `LITELLM_LOCAL_MODEL_COST_MAP` unset (or falsy), it always does `httpx.get(url, timeout=5)` against `https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json` first, falling back to the bundled `model_prices_and_context_window_backup.json` only on any exception (including a timeout).
- Ran a live runtime trace against the pinned version in `src/crew/.venv`: monkeypatched `socket.socket.connect` to record addresses before raising, then did `import litellm`. With the env var unset, saw 3 connect attempts to `185.199.108.133`, `185.199.109.133`, `185.199.110.133` (port 443 — GitHub raw/Pages' Fastly anycast IPs). Re-ran with `LITELLM_LOCAL_MODEL_COST_MAP=True` set: **zero** connect attempts, import succeeded, `litellm.model_cost` still populated (1319 entries, from the local backup JSON).
- Disposition flipped from "Unconfirmed" to **Reachable — must fix**, confirmed. Fix applied: `LITELLM_LOCAL_MODEL_COST_MAP=True` set as a build-baked `ENV` in `src/crew/Dockerfile.crew`, `src/knowledge/Dockerfile.knowledge`, and `src/django_app/Dockerfile.dj` runtime stages.

### 8. Docker build-vs-runtime check

- `src/crew/Dockerfile.crew` and `src/knowledge/Dockerfile.knowledge` both only run `poetry install` in the builder stage — no `RUN python -c "..."` pre-warm/pre-cache steps for tokenizers, embedding models, or NLTK/spacy data anywhere in either file. Every other service Dockerfile checked (`django_app`, `manager`, `realtime`, `sandbox`, `webhook`) follows the same plain-`poetry install` pattern and none of them touch model/tokenizer downloads based on the earlier grep, so they're out of scope for this specific finding.
- Conclusion: nothing in this repo currently does the "safe" thing (pre-cache at build) for any of the tokenizer paths above — all identified downloads happen at first runtime use inside the customer's environment.

---

## Recommended EULA carve-outs

List these explicitly as "you control what data leaves your deployment" rather than folding them into the blanket "no third-party data flows" claim:

1. **Knowledge RAG embedder providers** (openai, gemini, cohere, mistral, together_ai) — `src/knowledge/embedder/*.py`. Chunk/query text goes to whichever provider the user selects and supplies an API key for.
2. **Crew memory LLM + embedder** — `parse_memory_llm`/`parse_memory_embedder` (`src/crew/utils/parse_llm.py`). Only reachable when the user explicitly enables Crew memory and assigns both a memory LLM and embedder.
3. **Agent/Crew LLM providers generally** (OpenAI, Anthropic, Groq, HuggingFace Inference API via `HuggingFaceEndpoint`, Ollama if pointed at a remote host, etc.) — `src/crew/utils/agent_crew_llm.py`, `src/crew/utils/parse_llm.py`.
4. **GraphRAG LLM/embedding configuration** — same `Provider`/`LLMConfig`/`EmbeddingConfig` DB rows as #1, applies when a user creates a `rag_type="graph"` collection.
5. **Voice/realtime providers** (OpenAI Realtime, Gemini Live, ElevenLabs ConvAI, Twilio) — outside this audit's file scope but should be listed alongside the others since they're the same "explicit user choice with credentials" pattern.

Note: #1-#4 all cover the *provider API call* (sending text to the configured LLM/embedding service). They do **not** cover the hidden tokenizer downloads in the Action Items below, which happen regardless of which provider the user picked and are not disclosed anywhere in the current UI/EULA draft.

---

## Action items

1. **Done (EST-3245 unit 4):** Pre-cache the `gpt2` HuggingFace tokenizer file used by chonkie's default `TokenChunker` at `knowledge` image build time, and set `HF_HUB_OFFLINE=1` at runtime so any future accidental HF Hub call fails loudly instead of phoning home. (`src/knowledge/chunkers/token_chunker.py`, `src/knowledge/Dockerfile.knowledge`) — verified offline end-to-end locally (`chonkie.TokenChunker(tokenizer="gpt2")` chunks successfully with `HF_HUB_OFFLINE=1` after the cache-priming step).
2. **Done (EST-3245 unit 4):** Pre-cache tiktoken encodings (`cl100k_base` for GraphRAG's `ENCODING_MODEL` default, `o200k_base` for realtime's hardcoded `gpt-4o` default) at build time for both the `knowledge` and `realtime` images, and set `TIKTOKEN_CACHE_DIR` to a baked-in path. (`src/knowledge/libraries/graphrag/graphrag/tokenizer/get_tokenizer.py`, `src/realtime/utils/tokenizer.py`, `src/knowledge/Dockerfile.knowledge`, `src/realtime/Dockerfile.realtime`) — verified locally that `tiktoken.encoding_for_model("gpt-4o")` resolves to `o200k_base`.
3. **Done (EST-3245 unit 4):** Removed the `huggingface` embedder catalog entry from `src/django_app/tables/provider_models/embedding_models.json` — the `huggingface` `Provider` row is still created via the unrelated `huggingface` entry in `llm_models.json` (LLM providers, a separate EULA carve-out), so no orphaned-provider or FK issue.
4. **Verify:** Confirm `MEM0_TELEMETRY=False` (or equivalent) is actually set in every deployment target (K8s manifests, customer install scripts), not just the reference `docker-compose.yaml`. Upstream mem0 defaults to telemetry-on if the env var is absent. Hardened further in EST-3245 unit 4: `MEM0_TELEMETRY=False` is now also baked into `src/crew/Dockerfile.crew`'s runtime `ENV` as a defense-in-depth default (holds even if a deploy target's compose/K8s manifest omits the override).
5. **Fix — confirmed and neutralized (EST-3245 unit 4):** Runtime trace confirmed `litellm==1.75.7` fetches its model-price JSON from GitHub raw unconditionally at `import litellm` time. `LITELLM_LOCAL_MODEL_COST_MAP=True` is now set as a build-baked `ENV` in `crew`, `knowledge`, and `django_app` Dockerfiles.
6. **Low-priority cleanup:** Fix the `MONITORING_TYPE` (code) vs `MONITORING_MODE` (env files) naming mismatch in the forked crewAI telemetry module so the documented `server` mode actually activates when configured — currently harmless because it silently no-ops to local-only telemetry, but it's a latent config bug independent of the privacy question.
7. **No action needed, confirmed unreachable:** crewAI's `RAGStorage`/chromadb memory path, chromadb's default embedding function/ONNX auto-download, chromadb posthog telemetry, and embedchain — none of these are ever instantiated given how `crew_parser_service.py` always forces `memory_config.provider = "local_mem0"` and no code references `knowledge_sources`/embedchain.
