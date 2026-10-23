#!/bin/bash
set -e

echo "apply migrations"
piccolo migrations forwards all

# Exactly one process: the job queue, the execution registry and the monotonic queue
# deadlines all live in this process's memory. Never add workers or replicas.
exec uvicorn main:app --host 0.0.0.0 --port ${SANDBOX_PORT:?} --workers 1