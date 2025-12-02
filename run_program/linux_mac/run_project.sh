#!/bin/sh

# Create Docker volume
docker volume create crew_config
docker volume create crew_pgdata
docker volume create sandbox_venvs
docker volume create sandbox_executions

# Start services with Docker Compose
docker compose -f ./../docker-compose.yaml up

# Pause to keep the script open
read -p "Press [Enter] key to continue..."
