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

echo "Applying tags from branch: $BRANCH_NAME (tag: $SAFE_BRANCH)"
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
    if docker image inspect "$img:$SAFE_BRANCH" >/dev/null 2>&1; then
        echo "Tagging $img:$SAFE_BRANCH as $img..."
        docker tag "$img:$SAFE_BRANCH" "$img"
    else
        echo "Skipping $img (no branch tag found)"
    fi
done

echo ""
echo "All images re-tagged."
