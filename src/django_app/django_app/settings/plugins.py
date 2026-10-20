from pathlib import Path

from django_app.settings import env

PLUGINS_ENABLED = env.bool("PLUGINS_ENABLED")
# Each plugin is served at <identifier>.<PLUGINS_BASE_DOMAIN>.
PLUGINS_BASE_DOMAIN = env.str("PLUGINS_BASE_DOMAIN")
# `<name>:<minisign public key>` entries; `none` lists no key. Malformed entries are reported
# by the plugins.E004 system check rather than here, so a disabled platform never fails on them.
PLUGINS_TRUSTED_SIGNING_KEYS = env.list("PLUGINS_TRUSTED_SIGNING_KEYS") or []
PLUGINS_MAX_PACKAGE_MB = env.int("PLUGINS_MAX_PACKAGE_MB")
PLUGINS_STORAGE_BUCKET = env.str("PLUGINS_STORAGE_BUCKET")
# The plugin_spa volume: written here, served read-only by nginx from the same path.
PLUGINS_SPA_ROOT = Path("/srv/plugin-spa")
