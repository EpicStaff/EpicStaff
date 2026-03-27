$envFile = "../debug.env"

if (Test-Path $envFile) {
    Write-Output "Loading variables from $envFile"
    Get-Content $envFile | ForEach-Object {
        if ($_ -and $_ -notmatch '^#') {
            $name, $value = $_ -split '=', 2
            if ($name -and $value) {
                [System.Environment]::SetEnvironmentVariable($name.Trim(), $value.Trim())
            }
        }
    }
} else {
    Write-Output "Warning: $envFile not found."
}

#makes `from src.shared.models import ...` work
$srcPath = Resolve-Path "../../"
$env:PYTHONPATH = "$srcPath;$($env:PYTHONPATH)"
Write-Output "PYTHONPATH set to: $env:PYTHONPATH"

$PORT = if ($env:DJANGO_PORT) { $env:DJANGO_PORT } else { "8000" }

# Run database migrations
Write-Output "Activate venv (Chose your venv)"
venv/Scripts/activate.ps1

Write-Output "Applying database migrations..."
python manage.py migrate

# Fix PostgreSQL sequences for all tables
Write-Output "Fixing PostgreSQL sequences..."
python manage.py fix_sequences

# Upload models (custom command)
Write-Output "Uploading models..."
python manage.py upload_models

# Collect static files for production server
Write-Output "Collects static"
python manage.py collectstatic --noinput

# Start Redis listener in the background
Write-Output "Starting Redis listener..."
Start-Process -NoNewWindow -FilePath "python" -ArgumentList "manage.py listen_redis"

# Start Redis cache in the background
Write-Output "Starting Redis caching..."
Start-Process -NoNewWindow -FilePath "python" -ArgumentList "manage.py cache_redis"

# Start Django application
Write-Output "Starting Django server on port $PORT..."
uvicorn django_app.asgi:application --reload --host 0.0.0.0 --port $PORT