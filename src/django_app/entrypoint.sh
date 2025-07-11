#!/bin/bash

set -e  # Exit immediately if a command exits with a non-zero status\

# Wait for Postgres to be ready
echo "Check Postgres initialization"
python manage.py check_db_init
echo "Postgres is ready."

# Run database migrations
echo "Applying database migrations..."
python manage.py migrate

# Upload models (custom command)
echo "Uploading models..."
python manage.py upload_models

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
echo "Starting Django server..."
exec gunicorn django_app.asgi:application \
  -k uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000 \
  --workers "${GUNICORN_WORKERS:-1}" \
  --threads "${GUNICORN_THREADS:-4}"
