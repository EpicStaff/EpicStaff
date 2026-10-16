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

COPY ./webhook/uv.lock ./webhook/pyproject.toml .

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

# Install ngrok via official APT repo (S3-hosted, not equinox CDN).
# The downloaded key file is imported into a throwaway keyring and exported by
# fingerprint to /etc/apt/keyrings. Exporting by fingerprint also selects any
# key that merely carries a subkey with that fingerprint, so the export could
# include a different primary key. Therefore the exported file, which is exactly
# what APT will trust, must hold one key whose primary fingerprint is the
# pinned one. That keyring is bound to this one source via
# signed-by, so it cannot vouch for any other repository (a key in the global
# APT trust directory is trusted for every source). The package version is
# pinned.
# To bump ngrok: update NGROK_VERSION to a version listed in the repo's
# dists/bookworm/main/binary-<arch>/Packages index for every architecture we
# build. If ngrok rotates its signing key the build fails at the fingerprint
# check; take the new fingerprint from
# `gpg --show-keys --with-fingerprint ngrok.asc` and confirm it against
# ngrok's published documentation before changing ngrok_key_fingerprint.
ARG NGROK_VERSION=3.39.11
RUN set -eux; \
    ngrok_key_fingerprint=F0271FCF712CF2E39901F1A30E61D3BBAAEE37FE; \
    apt-get update; \
    apt-get install -y --no-install-recommends curl gnupg; \
    install -d -m 0755 /etc/apt/keyrings; \
    GNUPGHOME="$(mktemp -d)"; export GNUPGHOME; \
    curl --fail --proto '=https' -sSL -o "$GNUPGHOME/ngrok.asc" https://ngrok-agent.s3.amazonaws.com/ngrok.asc; \
    gpg --batch --import "$GNUPGHOME/ngrok.asc"; \
    gpg --batch --export "$ngrok_key_fingerprint" > /etc/apt/keyrings/ngrok.gpg; \
    exported_keys="$(gpg --batch --with-colons --show-keys /etc/apt/keyrings/ngrok.gpg)"; \
    [ "$(printf '%s\n' "$exported_keys" | grep -c '^pub:')" = 1 ]; \
    [ "$(printf '%s\n' "$exported_keys" | awk -F: '/^fpr:/ {print $10; exit}')" = "$ngrok_key_fingerprint" ]; \
    gpgconf --kill all; \
    rm -rf "$GNUPGHOME"; \
    echo "deb [signed-by=/etc/apt/keyrings/ngrok.gpg] https://ngrok-agent.s3.amazonaws.com bookworm main" \
      > /etc/apt/sources.list.d/ngrok.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends "ngrok=${NGROK_VERSION}"; \
    apt-get clean; \
    rm -rf /var/lib/apt/lists/*

COPY ./webhook .
COPY ./shared /app/src/shared

EXPOSE 8000

CMD ["python", "run.py"]
