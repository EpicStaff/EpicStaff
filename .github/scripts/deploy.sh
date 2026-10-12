#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/home/developer/EpicStaff"
COMPOSE_DIR="$APP_DIR/src"
COMPOSE_FILE="docker-compose.yaml"
NUKE_DB=${NUKE_DB:-false}
REGENERATE_ENV=${REGENERATE_ENV:-true}
IMAGE_TAG=${IMAGE_TAG:-latest}

export IMAGE_TAG

echo ">> deploy from current checkout"
echo ">> repo dir: $APP_DIR"
echo ">> image tag: $IMAGE_TAG"
echo ">> nuke database: $NUKE_DB"
echo ">> regenerate .env: $REGENERATE_ENV"

cd "$COMPOSE_DIR"

if [ "$REGENERATE_ENV" = "true" ]; then
  echo ">> regenerate .env from env.yaml"
  python3 "$APP_DIR/scripts/envtool.py" --dev
else
  echo ">> Skipping .env regeneration."
fi

DC="docker compose --env-file .env --env-file deploy.env -f $COMPOSE_FILE"

# The chat service is its own repository (EpicStaff/chat-service). A checkout of it at src/chat
# joins every compose call below; its version is CHAT_IMAGE_TAG in src/chat/.env, pulled from ghcr.
# deploy.env stays last so the server's overrides still win.
if [ -f "chat/docker-compose.epicstaff.yaml" ]; then
  if [ ! -f "chat/.env" ]; then
    echo "chat: src/chat/docker-compose.epicstaff.yaml found but src/chat/.env is missing (copy chat/.env.example)" >&2
    exit 1
  fi
  echo ">> chat service: included from src/chat ($(git -C chat rev-parse --short HEAD 2>/dev/null || echo 'not a git checkout'))"
  if ! grep -qsx 'CHAT_ENABLED=true' .env deploy.env; then
    echo "⚠️  chat runs but CHAT_ENABLED is not true in .env or deploy.env: the UI and nginx keep chat off."
  fi
  DC="docker compose --env-file .env --env-file chat/.env --env-file deploy.env -f $COMPOSE_FILE -f chat/docker-compose.epicstaff.yaml"
else
  echo ">> chat service: not installed (no src/chat)"
fi

echo ">> docker compose down"
$DC down --remove-orphans

if [ "$NUKE_DB" = "true" ]; then
  echo "⚠️  NUKE_DB is set to true. Resetting database volumes..."
  if [ -f "./nuke_db.sh" ]; then
    bash ./nuke_db.sh
  else
    docker volume rm crew_pgdata || true
    docker volume create crew_pgdata
  fi
else
  echo ">> Skipping database reset (data preserved)."
fi

echo ">> docker compose pull"
$DC pull

FAILED=0

echo ">> ensuring external volumes exist"
docker volume inspect opensearch_data >/dev/null 2>&1 || docker volume create opensearch_data

echo ">> docker compose up"
$DC up -d --remove-orphans || FAILED=1

sleep 60

echo ">> checking for crashed containers"
CRASHED=$($DC ps --status exited --format json \
  | python3 -c "import sys,json; services=[c['Service'] for c in json.load(sys.stdin) if c['Service'] != 'storage-init']; print('\n'.join(services))" 2>/dev/null || true)
if [ -n "$CRASHED" ]; then
  echo "Crashed services: $CRASHED"
  FAILED=1
fi

echo ">> last logs"
$DC logs --tail=50 --no-color || true

echo ">> docker compose ps"
$DC ps || true

if [ "$FAILED" = "1" ]; then
  echo "Deploy failed"
  exit 1
fi

echo ">> docker image prune"
docker image prune -f || true

echo "Deploy succeeded"
