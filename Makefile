# Makefile for managing Docker volume backups, image tags, and environments
# Use cmd.exe as the shell for executing .bat files on Windows
ifeq ($(OS),Windows_NT)
	SHELL := cmd.exe
else
	SHELL := /bin/sh
endif

# IMPORTANT: This Makefile must be run from the project's root directory
# (the same directory this file is in).

# Define phony targets to ensure they run even if files with the same name exist
.PHONY: backup apply-backup stash-tags apply-tags switch start-prod docker-generate-certs dev dev-down dev-logs rebuild-dev dev-restart dev-logs-s dev-rebuild-s prod prod-down prod-logs clean help

# --- Help Menu ---

help:
	@echo "Available commands:"
	@echo "  make dev             - Start the DEVELOPMENT environment (live-reload, mapped ports)"
	@echo "  make dev-down        - Stop the DEVELOPMENT environment"
	@echo "  make dev-logs        - Tail logs for the DEVELOPMENT environment"
	@echo "  make rebuild-dev     - Rebuild and start the DEVELOPMENT environment without cache"
	@echo "  make dev-restart s=X - Restart a single dev service (e.g., make dev-restart s=manager)"
	@echo "  make dev-logs-s s=X  - Tail logs for a single dev service (e.g., make dev-logs-s s=manager)"
	@echo "  make dev-rebuild-s s=X - Rebuild and restart a single service"
	@echo "---"
	@echo "  make prod        - Start the PRODUCTION environment (Nginx, standard mode)"
	@echo "  make prod-down   - Stop the PRODUCTION environment"
	@echo "  make prod-logs   - Tail logs for the PRODUCTION environment"
	@echo "---"
	@echo "  make clean       - Stop and completely remove containers, networks, and VOLUMES (WARNING: Deletes DB data!)"
	@echo "---"
	@echo "  make backup      - Create a .tar archive of the volume"
	@echo "  make apply-backup- Restore volume data from the branch's backup file"
	@echo "  make switch b=X  - Switch full branch environment to branch X"

# --- Volume Backups ---

# Usage: make backup
# Creates a .tar archive of the volume, named after the current branch.
backup:
	@echo "--- Creating Volume Backup ---"
	@.\make_scripts\backup.bat

# Usage: make apply-backup
# Stops services and restores volume data from the branch's backup file.
apply-backup:
	@echo "--- Applying Volume Backup ---"
	@.\make_scripts\apply_backup.bat

# --- Docker Image Tagging ---

# Usage: make stash-tags
# Tags images (e.g., 'crew') with the branch name (e.g., 'crew:my-branch').
stash-tags:
	@echo "--- Stashing Image Tags ---"
	@.\make_scripts\stash_tag_images.bat

# Usage: make apply-tags
# Re-tags images from the branch tag (e.g., 'crew:my-branch') back to the original (e.g., 'crew').
apply-tags:
	@echo "--- Applying Stashed Image Tags ---"
	@.\make_scripts\apply_tag_images.bat

# --- Full Environment Switching ---

# Usage: make switch b=<branch-name>
# Stashes, backs up, checks out, and applies the new branch's state.
switch:
	@echo "--- Switching Full Branch Environment ---"
	@.\make_scripts\switch_branch.bat $(b)

# --- SSL Certificates ---

docker-generate-certs:
	docker run --rm -v "$(CURDIR)/src/nginx/certs:/certs" -w /certs alpine \
		sh -c "apk add openssl && openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout privkey.pem -out fullchain.pem -subj '/CN=localhost'"
	@echo "SSL certificates generated!"

# ==========================================
# DEVELOPMENT Environment Commands
# ==========================================

# Usage: make dev
# Starts the DEVELOPMENT environment (with live-reload and port mapping)
dev:
	@echo "--- Starting development services ---"
	@cd src && docker compose -f docker-compose.yaml -f docker-compose.dev.yaml --env-file ./.env --env-file ../dev/dev.env up -d

# Usage: make dev-down
# Stops the DEVELOPMENT environment
dev-down:
	@echo "--- Stopping development services ---"
	@cd src && docker compose -f docker-compose.yaml -f docker-compose.dev.yaml --env-file ./.env --env-file ../dev/dev.env down

dev-build:
	@echo "--- Starting building services ---"
	@cd src && docker compose -f docker-compose.yaml -f docker-compose.dev.yaml --env-file ./.env --env-file ../dev/dev.env build


# Usage: make dev-logs
# Tails logs for the DEVELOPMENT environment in real-time
dev-logs:
	@cd src && docker compose -f docker-compose.yaml -f docker-compose.dev.yaml --env-file ./.env --env-file ../dev/dev.env logs -f

# Usage: make dev-restart s=<service>
# Restarts a single dev service (e.g., make dev-restart s=manager)
dev-restart:
	@cd src && docker compose -f docker-compose.yaml -f docker-compose.dev.yaml --env-file ./.env --env-file ../dev/dev.env restart $(s)

# Usage: make dev-logs-s s=<service>
# Tails logs for a single dev service (e.g., make dev-logs-s s=manager)
dev-logs-s:
	@cd src && docker compose -f docker-compose.yaml -f docker-compose.dev.yaml --env-file ./.env --env-file ../dev/dev.env logs -f $(s)

# Usage: make dev-rebuild-s s=<service>
# Rebuilds and restarts a single service (e.g., make dev-rebuild-s s=manager)
dev-rebuild-s:
	@cd src && docker compose -f docker-compose.yaml -f docker-compose.dev.yaml --env-file ./.env --env-file ../dev/dev.env up --build -d $(s)

# Usage: make rebuild-dev
# Rebuilds and starts the DEVELOPMENT environment completely from scratch (ignores Docker cache)
rebuild-dev:
	@echo "--- Rebuilding development services ---"
	@cd src && docker compose -f docker-compose.yaml -f docker-compose.dev.yaml --env-file ./.env --env-file ../dev/dev.env build --no-cache
	@cd src && docker compose -f docker-compose.yaml -f docker-compose.dev.yaml --env-file ./.env --env-file ../dev/dev.env up -d

# ==========================================
# PRODUCTION Environment Commands
# ==========================================

# Usage: make prod (Replaces your original start-prod)
# Starts the PRODUCTION environment (standard mode with Nginx)
prod: start-prod

# Kept for backward compatibility with your existing workflow
start-prod:
	@echo "--- Starting production services ---"
	@cd src && docker compose -f docker-compose.yaml -f docker-compose.override.yaml --env-file ./.env up --build -d

# Usage: make prod-down
# Stops the PRODUCTION environment
prod-down:
	@echo "--- Stopping production services ---"
	@cd src && docker compose -f docker-compose.yaml -f docker-compose.override.yaml --env-file ./.env down

# Usage: make prod-logs
# Tails logs for the PRODUCTION environment
prod-logs:
	@cd src && docker compose -f docker-compose.yaml -f docker-compose.override.yaml --env-file ./.env logs -f

# ==========================================
# UTILITIES
# ==========================================

# Usage: make clean
# Stops and completely removes containers, networks, and VOLUMES
clean:
	@echo "--- Cleaning up all environments and removing volumes ---"
	@cd src && docker compose -f docker-compose.yaml -f docker-compose.dev.yaml --env-file ./.env --env-file ../dev/dev.env down -v --remove-orphans
	@cd src && docker compose -f docker-compose.yaml -f docker-compose.override.yaml --env-file ./.env down -v --remove-orphans