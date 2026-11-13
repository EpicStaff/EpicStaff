#!/bin/bash
set -e

echo "apply migrations"
attempt=0
max_attempts=60
until piccolo migrations forwards all; do
    attempt=$(( attempt + 1 ))
    if [[ $attempt -ge $max_attempts ]]; then
        echo "ERROR: migrations still failing after $(( max_attempts * 5 ))s; giving up" >&2
        exit 1
    fi
    echo "[migrations] attempt ${attempt}/${max_attempts} failed; retrying in 5s..."
    sleep 5
done

# Exactly one manager process: the job queue, the execution registry and the queue
# deadlines all live in this process's memory. Never add workers or replicas.
exec uvicorn manager.main:app --host 0.0.0.0 --port ${SANDBOX_PORT:?} --workers 1
