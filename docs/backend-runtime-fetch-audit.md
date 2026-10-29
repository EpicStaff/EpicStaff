# Backend Runtime External-Fetch Audit

Purpose: identify every backend code path that silently contacts a third-party host at
**runtime** (model/tokenizer downloads, telemetry phone-home, hidden metadata fetches),
so the LICENSE/EULA "no third-party data flows at runtime" claim is accurate. Build-time
fetches (`uv sync`, Docker image builds) are out of scope — those happen before
the customer ever runs the product and are disclosed separately as build dependencies.

User-configured LLM/embedding providers (OpenAI, Cohere, HuggingFace Inference API, etc.)
are an explicit user choice made through the product UI — out of scope for "silent"
classification, listed as an EULA carve-out at the end of this doc.

## As of

Findings are taken at `developer` @ `0186d11e4`, 2026-10-16, from source and lockfile
reads. This revision re-verifies every finding of the original audit (2026-07-03, against
a tree that still vendored crewAI, mem0 and GraphRAG and shipped `src/knowledge`); it is
not a fresh sweep — [Coverage](#coverage) lists what was and was not looked at. The only
runtime trace is the litellm one in finding 4, run on `litellm==1.75.7`; on the current
`1.100.5` the env-var check it relies on was re-read in source, not re-traced.

When a service is added, replaced or rewritten, or a lockfile gains or loses a package
that downloads models or phones home, re-verify the affected rows and update this section.

## Coverage

Scope: `src/django_app`, `src/crew`, `src/knowledge_new`, `src/realtime`, `src/agent`,
`src/sandbox`, `src/shared` — limited per service as below.

| Service | What was verified at this commit |
|---|---|
| `knowledge_new` | Findings 1, 2, 4 (tokenizers, litellm cost map) and the embedder carve-out. Replaced `src/knowledge` after the original audit |
| `realtime` | Finding 3 (chat-buffer tokenizer) |
| `django_app` | Finding 4 (litellm cost map) and finding 5 (embedder catalog) |
| `crew` | Finding 4 only. The service was rewritten on LangGraph + litellm after the original audit (no crewAI, no mem0); its new code has **not** been swept |
| `agent` | Finding 4 only. **Not audited** otherwise — it was not in the original scope |
| `sandbox`, `shared` | In the original scope; **not re-swept** at this commit |
| `auditor`, `manager`, `webhook` | **Not audited** — never in scope |

---

## Summary table

| # | Component | Trigger | Data sent/pulled if unmitigated | Status at this commit | Mitigation |
|---|---|---|---|---|---|
| 1 | chonkie `TokenChunker` (`chonkie` 1.7.0 via `tokie` 0.1.4) — naive RAG default chunker | First document chunked with `chunk_strategy="token"` (the default) | Downloads the `gpt2` tokenizer from huggingface.co | **Fixed** | Tokenizer baked into the image and loaded by path (`KNOWLEDGE_TOKENIZER_PATH`) |
| 2 | GraphRAG / litellm tiktoken encodings in `knowledge_new` (`graphrag` 3.1.1, `tiktoken` 0.13.0) | First `rag_type="graph"` indexing/search; litellm token counting | BPE rank files from `openaipublic.blob.core.windows.net` | **Fixed** | `o200k_base` and `cl100k_base` pre-cached at build; `TIKTOKEN_CACHE_DIR` + `CUSTOM_TIKTOKEN_CACHE_DIR` set at runtime |
| 3 | `realtime` chat-buffer tokenizer (`tiktoken.encoding_for_model("gpt-4o")`, `tiktoken` 0.9.0) | Every realtime/voice session that uses the summarized chat buffer | Same tiktoken BPE download as #2 | **Fixed** | `o200k_base` pre-cached at build; `TIKTOKEN_CACHE_DIR` set at runtime |
| 4 | `litellm` model-price JSON fetch (`litellm` 1.100.5) | Every `import litellm` (module level) | GET `https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json` | **Fixed in all four importing services** | `LITELLM_LOCAL_MODEL_COST_MAP=True` in the runtime `ENV` of `agent`, `crew`, `django_app`, `knowledge_new` |
| 5 | `huggingface` embedder catalog entry (formerly a `SentenceTransformer` local download in vendored mem0) | User selecting it as an embedder | Model weights from huggingface.co | **Removed** | Entry no longer in `embedding_models.json`; mem0 is no longer a dependency |

Findings about packages that are no longer shipped are listed under
[Removed since the original audit](#removed-since-the-original-audit), not in this table.

---

## Detail per finding

### 1. chonkie `TokenChunker` — HuggingFace tokenizer download (default chunker)

- `src/knowledge_new/infrastructure/database/models/naive.py:55` — `chunk_strategy` defaults to `"token"`, which `src/knowledge_new/infrastructure/naive/chunkers/factory.py:13` maps to `TokenChunker`.
- chonkie ≥1.7 resolves a tokenizer name through `tokie`, a Rust extension that ignores `HF_HOME`/`HF_HUB_OFFLINE`, caches under `$HOME/.cache/huggingface/hub`, and downloads `openai-community/gpt2` from huggingface.co on a cold cache. A builder-stage cache warm cannot reach the runtime stage.
- Mitigation: `src/knowledge_new/Dockerfile:54-56` saves the tokenizer to `/app/.cache/tokie/gpt2.tkz` at build; `src/knowledge_new/infrastructure/naive/chunkers/strategies/token_chunker.py:9-16` loads it with `Tokenizer.from_file(settings.TOKENIZER_PATH)`. `KNOWLEDGE_TOKENIZER_PATH` is required — `src/knowledge_new/settings.py:43` (`env.str`, no default) and `src/docker-compose.yaml:661` (`${KNOWLEDGE_TOKENIZER_PATH:?}`) — so the `"gpt2"` name fallback in the chunker is not reached in a compose deploy.
- `HF_HUB_OFFLINE=1` (`src/knowledge_new/Dockerfile:94`) still covers the Python `huggingface_hub` client.
- Verified when the fix landed: a container from the built image with `--network none` completes a token chunking operation; the control with `KNOWLEDGE_TOKENIZER_PATH` unset fails with a DNS error from tokie. Not re-run at this commit.

### 2. tiktoken encodings in `knowledge_new` (GraphRAG and litellm)

- GraphRAG's default `ENCODING_MODEL` is `o200k_base`; litellm's default encoding is `cl100k_base`. Without a cache, `tiktoken.get_encoding(...)` downloads the BPE file from `openaipublic.blob.core.windows.net` on first use per process. `knowledge_new` sets no `encoding_model` override of its own.
- The `graphrag` package ships in every `knowledge_new` image (`uv sync --all-groups --no-group dev`, `src/knowledge_new/Dockerfile:40`); reachability is gated by a customer creating a `rag_type="graph"` collection.
- Mitigation: `src/knowledge_new/Dockerfile:53-55` pre-caches both encodings into `/app/.cache/tiktoken`; the runtime `ENV` (`src/knowledge_new/Dockerfile:92-93`) sets `TIKTOKEN_CACHE_DIR` to that path and `CUSTOM_TIKTOKEN_CACHE_DIR` to the same path, because litellm otherwise overwrites `TIKTOKEN_CACHE_DIR` at import with its own bundled copy.

### 3. `realtime` chat-buffer tokenizer

- `src/realtime/utils/tokenizer.py:18` — `tiktoken.encoding_for_model(model)`, reached from `ConversationService._initialize_buffer` (`src/realtime/application/conversation_service.py:251-252`) with a hardcoded default `model="gpt-4o"` (`o200k_base`), independent of the provider the user configured for the session.
- Mitigation: `src/realtime/Dockerfile.realtime:50-51` pre-caches the encoding at build; the runtime `ENV` sets `TIKTOKEN_CACHE_DIR=/app/.cache/tiktoken` (`src/realtime/Dockerfile.realtime:77`). `realtime` does not depend on litellm, so no `CUSTOM_TIKTOKEN_CACHE_DIR` is needed.

### 4. litellm model-cost JSON

- Services that import litellm at this commit, counted from the tree (`git grep` for `import litellm` / `from litellm` outside tests), all on `litellm==1.100.5`:
  - `agent` — `src/agent/app/llm/` (`config.py`, `litellm_client.py`, `retry.py`, `router_pool.py`), `src/agent/app/loop/agent_loop.py`
  - `crew` — `src/crew/services/graph/subgraphs/classification_decision_table_node.py`
  - `django_app` — `src/django_app/tables/services/llm_clients/litellm_client.py`, `src/django_app/tables/utils/litellm_model_info.py`
  - `knowledge_new` — `src/knowledge_new/infrastructure/naive/embedders/strategies/litellm_embedder.py`
- `import litellm` loads the model-price map at module level. With `LITELLM_LOCAL_MODEL_COST_MAP` unset, `litellm/litellm_core_utils/get_model_cost_map.py` calls `httpx.get(url, timeout=...)` against GitHub raw before falling back to the bundled backup JSON. In `1.100.5` the env check is `os.getenv("LITELLM_LOCAL_MODEL_COST_MAP", "").lower() == "true"`, which short-circuits to the local backup.
- Runtime trace (2026-07-03, `litellm==1.75.7`): with `socket.socket.connect` monkeypatched, `import litellm` made 3 connect attempts to `185.199.10{8,9,10}.133:443` (GitHub raw's Fastly IPs) with the variable unset and **zero** with `LITELLM_LOCAL_MODEL_COST_MAP=True`, while `litellm.model_cost` was still populated from the backup. Not re-traced on `1.100.5`.
- Mitigation — `LITELLM_LOCAL_MODEL_COST_MAP=True` in the runtime `ENV` of all four services: `src/agent/Dockerfile.agent:61`, `src/crew/Dockerfile.crew:64`, `src/django_app/Dockerfile.dj:55`, `src/knowledge_new/Dockerfile:95`. The django_app test settings set it too (`src/django_app/tests/settings.py:7`).

### 5. `huggingface` embedder catalog entry

- The original audit found a `huggingface/microsoft/codebert-base` embedder entry that resolved to vendored mem0's `HuggingFaceEmbedding` (`SentenceTransformer`, a local model download) — broken at the time because `sentence-transformers` was not installed, and a download path the moment it was.
- At this commit `src/django_app/tables/provider_models/embedding_models.json` has no `huggingface` entry, and neither `mem0ai` nor `sentence-transformers` is in any `uv.lock`. The `huggingface` LLM provider in `llm_models.json` is a hosted-API carve-out, not a local download.

---

## Removed since the original audit

These rows of the 2026-07-03 audit analysed code that no longer ships. At this commit none
of `mem0ai`, `crewai`, `chromadb`, `embedchain` or `posthog` is in any `uv.lock`, and
`src/crew/libraries/` and `src/knowledge/` contain no tracked files. They are kept here
only so a reader comparing against the old version can see where each one went.

| Original finding | Original disposition | Why it no longer applies |
|---|---|---|
| crewAI `RAGStorage` / chromadb default embedding function | Unreachable in our config | crewAI and chromadb are no longer dependencies |
| chromadb default embedding function (`OpenAIEmbeddingFunction`) | Unreachable in our config | Same |
| chromadb posthog telemetry | Unreachable in our config | Same; `posthog` is in no lockfile |
| mem0 `AnonymousTelemetry` (posthog), disabled via `MEM0_TELEMETRY=False` | Disabled via config | mem0 is no longer a dependency; `MEM0_TELEMETRY` is no longer set anywhere |
| crewAI forked telemetry (`MONITORING_TYPE` vs `MONITORING_MODE` mismatch) | Not a third-party flow by default | The forked crewAI module is gone; no `MONITORING_*` variable exists in `src/` |
| embedchain telemetry (posthog) | Unreachable in our config | embedchain is no longer vendored |
| Crew memory LLM/embedder carve-out (`parse_memory_llm` / `parse_memory_embedder`) | User-opt-in | The crewAI-based crew service and its memory feature were removed |

---

## Recommended EULA carve-outs

List these explicitly as "you control what data leaves your deployment" rather than folding them into the blanket "no third-party data flows" claim:

1. **Knowledge RAG embedder providers** — `src/knowledge_new/infrastructure/naive/embedders/strategies/litellm_embedder.py`. Chunk/query text goes to whichever provider the user selects and supplies an API key for.
2. **Agent and flow LLM providers** (OpenAI, Anthropic, Groq, HuggingFace Inference API, Ollama if pointed at a remote host, etc.) — called through litellm in `src/agent/app/llm/` and `src/crew/`, and from `src/django_app/tables/services/llm_clients/litellm_client.py`.
3. **GraphRAG LLM/embedding configuration** — the same user-configured provider rows as #1, used when a user creates a `rag_type="graph"` collection.
4. **Voice/realtime providers** (OpenAI Realtime, Gemini Live, ElevenLabs ConvAI, Twilio) — `src/realtime/infrastructure/providers/`. Same "explicit user choice with credentials" pattern.

Note: these cover the *provider API call* only. They do **not** cover hidden downloads such as the tokenizer fetches above, which happen regardless of which provider the user picked.

---

## Open items

1. **Coverage gaps.** `agent`, `auditor`, `manager` and `webhook` have never been audited, the rewritten `crew` has not been swept, and `sandbox`/`shared` were not re-swept at this commit (see [Coverage](#coverage)). Until they are, this document supports the EULA claim only for the paths listed in the summary table.
2. **tiktoken in `agent`, `crew`, `django_app`.** These three import litellm and have `tiktoken` 0.14.0 in their lockfiles, but set neither `TIKTOKEN_CACHE_DIR` nor `CUSTOM_TIKTOKEN_CACHE_DIR`, so litellm points tiktoken at its own bundled cache. Whether any code path in them requests an encoding that cache does not contain — which would trigger a download — is not established.
3. **Re-trace litellm on the pinned version.** The finding 4 trace predates the `1.100.5` upgrade; re-running it would turn the source read into a measurement.
