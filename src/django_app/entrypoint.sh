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

# First-setup bootstrap. Gated by DJANGO_AUTO_CREATE_ADMIN ('True'/'true' or
# 'False'/'false' only). When enabled, runs the same FirstSetupService that
# POST /api/auth/first-setup/ uses, so the resulting DB state is identical.
# Required when enabled: DJANGO_ADMIN_EMAIL, DJANGO_ADMIN_PASSWORD,
# DEFAULT_ORGANIZATION_NAME. Password is used as-is from env (never generated).
case "${DJANGO_AUTO_CREATE_ADMIN:-False}" in
  True|true)   AUTO_CREATE_ADMIN=1 ;;
  False|false) AUTO_CREATE_ADMIN=0 ;;
  *)
    echo "ERROR: DJANGO_AUTO_CREATE_ADMIN must be 'True' or 'False', got '${DJANGO_AUTO_CREATE_ADMIN}'." >&2
    exit 1
    ;;
esac

if [ "${AUTO_CREATE_ADMIN}" = "1" ]; then
  missing=""
  [ -z "${DJANGO_ADMIN_EMAIL}" ]      && missing="${missing} DJANGO_ADMIN_EMAIL"
  [ -z "${DJANGO_ADMIN_PASSWORD}" ]   && missing="${missing} DJANGO_ADMIN_PASSWORD"
  [ -z "${DEFAULT_ORGANIZATION_NAME}" ] && missing="${missing} DEFAULT_ORGANIZATION_NAME"

  if [ -n "${missing}" ]; then
    echo "ERROR: DJANGO_AUTO_CREATE_ADMIN=True but required var(s) missing:${missing}." >&2
    echo "ERROR: Skipping auto-bootstrap. Create the first superadmin via POST /api/auth/first-setup/." >&2
  else
    echo "Running first-setup bootstrap..."
    python manage.py shell -c "
import os
from tables.services.rbac.first_setup_service import FirstSetupService

service = FirstSetupService()
if not service.is_setup_required():
    print('Superadmin already exists — skipping bootstrap.')
else:
    service.setup(
        email=os.environ['DJANGO_ADMIN_EMAIL'],
        password=os.environ['DJANGO_ADMIN_PASSWORD'],
    )
    print(f\"Bootstrapped superadmin {os.environ['DJANGO_ADMIN_EMAIL']} in org '{os.environ['DEFAULT_ORGANIZATION_NAME']}'.\")
"
  fi
else
  echo "DJANGO_AUTO_CREATE_ADMIN=False — create the first superadmin via POST /api/auth/first-setup/."
fi

# Seed + validate the system API key from env DJANGO_API_KEY. Validation
# round-trips check_key() to prove the raw key a caller will send actually
# authenticates against what's stored. If a row with the same prefix exists
# but doesn't match, fail loud — env and DB are out of sync and silent auth
# failures would follow.
if [ -n "${DJANGO_API_KEY}" ]; then
  python manage.py shell -c "
import os, sys
from tables.models.rbac_models import ApiKey

raw_key = os.environ['DJANGO_API_KEY']
name = os.environ.get('DJANGO_API_KEY_NAME', 'system')
prefix = raw_key[:8]

existing = ApiKey.objects.filter(prefix=prefix, revoked_at__isnull=True).first()
if existing:
    if not existing.check_key(raw_key):
        print(f'ERROR: ApiKey with prefix {prefix!r} exists but does not match DJANGO_API_KEY.', file=sys.stderr)
        sys.exit(1)
    print(f'System API key {existing.name!r} already seeded and valid.')
else:
    key = ApiKey(name=name)
    key.set_key(raw_key)
    key.save()
    fetched = ApiKey.objects.get(pk=key.pk)
    if not fetched.check_key(raw_key):
        print('ERROR: Seeded API key failed check_key round-trip.', file=sys.stderr)
        sys.exit(1)
    print(f'System API key {name!r} seeded (prefix={prefix}).')
"
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
