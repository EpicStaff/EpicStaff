#!/bin/bash

set -e  # Exit immediately if a command exits with a non-zero status\

# >>> env_bool
# Strict boolean environment flag, accepting exactly the values Env.bool accepts
# (src/shared/envtools.py). Copied verbatim into every script that needs it;
# .github/scripts/check_env_conventions.py fails CI if the copies or the values drift.
# Usage: if env_bool NAME [DEFAULT]; then ...; fi
# Returns 0 for true and 1 for false. DEFAULT applies only when NAME is unset.
# An unset NAME without DEFAULT, or any other value, exits the script with 64.
env_bool() {
  eval "env_bool_is_set=\${$1+set}"
  if [ -n "$env_bool_is_set" ]; then
    eval "env_bool_value=\${$1}"
  elif [ $# -ge 2 ]; then
    env_bool_value=$2
  else
    echo "ERROR: environment variable $1 is not set." >&2
    exit 64
  fi
  case "$(printf '%s' "$env_bool_value" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | tr '[:upper:]' '[:lower:]')" in
    1|on|t|true|y|yes) return 0 ;;
    0|f|false|n|no|off) return 1 ;;
  esac
  echo "ERROR: environment variable $1='$env_bool_value' is not a boolean. Use one of 1, on, t, true, y, yes for true or 0, f, false, n, no, off for false (case-insensitive)." >&2
  exit 64
}
# <<< env_bool

# Wait for Postgres to be ready
echo "Check Postgres initialization"
python manage.py check_db_init
echo "Postgres is ready."

# Run database migrations
echo "Applying database migrations..."
python manage.py migrate

# Right after migrate, while nothing else alters the schema: a grant racing a migration
# on the same table fails. crewdb has already created the roles.
echo "Granting service database roles their table privileges..."
python manage.py apply_service_grants

# Reconcile built-in roles with rbac/access/builtin_roles.json; an invalid file stops startup.
echo "Seeding built-in roles..."
python manage.py seed_builtin_roles

# Backfill MinIO storage credentials for any organization missing them
echo "Backfilling org storage credentials..."
python manage.py backfill_org_storage_credentials

# Fix PostgreSQL sequences for all tables
echo "Fixing PostgreSQL sequences..."
python manage.py fix_sequences

# Upload models (custom command)
echo "Uploading models..."
python manage.py upload_models

# Seed/rotate the singleton system API key from DJANGO_API_KEY.
echo "Seeding system API key..."
python manage.py seed_system_api_key

# Register the plugin node from PLUGINS_NODE_*; a no-op while plugins are off.
echo "Seeding plugin node..."
python manage.py seed_plugin_node

# Collect static files for production server
echo "Collects static"
python manage.py collectstatic --noinput

# The Redis workers share this container with the web server, so their own
# connection pool is set per process here. Each queries from a single thread:
# one connection, plus one spare.

# Start Redis listener in the background
echo "Starting Redis listener..."
DJANGO_DB_POOL_MIN_SIZE=1 DJANGO_DB_POOL_MAX_SIZE=2 python manage.py listen_redis &

# Start Redis cache in the background
echo "Starting Redis caching..."
DJANGO_DB_POOL_MIN_SIZE=1 DJANGO_DB_POOL_MAX_SIZE=2 python manage.py cache_redis &

# Start session callback sender in the background
echo "Starting session callback sender..."
python manage.py send_session_callbacks &

# Start Django application
PORT="${DJANGO_PORT}"

echo "Starting Django server on port $PORT..."

# Local-run-only switch for auto-reload; deliberately not declared in env.yaml or compose.
echo "DJANGO_SGI_RELOAD=$DJANGO_SGI_RELOAD"
RELOAD_ARGS=""
if env_bool DJANGO_SGI_RELOAD false; then
  RELOAD_ARGS="--reload"
  echo "SETUP DJANGO_SGI_WORKERS and DJANGO_SGI_THREADS to 1"
  export DJANGO_SGI_WORKERS=1
  export DJANGO_SGI_THREADS=1
fi

exec gunicorn django_app.asgi:application \
  -k uvicorn.workers.UvicornWorker \
  --bind "0.0.0.0:$PORT" \
  $RELOAD_ARGS \
  --workers "${DJANGO_SGI_WORKERS:-1}" \
  --threads "${DJANGO_SGI_THREADS:-4}" \
  --max-requests "${DJANGO_SGI_MAX_REQUESTS:-1000}" \
  --max-requests-jitter "${DJANGO_SGI_MAX_REQUESTS_JITTER:-100}"
