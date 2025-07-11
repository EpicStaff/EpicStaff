#!/bin/bash

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
exec uvicorn django_app.asgi:application --reload --host 0.0.0.0 --port 8000
