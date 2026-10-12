# --- Stage 1: Builder ---
FROM python:3.12.10-slim@sha256:fd95fa221297a88e1cf49c55ec1828edd7c5a428187e67b5d1805692d11588db AS builder

# Wheels only. UV_NO_BUILD=1 refuses to build source distributions, so no
# sdist's setup.py / PEP 517 backend runs at install time, meaning resolving
# never executes arbitrary Python code. A service that gains a dependency with
# no Linux wheel will fail the build rather than silently regain source
# execution.
#
# UV_PYTHON_DOWNLOADS=never is load-bearing: without it uv may fetch its own
# interpreter instead of using the digest-pinned base image above, silently
# defeating that pin.
RUN pip install --no-cache-dir uv==0.11.21

# The venv lives at /app/.venv, OUTSIDE the app dir (/app/src/knowledge, the
# runtime WORKDIR/CWD). nltk>=3.9 ships an import-security hook that blocks any
# module whose files resolve *underneath* the process CWD (CWE-427 mitigation);
# a venv nested inside the WORKDIR would make every site-packages module (e.g.
# `regex`, pulled by nltk) look CWD-local and get blocked. Keeping it a sibling
# of the app dir avoids that while a single `COPY /app` still carries both.
ENV UV_NO_BUILD=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    UV_CACHE_DIR=/tmp/uv_cache \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app/src

# Copy only dependency descriptors first (better layer caching)
COPY ./knowledge_new/pyproject.toml ./knowledge_new/uv.lock ./knowledge/

WORKDIR /app/src/knowledge

# Install dependencies into /app/.venv.
# --all-groups is required: transitive-pins (and any other non-dev group) is
# not installed by default. --no-group dev deliberately excludes dev from this
# image.
RUN uv sync --frozen --no-install-project --all-groups --no-group dev

# Pre-cache every tokenizer the service resolves at runtime so no customer
# deployment fetches one on first use (see docs/backend-runtime-fetch-audit.md):
# - tiktoken encodings o200k_base (GraphRAG's ENCODING_MODEL default) and
#   cl100k_base (litellm's default encoding), otherwise fetched from
#   openaipublic.blob.core.windows.net.
# - chonkie's default "gpt2" TokenChunker tokenizer, resolved through tokie.
#   tokie ignores HF_HOME/HF_HUB_OFFLINE and caches under $HOME, which the
#   runtime stage does not inherit, so the tokenizer is saved to a file that
#   the chunker loads by path (KNOWLEDGE_TOKENIZER_PATH, set by compose).
# Cache dirs must live under /app since nothing outside it is copied into the
# runtime stage.
ENV TIKTOKEN_CACHE_DIR=/app/.cache/tiktoken
RUN mkdir -p /app/.cache/tokie \
 && /app/.venv/bin/python -c "import tiktoken; tiktoken.get_encoding('o200k_base'); tiktoken.get_encoding('cl100k_base')" \
 && /app/.venv/bin/python -c "from tokie import Tokenizer; Tokenizer.from_pretrained('openai-community/gpt2').save('/app/.cache/tokie/gpt2.tkz')"

# Copy application source
COPY ./knowledge_new /app/src/knowledge
COPY ./shared /app/src/shared

# --- Stage 2: Runtime ---
FROM python:3.12.10-slim@sha256:fd95fa221297a88e1cf49c55ec1828edd7c5a428187e67b5d1805692d11588db AS runtime

# libpq-dev is required for psycopg https://www.psycopg.org/docs/install.html
RUN apt-get update && apt-get install -y libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy built app (and the /app/.venv beside it) from builder
COPY --from=builder /app /app

# Add virtualenv to PATH.
# The app's top-level modules (main, bootstrap, settings, ...) live in the
# WORKDIR and `src.shared` resolves from /app, so both are on PYTHONPATH
# explicitly rather than relying on the CWD being searched. PYTHONSAFEPATH=1
# keeps the CWD off sys.path so spawn-based workers inherit nltk's CWD isolation.
# TIKTOKEN_CACHE_DIR points at the pre-baked cache from the builder stage;
# CUSTOM_TIKTOKEN_CACHE_DIR stops litellm from redirecting TIKTOKEN_CACHE_DIR to
# its own bundled copy at import time.
# HF_HUB_OFFLINE=1 makes any huggingface_hub (Python) call fail loudly instead
# of phoning home; it does not reach tokie, which is why the baked tokenizer
# file above exists.
# LITELLM_LOCAL_MODEL_COST_MAP=True: litellm otherwise does a live GET to
# raw.githubusercontent.com on every `import litellm` (confirmed by runtime
# trace, see docs/backend-runtime-fetch-audit.md item 7).
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app:/app/src/knowledge \
    PYTHONSAFEPATH=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/app/.venv \
    TIKTOKEN_CACHE_DIR=/app/.cache/tiktoken \
    CUSTOM_TIKTOKEN_CACHE_DIR=/app/.cache/tiktoken \
    HF_HUB_OFFLINE=1 \
    LITELLM_LOCAL_MODEL_COST_MAP=True

WORKDIR /app/src/knowledge

# Run module
CMD uvicorn main:app --host 0.0.0.0 --port ${KNOWLEDGE_PORT:?}
