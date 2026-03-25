#!/bin/bash
set -e

VOLUME_NAME="crew_pgdata"
BACKUP_DIR="$(cd "$(dirname "$0")" && pwd)/backups"

# Get current Git branch name
BRANCH_NAME=$(git rev-parse --abbrev-ref HEAD)
if [ -z "$BRANCH_NAME" ]; then
    echo "ERROR: Could not determine Git branch. Make sure you are in a Git repository."
    exit 1
fi

# Sanitize branch name for filename (replace / with -)
SAFE_BRANCH=$(echo "$BRANCH_NAME" | tr '/' '-')

echo "Branch: $BRANCH_NAME"
echo "Volume: $VOLUME_NAME"

BACKUP_FILE="$BACKUP_DIR/${SAFE_BRANCH}.tar"

# Check if backup file exists
if [ ! -f "$BACKUP_FILE" ]; then
    echo "ERROR: Backup file not found: $BACKUP_FILE"
    exit 1
fi

# Stop services
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
echo "Stopping services (docker compose down)..."
docker compose --project-directory "$PROJECT_ROOT/src" down || echo "Warning: 'docker compose down' had issues."

# Restore data
echo "Restoring data from $BACKUP_FILE..."
echo "WARNING: This will DELETE all current data in volume $VOLUME_NAME and replace it."

docker run --rm \
    -v "${VOLUME_NAME}":/volume_data \
    -v "${BACKUP_DIR}":/backup_dir \
    alpine sh -c "rm -rf /volume_data/* && tar -xf /backup_dir/${SAFE_BRANCH}.tar -C /volume_data"

echo "Restore complete."
