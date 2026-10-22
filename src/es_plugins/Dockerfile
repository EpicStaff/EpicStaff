# The plugin node: the root launcher (PID 1) and the agent (UID 10000) on Python 3.12.10, plus
# the CPython builds plugin backends run on. Build context: src/ (see docker-compose.yaml).

# Plugin interpreters, taken whole from the official images. Both are Debian bookworm builds,
# like the runtime base below, so they find the same glibc (2.36, enough for manylinux_2_28
# wheels) and system libraries; each binary's rpath ($ORIGIN/../lib) lets it run from
# /opt/plugin-python/<version>. No compiler is installed anywhere: plugins bring wheels only.
FROM python:3.13.16-slim-bookworm@sha256:a1165e272e578941b84abc79e4ab38a0305cd12803a5c4247979ac7655f4d641 AS plugin-python-3-13
FROM python:3.12.10-slim@sha256:fd95fa221297a88e1cf49c55ec1828edd7c5a428187e67b5d1805692d11588db AS plugin-python-3-12

# pg_dump and pg_restore of plugins_db's major version (17), with their libpq, for the backups
# taken before upgrades. From the official image's bookworm build: the node's base is bookworm, so
# they find the same glibc (plugins_db runs the trixie build of the same release, which needs a
# newer one). This digest moves together with plugins_db's image in docker-compose.yaml.
FROM postgres:17.11-bookworm@sha256:858bb5e98eed02eb8cafbcdc007f9a65d1b613972028944a8ec2133ccaf80d27 AS postgres-client
RUN mkdir -p /opt/postgresql-client/17/bin /opt/postgresql-client/17/lib \
    && cp /usr/lib/postgresql/17/bin/pg_dump /usr/lib/postgresql/17/bin/pg_restore /opt/postgresql-client/17/bin/ \
    && cp -L "$(ldd /usr/lib/postgresql/17/bin/pg_dump | awk '$1 == "libpq.so.5" { print $3 }')" \
        /opt/postgresql-client/17/lib/libpq.so.5

# --- Builder: the agent's venv ---
FROM python:3.12.10-slim@sha256:fd95fa221297a88e1cf49c55ec1828edd7c5a428187e67b5d1805692d11588db AS builder

# Wheels only (UV_NO_BUILD=1): no sdist build backend runs. epicstaff-plugin (src/plugin_sdk) is
# the first-party path dependency without a wheel, the one audited exception, as in
# django_app's image. UV_PYTHON_DOWNLOADS=never keeps the digest-pinned interpreter in use.
RUN pip install --no-cache-dir uv==0.11.21

ENV UV_NO_BUILD=1 \
    UV_NO_BINARY_PACKAGE=epicstaff-plugin \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    UV_CACHE_DIR=/tmp/uv_cache \
    UV_COMPILE_BYTECODE=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app/src/es_plugins

# Dependency descriptors first, for layer caching. "../plugin_sdk" in [tool.uv.sources]
# resolves to /app/src/plugin_sdk; it is installed editable, so the runtime stage keeps it.
COPY ./es_plugins/pyproject.toml ./es_plugins/uv.lock ./
COPY ./plugin_sdk/pyproject.toml ./plugin_sdk/uv.lock /app/src/plugin_sdk/
COPY ./plugin_sdk/epicstaff_plugin /app/src/plugin_sdk/epicstaff_plugin

RUN uv sync --frozen --no-install-project --all-groups --no-group dev

# Only the package: the lab and the tests stay out of the image.
COPY ./es_plugins/es_plugins /app/src/es_plugins/es_plugins
COPY ./shared /app/src/shared

# --- Runtime ---
FROM python:3.12.10-slim@sha256:fd95fa221297a88e1cf49c55ec1828edd7c5a428187e67b5d1805692d11588db AS runtime

# Before the COPYs, so a change of the code reuses this layer. nftables for the per-plugin
# connection caps the entrypoint installs; setpriv (util-linux, in the base image) starts the
# launcher without the capabilities that installed them; libldap (with libsasl2) is the one
# library of the PostgreSQL client's libpq the base image lacks.
RUN apt-get update \
    && apt-get install -y --no-install-recommends nftables libldap-2.5-0 \
    && rm -rf /var/lib/apt/lists/* \
    && nft --version \
    && command -v setpriv

COPY --from=plugin-python-3-13 /usr/local/ /opt/plugin-python/3.13/
COPY --from=plugin-python-3-12 /usr/local/ /opt/plugin-python/3.12/
COPY --from=postgres-client /opt/postgresql-client/ /opt/postgresql-client/
COPY --from=builder /app /app

# The client runs here, and is plugins_db's major version: the agent runs it with this
# LD_LIBRARY_PATH (es_plugins.database.postgres_client), and pg_dump refuses a newer server.
RUN export LD_LIBRARY_PATH=/opt/postgresql-client/17/lib \
    && ! ldd /opt/postgresql-client/17/bin/pg_dump /opt/postgresql-client/17/bin/pg_restore | grep -q "not found" \
    && /opt/postgresql-client/17/bin/pg_dump --version | grep -q "(PostgreSQL) 17\." \
    && /opt/postgresql-client/17/bin/pg_restore --version | grep -q "(PostgreSQL) 17\."

# The node's volume is mounted at /var/lib/es_plugins; the launcher sets the owners and modes
# at start-up. The egress policy volume is mounted below /var/lib/es_plugins_egress, which only
# root and the agent's group may pass through: no plugin UID reads the proxy's policy.
RUN mkdir -p /var/lib/es_plugins \
    && install -d -m 0710 -o root -g 10000 /var/lib/es_plugins_egress

COPY --chmod=0755 ./es_plugins/entrypoint.sh /usr/local/bin/es-plugins-entrypoint

# `src.shared` resolves from /app and the service's own package from /app/src/es_plugins.
# PYTHONSAFEPATH=1 keeps the working directory off sys.path.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app:/app/src/es_plugins \
    PYTHONSAFEPATH=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/app/.venv

WORKDIR /app/src/es_plugins

# The entrypoint installs the connection caps, then execs the launcher, which stays PID 1, reaps
# orphans and starts the agent.
ENTRYPOINT ["/usr/local/bin/es-plugins-entrypoint"]
