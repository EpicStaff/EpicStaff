#!/bin/bash

FILE="../debug.env"
if [ -f "$FILE" ]; then
    echo "Loading variables from $FILE"
    set -a
    source "$FILE"
    set +a
else
    echo "Warning: $FILE not found, using defaults."
fi

PORT="${DJANGO_PORT:-8000}"

# Run database migrations
echo "Applying database migrations..."
python manage.py migrate

# Fix PostgreSQL sequences for all tables
echo "Fixing PostgreSQL sequences..."
python manage.py fix_sequences

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
exec uvicorn django_app.asgi:application --reload --host 0.0.0.0 --port "$PORT"