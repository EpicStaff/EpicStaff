#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/home/developer/EpicStaff"
COMPOSE_DIR="$APP_DIR/src"
COMPOSE_FILE="docker-compose.yaml"
NUKE_DB=${NUKE_DB:-false}

echo ">> deploy from current checkout"
echo ">> repo dir: $APP_DIR"
echo ">> nuke database: $NUKE_DB"

cd "$COMPOSE_DIR"

echo ">> docker compose down"
docker compose -f "$COMPOSE_FILE" down --remove-orphans

if [ "$NUKE_DB" = "true" ]; then
  echo "⚠️  NUKE_DB is set to true. Resetting database volumes..."
  
  if [ -f "./nuke_db.sh" ]; then
    bash ./nuke_db.sh
  else
    docker volume rm crew_pgdata || true
    docker volume create crew_pgdata
    # docker volume rm redis_data || true
  fi
else
  echo ">> Skipping database reset (data preserved)."
fi

FAILED=0

echo ">> docker compose up"
docker compose \
  --env-file .env \
  --env-file deploy.env \
  -f "$COMPOSE_FILE" \
  up --build -d --remove-orphans || FAILED=1

echo ">> last logs"
docker compose \
  --env-file .env \
  --env-file deploy.env \
  -f "$COMPOSE_FILE" \
  logs --tail=50 --no-color || true

echo ">> docker compose ps"
docker compose \
  --env-file .env \
  --env-file deploy.env \
  -f "$COMPOSE_FILE" \
  ps || true

if [ "$FAILED" = "1" ]; then
  echo "Deploy failed"
  exit 1
fi

echo ">> docker image prune"
docker image prune -f || true

echo "Deploy succeeded"
