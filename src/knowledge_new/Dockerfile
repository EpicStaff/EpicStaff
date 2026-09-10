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

ENV UV_NO_BUILD=1 \
    UV_PROJECT_ENVIRONMENT=/app/src/knowledge/.venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    UV_CACHE_DIR=/tmp/uv_cache \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app/src

# Copy only dependency descriptors first (better layer caching)
COPY ./knowledge_new/pyproject.toml ./knowledge_new/uv.lock ./knowledge/

WORKDIR /app/src/knowledge

# Install dependencies into /app/src/knowledge/.venv.
# --all-groups is required: transitive-pins (and any other non-dev group) is
# not installed by default. --no-group dev deliberately excludes dev from this
# image.
RUN uv sync --frozen --no-install-project --all-groups --no-group dev

# Copy application source
COPY ./knowledge_new /app/src/knowledge
COPY ./shared /app/src/shared

# --- Stage 2: Runtime ---
FROM python:3.12.10-slim@sha256:fd95fa221297a88e1cf49c55ec1828edd7c5a428187e67b5d1805692d11588db AS runtime

# libpq-dev is required for psycopg https://www.psycopg.org/docs/install.html
RUN apt-get update && apt-get install -y libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy built app from builder
COPY --from=builder /app /app

# Add virtualenv to PATH.
# PYTHONSAFEPATH=1 stops Python from adding the process CWD to sys.path: nltk's
# import-security hook (nltk>=3.9) refuses to import `regex` while the CWD is
# searchable. That also drops the implicit path entry the app relied on to find
# its top-level modules (main, bootstrap, settings, ...), so /app/src/knowledge
# is added to PYTHONPATH explicitly; /app stays on the path for `src.shared`.
ENV PATH="/app/src/knowledge/.venv/bin:$PATH" \
    PYTHONPATH=/app:/app/src/knowledge \
    PYTHONSAFEPATH=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/app/src/knowledge/.venv

WORKDIR /app/src/knowledge

# Run module
CMD uvicorn main:app --host 0.0.0.0 --port ${KNOWLEDGE_PORT:?}
