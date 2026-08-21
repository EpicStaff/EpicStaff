FROM python:3.12-slim@sha256:2c941e860699f878900b0edc2403613c234d4b32eda3cc9fa7036991a2a63c4a

WORKDIR /app/src/webhook

RUN pip install poetry

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_NO_INTERACTION=1 \
    PYTHONPATH=/app

COPY ./webhook/poetry.lock ./webhook/pyproject.toml .
RUN poetry config virtualenvs.create false && \
    poetry install --no-root --no-interaction && \
    rm -rf /root/.cache

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

# Create non-root user for runtime (mirrors agent/Dockerfile.agent).
RUN groupadd --system --gid 1000 app \
 && useradd  --system --uid 1000 --gid app --create-home --shell /usr/sbin/nologin app \
 && chown -R app:app /app

ENV HOME=/home/app

EXPOSE 8000

# This service mounts no volumes, so it can drop to a non-root user outright
# rather than going through docker/entrypoint-nonroot.sh.
USER app

CMD ["python", "run.py"]