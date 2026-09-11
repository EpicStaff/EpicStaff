#!/bin/sh
set -e

AUDIT_TRAIL_ENABLED_LOWER=$(echo "$AUDIT_TRAIL_ENABLED" | tr '[:upper:]' '[:lower:]')
if [ "$AUDIT_TRAIL_ENABLED_LOWER" != "true" ]; then
    echo "AUDIT_TRAIL_ENABLED is not true - auditor has nothing to do, exiting."
    exit 0
fi

python -m app.index_setup.runner

exec python run.py