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

# Start the daily purge consumer in the background (recycle bin and voice-recording retention);
# manager requests the purge daily
echo "Starting recycle bin purge consumer..."
DJANGO_DB_POOL_MIN_SIZE=1 DJANGO_DB_POOL_MAX_SIZE=2 python manage.py run_recycle_bin_purge &

# Start session callback sender in the background
echo "Starting session callback sender..."
python manage.py send_session_callbacks &

# Start Django application
PORT="${DJANGO_PORT}"

# No default: compose always passes it, and epicstaff-nginx renders one upstream server per
# Django server from the same value, so a guess here could disagree with nginx. A value that
# starts no server would leave the container up with nothing answering.
web_server_count=${DJANGO_SGI_WORKERS-}
case "$web_server_count" in
  '')
    echo "ERROR: environment variable DJANGO_SGI_WORKERS is not set or empty." >&2
    exit 64
    ;;
  *[!0-9]* | 0*)
    echo "ERROR: DJANGO_SGI_WORKERS='$web_server_count' is not a whole number of 1 or more." >&2
    exit 64
    ;;
esac

# No defaults either: compose always passes both, and their defaults live in env.yaml.
for recycle_variable in DJANGO_SGI_MAX_REQUESTS DJANGO_SGI_MAX_REQUESTS_JITTER; do
  if [ -z "${!recycle_variable-}" ]; then
    echo "ERROR: environment variable $recycle_variable is not set or empty." >&2
    exit 64
  fi
done

# Local-run-only switch for auto-reload; deliberately not declared in env.yaml or compose.
echo "DJANGO_SGI_RELOAD=$DJANGO_SGI_RELOAD"
RELOAD_ARGS=""
if env_bool DJANGO_SGI_RELOAD false; then
  RELOAD_ARGS="--reload"
  if [ "$web_server_count" != 1 ]; then
    echo "WARNING: DJANGO_SGI_RELOAD starts one Django server, but DJANGO_SGI_WORKERS=$web_server_count: epicstaff-nginx's upstream ports from $((PORT + 2)) up will refuse connections. Set DJANGO_SGI_WORKERS=1." >&2
  fi
  echo "SETUP DJANGO_SGI_WORKERS and DJANGO_SGI_THREADS to 1"
  export DJANGO_SGI_WORKERS=1
  export DJANGO_SGI_THREADS=1
  web_server_count=1
fi

echo "Starting $web_server_count Django server(s): shared port $PORT, own ports from $((PORT + 1))..."

# One single-worker server per process. Workers sharing one listening socket split a burst
# unevenly: the first to wake accepts nearly every waiting connection (asyncio accepts up to the
# backlog per wake-up), so one worker queues most of the burst while the others sit idle.
# Each server listens on two ports:
#   - its own, DJANGO_PORT + 1 + its index, which epicstaff-nginx balances across (least_conn
#     over the servers 19-render-django-upstream.envsh renders from the same DJANGO_SGI_WORKERS);
#   - DJANGO_PORT, shared by every server through SO_REUSEPORT, for the services that call
#     django_app directly (crew, realtime, chat) and the healthcheck: the kernel spreads their
#     connections across the servers' sockets.
web_server_pids=()
stop_requested=false
# Installed before the first server starts. A stop from here on passes to the servers already
# running, and no server starts after it.
trap 'stop_requested=true; kill -TERM "${web_server_pids[@]}" 2>/dev/null || true' TERM INT
for ((web_server_index = 0; web_server_index < web_server_count; web_server_index++)); do
  if [ "$stop_requested" = true ]; then
    break
  fi
  gunicorn django_app.asgi:application \
    -k uvicorn.workers.UvicornWorker \
    --reuse-port \
    --bind "0.0.0.0:$PORT" \
    --bind "0.0.0.0:$((PORT + 1 + web_server_index))" \
    $RELOAD_ARGS \
    --workers 1 \
    --threads "${DJANGO_SGI_THREADS:-4}" \
    --max-requests "$DJANGO_SGI_MAX_REQUESTS" \
    --max-requests-jitter "$DJANGO_SGI_MAX_REQUESTS_JITTER" &
  web_server_pids+=("$!")
done

# The servers are children of this shell, which is PID 1: the trap above passes Docker's stop
# signal on to them. When any server exits, stop the rest and exit with its status, so Docker
# restarts the container (restart: unless-stopped) instead of nginx sending requests to a dead
# port. After a stop during the start loop, skip the wait. The signal goes out again, because a
# server started between the signal and its PID being recorded did not get it, and the script
# exits once every server it started has stopped.
web_server_status=0
if [ "$stop_requested" = false ]; then
  wait -n "${web_server_pids[@]}" || web_server_status=$?
fi
# Without a PID, kill would fail and wait would wait for the Redis workers too.
if [ "${#web_server_pids[@]}" -gt 0 ]; then
  kill -TERM "${web_server_pids[@]}" 2>/dev/null || true
  wait "${web_server_pids[@]}" || true
fi
exit "$web_server_status"
