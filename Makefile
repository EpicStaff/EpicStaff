# Makefile for managing Docker volume backups, image tags, and environments
# Use cmd.exe as the shell for executing .bat files on Windows
ifeq ($(OS),Windows_NT)
	SHELL := cmd.exe
else
	SHELL := /bin/sh
endif

# IMPORTANT: This Makefile must be run from the project's root directory
# (the same directory this file is in).

.DEFAULT_GOAL := help
.PHONY: help \
        backup apply-backup stash-tags apply-tags switch \
        dev dev-down dev-build dev-logs dev-restart dev-logs-s dev-rebuild-s rebuild-dev \
        prod start-prod prod-down prod-logs \
        clean docker-generate-certs

# --- Help ---

help:
	@type make_scripts\help.txt

# ==========================================
# BRANCH SWITCHING
# ==========================================

backup:
	@echo "--- Creating Volume Backup ---"
ifeq ($(OS),Windows_NT)
	@.\make_scripts\backup.bat
else
	@./make_scripts/backup.sh
endif

apply-backup:
	@echo "--- Applying Volume Backup ---"
ifeq ($(OS),Windows_NT)
	@.\make_scripts\apply_backup.bat
else
	@./make_scripts/apply_backup.sh
endif

stash-tags:
	@echo "--- Stashing Image Tags ---"
ifeq ($(OS),Windows_NT)
	@.\make_scripts\stash_tag_images.bat
else
	@./make_scripts/stash_tag_images.sh
endif

apply-tags:
	@echo "--- Applying Stashed Image Tags ---"
ifeq ($(OS),Windows_NT)
	@.\make_scripts\apply_tag_images.bat
else
	@./make_scripts/apply_tag_images.sh
endif

switch:
	@echo "--- Switching Full Branch Environment ---"
ifeq ($(OS),Windows_NT)
	@.\make_scripts\switch_branch.bat $(b)
else
	@./make_scripts/switch_branch.sh $(b)
endif

# ==========================================
# DEVELOPMENT Environment
# ==========================================

dev:
	@echo "--- Starting development services ---"
	@cd src && docker compose -f docker-compose.yaml -f docker-compose.dev.yaml --env-file ./.env --env-file ../dev/dev.env up -d

dev-down:
	@echo "--- Stopping development services ---"
	@cd src && docker compose -f docker-compose.yaml -f docker-compose.dev.yaml --env-file ./.env --env-file ../dev/dev.env down

dev-build:
	@echo "--- Building development services ---"
	@cd src && docker compose -f docker-compose.yaml -f docker-compose.dev.yaml --env-file ./.env --env-file ../dev/dev.env build

dev-logs:
	@cd src && docker compose -f docker-compose.yaml -f docker-compose.dev.yaml --env-file ./.env --env-file ../dev/dev.env logs -f

dev-restart:
	@cd src && docker compose -f docker-compose.yaml -f docker-compose.dev.yaml --env-file ./.env --env-file ../dev/dev.env restart $(s)

dev-logs-s:
	@cd src && docker compose -f docker-compose.yaml -f docker-compose.dev.yaml --env-file ./.env --env-file ../dev/dev.env logs -f $(s)

dev-rebuild-s:
	@cd src && docker compose -f docker-compose.yaml -f docker-compose.dev.yaml --env-file ./.env --env-file ../dev/dev.env up --build -d $(s)

rebuild-dev:
	@echo "--- Rebuilding development services (no cache) ---"
	@cd src && docker compose -f docker-compose.yaml -f docker-compose.dev.yaml --env-file ./.env --env-file ../dev/dev.env build --no-cache
	@cd src && docker compose -f docker-compose.yaml -f docker-compose.dev.yaml --env-file ./.env --env-file ../dev/dev.env up -d

# ==========================================
# PRODUCTION Environment
# ==========================================

prod: start-prod

start-prod:
	@echo "--- Starting production services ---"
	@cd src && docker compose -f docker-compose.yaml -f docker-compose.override.yaml --env-file ./.env up --build -d

prod-down:
	@echo "--- Stopping production services ---"
	@cd src && docker compose -f docker-compose.yaml -f docker-compose.override.yaml --env-file ./.env down

prod-logs:
	@cd src && docker compose -f docker-compose.yaml -f docker-compose.override.yaml --env-file ./.env logs -f

# ==========================================
# UTILITIES
# ==========================================

clean:
	@echo "--- Cleaning up all environments and removing volumes ---"
	@cd src && docker compose -f docker-compose.yaml -f docker-compose.dev.yaml --env-file ./.env --env-file ../dev/dev.env down -v --remove-orphans
	@cd src && docker compose -f docker-compose.yaml -f docker-compose.override.yaml --env-file ./.env down -v --remove-orphans

docker-generate-certs:
	docker run --rm -v "$(CURDIR)/src/nginx/certs:/certs" -w /certs alpine \
		sh -c "apk add openssl && openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout privkey.pem -out fullchain.pem -subj '/CN=localhost'"
	@echo "SSL certificates generated!"

# ==========================================
# LOCAL DJANGO DEVELOPMENT
# ==========================================

django-makemigrations django-migrate django-manage: export PYTHONPATH = $(CURDIR)

django-makemigrations:
	@cd src/django_app && python manage.py makemigrations $(ARGS)

django-migrate:
	@cd src/django_app && python manage.py migrate $(ARGS)

django-manage:
	@cd src/django_app && python manage.py $(CMD)