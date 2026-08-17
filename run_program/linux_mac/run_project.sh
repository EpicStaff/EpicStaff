#!/bin/sh

# Idempotent: generates the signing keys on first run, preserves them afterwards.
sh "$(dirname "$0")/create_env.sh"

# Create Docker volume
docker volume create crew_config
docker volume create crew_pgdata
docker volume create sandbox_venvs

# Start services with Docker Compose.
docker compose --env-file ./../.env --env-file ./../.signing.env \
  -f ./../docker-compose.yaml up

# Pause to keep the script open
read -p "Press [Enter] key to continue..."
