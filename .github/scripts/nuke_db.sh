#!/usr/bin/env bash
set -euo pipefail

COMPOSE_DIR="/home/developer/EpicStaff/src"
COMPOSE_FILE="docker-compose.yaml"

echo "⚠️  RUNNING DATABASE RESET..."
cd "$COMPOSE_DIR"

docker compose -f "$COMPOSE_FILE" stop crewdb redis || true
docker volume rm crew_pgdata redis_data || true

docker volume create crew_pgdata
docker volume create redis_data

echo "✅ Database and Redis volumes have been reset."