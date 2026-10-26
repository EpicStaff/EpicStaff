# Gateway lab image: the stand-in decision service, the plugin backends and the test client
# (curl, jq, wrk, aiohttp). Lab only; nginx itself is the stack's pinned image.
FROM python:3.12.10-slim@sha256:fd95fa221297a88e1cf49c55ec1828edd7c5a428187e67b5d1805692d11588db
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl jq wrk \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir "aiohttp==3.14.3"
WORKDIR /lab
