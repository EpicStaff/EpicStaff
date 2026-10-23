# --- Stage 1: Builder ---
FROM python:3.12.10-slim@sha256:fd95fa221297a88e1cf49c55ec1828edd7c5a428187e67b5d1805692d11588db AS builder

# Wheels only. UV_NO_BUILD=1 refuses to build source distributions, so no
# sdist's setup.py / PEP 517 backend runs at install time, meaning resolving
# never executes arbitrary Python code. A service that gains a dependency with
# no Linux wheel (psycopg2 is the audited exception elsewhere in this repo, via
# UV_NO_BINARY_PACKAGE) will fail the build rather than silently regain source
# execution.
#
# UV_PYTHON_DOWNLOADS=never is load-bearing: without it uv may fetch its own
# interpreter instead of using the digest-pinned base image above, silently
# defeating that pin.
RUN pip install --no-cache-dir uv==0.11.21

ENV UV_NO_BUILD=1 \
    UV_NO_BINARY_PACKAGE=foundation \
    UV_PROJECT_ENVIRONMENT=/app/src/.venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    UV_CACHE_DIR=/tmp/uv_cache \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app/src

RUN apt-get update && apt-get install -y ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy only dependency descriptors first (better layer caching)
COPY ./sandbox_new/pyproject.toml ./sandbox_new/uv.lock ./sandbox/
COPY ./foundation /app/src/foundation

# Install dependencies into /app/src/.venv.
# --all-groups is required: transitive-pins (and any other non-dev group) is
# not installed by default. --no-group dev deliberately excludes dev from this
# image.
RUN cd /app/src/sandbox && uv sync --frozen --no-install-project --all-groups --no-group dev

# Copy application source
COPY ./sandbox_new/ /app/src/sandbox/
COPY ./shared /app/src/shared

# --- Stage 2: Runtime ---
FROM python:3.12.10-slim@sha256:fd95fa221297a88e1cf49c55ec1828edd7c5a428187e67b5d1805692d11588db AS runtime

# git is required by the Enter/Exit Worktree Tools — the
# image previously shipped without it.
RUN apt-get update && apt-get install -y ffmpeg git \
    && rm -rf /var/lib/apt/lists/*

# uv is needed at RUNTIME, not just at build: the manager builds every per-job
# virtualenv by shelling out to `uv` (UVProvider). The builder-stage uv lives in
# the builder's system python and is not part of the copied /app, so install it
# into the runtime image too.
RUN pip install --no-cache-dir uv==0.11.21

# Create the non-root user that child subprocesses (pip, venv creation, and
# user code execution) run as.
RUN useradd --system --no-create-home --uid 1000 sandboxuser

# Copy built app from builder
COPY --from=builder /app /app

# Add virtualenv to PATH
ENV PATH="/app/src/.venv/bin:$PATH" \
    PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PICCOLO_CONF=manager.infrastructure.database.config \
    UV_PYTHON_DOWNLOADS=never \
    UV_CACHE_DIR=/tmp/uv_cache

WORKDIR /app/src/sandbox

RUN chmod +x ./entrypoint.sh
