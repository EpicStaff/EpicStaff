from pathlib import Path

from django_app.settings import env

PLUGINS_ENABLED = env.bool("PLUGINS_ENABLED")
# Each plugin is served at <identifier>.<PLUGINS_BASE_DOMAIN>.
PLUGINS_BASE_DOMAIN = env.str("PLUGINS_BASE_DOMAIN")
# `<name>:<minisign public key>` entries; `none` lists no key. Malformed entries are reported
# by the plugins.E004 system check rather than here, so a disabled platform never fails on them.
PLUGINS_TRUSTED_SIGNING_KEYS = env.list("PLUGINS_TRUSTED_SIGNING_KEYS") or []
PLUGINS_MAX_PACKAGE_MB = env.int("PLUGINS_MAX_PACKAGE_MB")
# Days a suspended plugin keeps its data in an organization. Read as text: the plugins.E011
# start-up check reports a value outside 1-3650, so a disabled platform never fails on one
# (plugins.configuration.grace_period reads it as a number).
PLUGINS_GRACE_PERIOD_DAYS = env.str("PLUGINS_GRACE_PERIOD_DAYS")
PLUGINS_STORAGE_BUCKET = env.str("PLUGINS_STORAGE_BUCKET")
# The plugin_spa volume: written here, served read-only by nginx from the same path.
PLUGINS_SPA_ROOT = Path("/srv/plugin-spa")
# Shared secret nginx sends with every gateway check; `none` (the default) is never accepted.
PLUGINS_GATEWAY_SECRET = env.str("PLUGINS_GATEWAY_SECRET")
# The single plugin node: `seed_plugin_node` registers it under this name with this key
# (only its sha256 is stored) and this `<start>-<end>` range of Unix user ids.
PLUGINS_NODE_NAME = env.str("PLUGINS_NODE_NAME")
PLUGINS_NODE_KEY = env.str("PLUGINS_NODE_KEY")
PLUGINS_NODE_UID_RANGE = env.str("PLUGINS_NODE_UID_RANGE")
# EpicStaff's API as plugin processes reach it; written into every runtime file.
PLUGINS_INTERNAL_API_URL = env.str("PLUGINS_INTERNAL_API_URL")
# Platform maximums for what a plugin backend may ask for. Read as text: the plugins.E009
# start-up check reports a value that is not a positive integer, so a disabled platform
# never fails on one (plugins.configuration.limits reads them as numbers).
PLUGINS_MAX_PROCESS_MEMORY_MB = env.str("PLUGINS_MAX_PROCESS_MEMORY_MB")
PLUGINS_MAX_DB_CONNECTIONS = env.str("PLUGINS_MAX_DB_CONNECTIONS")
PLUGINS_MAX_STATEMENT_TIMEOUT_SECONDS = env.str("PLUGINS_MAX_STATEMENT_TIMEOUT_SECONDS")
PLUGINS_MAX_REQUESTS_PER_MINUTE = env.str("PLUGINS_MAX_REQUESTS_PER_MINUTE")
PLUGINS_MAX_PUBLIC_REQUESTS_PER_MINUTE = env.str("PLUGINS_MAX_PUBLIC_REQUESTS_PER_MINUTE")
PLUGINS_MAX_REQUEST_BODY_MB = env.str("PLUGINS_MAX_REQUEST_BODY_MB")
# Plugin development mode: a SuperAdmin may serve an installed plugin's backend and page from
# this machine's ports. Only for a deployment on the developer's own machine: the
# plugins.E012 start-up check refuses it anywhere else. Read when used, never cached.
PLUGINS_DEV_MODE = env.bool("PLUGINS_DEV_MODE")
# Port on 127.0.0.1 where a development backend reaches EpicStaff's API. Read as text: the
# plugins.E013 start-up check reports a bad value while development mode is on, so nothing
# else ever fails on one.
PLUGINS_DEV_API_PORT = env.str("PLUGINS_DEV_API_PORT")
