# --- Stage 1: Builder ---
FROM python:3.12.16-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b AS builder

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
FROM python:3.12.16-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b AS runtime

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

# Code and venv stay root-owned (read-only for the runtime user).
RUN groupadd --system --gid 1000 app \
 && useradd --system --uid 1000 --gid app --create-home --shell /usr/sbin/nologin app

USER app

CMD alembic upgrade head && exec uvicorn main:app --host 0.0.0.0 --port ${CHAT_PORT:?} --workers ${CHAT_WORKERS:?}
