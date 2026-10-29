# --- Stage 1: Builder ---
FROM python:3.12.10-slim@sha256:fd95fa221297a88e1cf49c55ec1828edd7c5a428187e67b5d1805692d11588db AS builder

# Wheels only (UV_NO_BUILD=1): no sdist build backend ever runs at install time.
# UV_PYTHON_DOWNLOADS=never keeps the digest-pinned interpreter above in use.
RUN pip install --no-cache-dir uv==0.11.21

# The venv lives at /app/.venv, beside the app dir (/app/src/chat), not inside it.
ENV UV_NO_BUILD=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    UV_CACHE_DIR=/tmp/uv_cache \
    UV_COMPILE_BYTECODE=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app/src/chat

# Dependency descriptors first, for layer caching. The build context is src/, so
# src/.dockerignore keeps tests, pytest.ini, venvs, caches and .env out.
COPY ./chat/pyproject.toml ./chat/uv.lock ./

RUN uv sync --frozen --no-install-project --all-groups --no-group dev

COPY ./chat /app/src/chat
COPY ./shared /app/src/shared

# --- Stage 2: Runtime ---
FROM python:3.12.10-slim@sha256:fd95fa221297a88e1cf49c55ec1828edd7c5a428187e67b5d1805692d11588db AS runtime

COPY --from=builder /app /app

# `src.shared` resolves from /app and the service's own top-level packages (`from domain...`)
# from /app/src/chat. PYTHONSAFEPATH=1 keeps the CWD off sys.path.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app:/app/src/chat \
    PYTHONSAFEPATH=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/app/.venv

# alembic.ini is read from here and finds the migrations relative to itself.
WORKDIR /app/src/chat

CMD alembic upgrade head && exec uvicorn main:app --host 0.0.0.0 --port ${CHAT_PORT:?} --workers ${CHAT_WORKERS:?}
