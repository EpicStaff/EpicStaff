#!/bin/bash
set -e

# Get current Git branch name
BRANCH_NAME=$(git rev-parse --abbrev-ref HEAD)
if [ -z "$BRANCH_NAME" ]; then
    echo "ERROR: Could not determine Git branch. Make sure you are in a Git repository."
    exit 1
fi

# Sanitize branch name for tag (replace / with -)
SAFE_BRANCH=$(echo "$BRANCH_NAME" | tr '/' '-')

echo "Tagging for branch: $BRANCH_NAME (tag: $SAFE_BRANCH)"
echo ""

IMAGES=(
    webhook
    django_app
    realtime
    manager
    crewdb
    redis
    redis-monitor
    crew
)

for img in "${IMAGES[@]}"; do
    if docker image inspect "$img" >/dev/null 2>&1; then
        echo "Tagging $img as $img:$SAFE_BRANCH..."
        docker tag "$img" "$img:$SAFE_BRANCH"
    else
        echo "Skipping $img (image not found)"
    fi
done

echo ""
echo "All images tagged."
