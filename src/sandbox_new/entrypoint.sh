#!/bin/bash
set -e

echo "apply migrations"
piccolo migrations forwards all

exec uvicorn main:app --host 0.0.0.0 --port ${SANDBOX_PORT:?}