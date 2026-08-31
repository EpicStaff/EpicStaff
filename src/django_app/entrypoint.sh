#!/bin/bash

set -e  # Exit immediately if a command exits with a non-zero status\

# Wait for Postgres to be ready
echo "Check Postgres initialization"
python manage.py check_db_init
echo "Postgres is ready."

# Run database migrations
echo "Applying database migrations..."
python manage.py migrate

# Fix PostgreSQL sequences for all tables
echo "Fixing PostgreSQL sequences..."
python manage.py fix_sequences

# Upload models (custom command)
echo "Uploading models..."
python manage.py upload_models

# Seed/rotate the singleton system API key from DJANGO_API_KEY.
echo "Seeding system API key..."
python manage.py seed_system_api_key

# Collect static files for production server
echo "Collects static"
python manage.py collectstatic --noinput

# Start Redis listener in the background
echo "Starting Redis listener..."
python manage.py listen_redis &

# Start Redis cache in the background
echo "Starting Redis caching..."
python manage.py cache_redis &

# Start the per-execution MinIO credential issuer/revoker in the background
echo "Starting storage credential issuer..."
python manage.py run_storage_credential_issuer &

# Start Django application
PORT="${DJANGO_PORT:-8000}"

echo "Starting Django server on port $PORT..."

echo "GUNICORN_RELOAD=$GUNICORN_RELOAD"
RELOAD_ARGS=""
if [ "${GUNICORN_RELOAD:-0}" = "1" ]; then
  RELOAD_ARGS="--reload"
  echo "SETUP GUNICORN_WORKERS and GUNICORN_THREADS to 1"
  export GUNICORN_WORKERS=1
  export GUNICORN_THREADS=1
fi

exec gunicorn django_app.asgi:application \
  -k uvicorn.workers.UvicornWorker \
  --bind "0.0.0.0:$PORT" \
  $RELOAD_ARGS \
  --workers "${GUNICORN_WORKERS:-1}" \
  --threads "${GUNICORN_THREADS:-4}" \
  --max-requests "${GUNICORN_MAX_REQUESTS:-1000}" \
  --max-requests-jitter "${GUNICORN_MAX_REQUESTS_JITTER:-100}"
