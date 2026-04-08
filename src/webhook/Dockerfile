FROM python:3.12-slim

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

EXPOSE 8000

CMD ["python", "run.py"]
