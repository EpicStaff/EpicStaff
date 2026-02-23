#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/home/developer/EpicStaff"
COMPOSE_DIR="$APP_DIR/src"
COMPOSE_FILE="docker-compose.deploy.yaml"

echo ">> deploy from current checkout"
echo ">> repo dir: $APP_DIR"

cd "$COMPOSE_DIR"

echo ">> docker compose down"
docker compose -f "$COMPOSE_FILE" down --remove-orphans

echo ">> docker volume rm crew_pgdata"
docker volume rm crew_pgdata || true

echo ">> docker volume create crew_pgdata"
docker volume create crew_pgdata

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
