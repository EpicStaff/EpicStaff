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

# Create default admin user if not exists
GENERATED_ADMIN_PASSWORD=""
if [ "${DJANGO_AUTO_CREATE_ADMIN:-0}" = "1" ]; then
  if [ -n "${DJANGO_ADMIN_USERNAME}" ] && [ -n "${DJANGO_ADMIN_PASSWORD}" ]; then
    if [ "${DJANGO_ADMIN_PASSWORD}" = "epicstaff_password" ]; then
      GENERATED_ADMIN_PASSWORD=$(python - <<'PY'
import secrets
print(secrets.token_urlsafe(18))
PY
)
      export DJANGO_ADMIN_PASSWORD="${GENERATED_ADMIN_PASSWORD}"
    fi
    echo "Ensuring default Django admin user exists..."
    python manage.py shell -c "
from django.contrib.auth import get_user_model
import os
User = get_user_model()
username = os.getenv('DJANGO_ADMIN_USERNAME')
password = os.getenv('DJANGO_ADMIN_PASSWORD')
email = os.getenv('DJANGO_ADMIN_EMAIL', '')
if username and password and not User.objects.filter(username=username).exists():
    User.objects.create_superuser(username=username, password=password, email=email)
"
  fi
fi

# Create default API key for realtime if not exists
if [ -n "${DJANGO_API_KEY}" ]; then
  echo "Ensuring default API key exists..."
  python manage.py shell -c "
import os
from tables.models.auth_models import ApiKey
raw_key = os.getenv('DJANGO_API_KEY')
if raw_key:
    prefix = raw_key[:8]
    existing = ApiKey.objects.filter(prefix=prefix, revoked_at__isnull=True).first()
    if not existing:
        key = ApiKey(name='realtime-default')
        key.set_key(raw_key)
        key.save()
"
fi

# Warn on default credentials
if [ "${DJANGO_ADMIN_USERNAME}" = "epicstaff_admin" ] || [ "${DJANGO_ADMIN_PASSWORD}" = "epicstaff_password" ] || [ "${DJANGO_API_KEY}" = "epicstaff_realtime_api_key" ]; then
  echo "WARNING: Default admin/API credentials detected. Please change them after first launch."
fi

if [ -n "${GENERATED_ADMIN_PASSWORD}" ]; then
  echo "WARNING: Generated admin password for first launch: ${GENERATED_ADMIN_PASSWORD}"
  echo "Please change it after logging in."
fi

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
  --threads "${GUNICORN_THREADS:-4}"
