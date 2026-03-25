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

# Create backups directory if it doesn't exist
mkdir -p "$BACKUP_DIR"

BACKUP_FILE="$BACKUP_DIR/${SAFE_BRANCH}.tar"
echo "Creating archive $BACKUP_FILE..."

# Show volume size so user knows how long to expect
echo "Volume size:"
docker run --rm -v "${VOLUME_NAME}":/volume_data alpine du -sh /volume_data

# Run a temporary container to create a tar archive of the volume
echo "Archiving (this may take a few minutes for large volumes)..."
docker run --rm \
    -v "${VOLUME_NAME}":/volume_data \
    -v "${BACKUP_DIR}":/backup_dir \
    alpine tar -cf "/backup_dir/${SAFE_BRANCH}.tar" -C /volume_data .

echo "Backup complete: $BACKUP_FILE"
