FROM python:3.12.10-slim@sha256:fd95fa221297a88e1cf49c55ec1828edd7c5a428187e67b5d1805692d11588db

WORKDIR /app/src/webhook

# Wheels only. UV_NO_BUILD=1 refuses to build source distributions, so no
# sdist's setup.py / PEP 517 backend runs at install time, meaning resolving
# never executes arbitrary Python code. No exception is needed here -- every
# package this service resolves has a Linux wheel.
#
# UV_PYTHON_DOWNLOADS=never is load-bearing: without it uv may fetch its own
# interpreter instead of using the digest-pinned base image above, silently
# defeating that pin.
# This image stays single-stage: ngrok below is installed via APT and used
# at RUNTIME, so splitting into builder/runtime stages would risk relocating
# that dependency out of the final image. As a consequence, uv itself is never
# discarded and remains in the final image. The multi-stage services don't
# have this property, since their builder stage (and uv with it) is discarded.
RUN pip install --no-cache-dir uv==0.11.21

ENV UV_NO_BUILD=1 \
    UV_PROJECT_ENVIRONMENT=/app/src/.venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    UV_CACHE_DIR=/tmp/uv_cache \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

COPY ./webhook/uv.lock ./webhook/pyproject.toml ./webhook/.python-version .

# Install dependencies into /app/src/.venv.
# --all-groups is required: transitive-pins (and any other non-dev group) is
# not installed by default. --no-group dev --no-group tests deliberately
# excludes dev and tests from this image.
#
# This image has no stage boundary to discard the uv cache automatically, so
# it must be removed explicitly here.
RUN uv sync --frozen --no-install-project --all-groups --no-group dev --no-group tests && \
    rm -rf /tmp/uv_cache

# Add virtualenv to PATH so the existing CMD keeps resolving python from it.
ENV PATH="/app/src/.venv/bin:$PATH"

# Install ngrok via official APT repo (S3-hosted, not equinox CDN)
RUN apt-get update && apt-get install -y curl apt-transport-https gnupg && \
    curl -sSL https://ngrok-agent.s3.amazonaws.com/ngrok.asc \
      | tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null && \
    echo "deb https://ngrok-agent.s3.amazonaws.com buster main" \
      | tee /etc/apt/sources.list.d/ngrok.list && \
    apt-get update && apt-get install -y ngrok && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

COPY ./webhook .
COPY ./shared /app/src/shared

EXPOSE 8000

CMD ["python", "run.py"]
