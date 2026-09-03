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

# Start Django application
PORT="${DJANGO_PORT}"

echo "Starting Django server on port $PORT..."

echo "DJANGO_SGI_RELOAD=$DJANGO_SGI_RELOAD"
RELOAD_ARGS=""
if [ "${DJANGO_SGI_RELOAD:-0}" = "1" ]; then
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
