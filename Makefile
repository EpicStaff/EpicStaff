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
        dev dev-init dev-down dev-build dev-logs dev-restart dev-logs-s dev-rebuild-s rebuild-dev \
        dev-voice dev-ngrok \
        prod-setup prod-init prod prod-build prod-up start-prod prod-down prod-logs prod-voice prod-ngrok \
        clean docker-generate-certs \
        integration-test \
        gen-env check-env

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

dev-init:
	@echo "--- Creating external volumes and networks ---"
	@docker volume create sandbox_venvs      || true
	@docker volume create crew_pgdata        || true
	@docker volume create media_data         || true
	@docker volume create graph_data         || true
	@docker network create mcp-network       || true
	@echo "--- Done ---"

dev: dev-init
	@echo "--- Starting development services ---"
	@cd src && docker compose -f docker-compose.yaml -f docker-compose.dev.yaml --env-file ./.dev.env up -d

dev-down:
	@echo "--- Stopping development services ---"
	@cd src && docker compose -f docker-compose.yaml -f docker-compose.dev.yaml --env-file ./.dev.env down

dev-build:
	@echo "--- Building development services ---"
	@cd src && docker compose -f docker-compose.yaml -f docker-compose.dev.yaml --env-file ./.dev.env build

dev-logs:
	@cd src && docker compose -f docker-compose.yaml -f docker-compose.dev.yaml --env-file ./.dev.env logs -f

dev-restart:
	@cd src && docker compose -f docker-compose.yaml -f docker-compose.dev.yaml --env-file ./.dev.env restart $(s)

dev-logs-s:
	@cd src && docker compose -f docker-compose.yaml -f docker-compose.dev.yaml --env-file ./.dev.env logs -f $(s)

dev-rebuild-s:
	@cd src && docker compose -f docker-compose.yaml -f docker-compose.dev.yaml --env-file ./.dev.env up --build -d $(s)

rebuild-dev: dev-init
	@echo "--- Rebuilding development services (no cache) ---"
	@cd src && docker compose -f docker-compose.yaml -f docker-compose.dev.yaml --env-file ./.dev.env build --no-cache
	@cd src && docker compose -f docker-compose.yaml -f docker-compose.dev.yaml --env-file ./.dev.env up -d

dev-voice: dev-init
	@echo "--- Starting development services with voice (ngrok) ---"
	@cd src && docker compose -f docker-compose.yaml -f docker-compose.dev.yaml --env-file ./.dev.env --profile voice up -d

dev-ngrok: dev-init
	@echo "--- Starting ngrok tunnel ---"
	@cd src && docker compose -f docker-compose.yaml -f docker-compose.dev.yaml --env-file ./.dev.env --profile voice up ngrok

# ==========================================
# PRODUCTION Environment
# ==========================================

prod-setup:
	@echo "--- Setting up production environment ---"
	@python3 make_scripts/setup_prod.py

prod-init:
	@echo "--- Creating external volumes and networks ---"
	@docker volume create sandbox_venvs      || true
	@docker volume create crew_pgdata        || true
	@docker volume create media_data         || true
	@docker volume create graph_data         || true
	@docker network create mcp-network       || true
	@echo "--- Done ---"

PROD_ENV_ARG = $(shell test -f prod/prod.env && echo "--env-file ../prod/prod.env")

prod: prod-build prod-up

prod-build: prod-init
	@echo "--- Building production images ---"
	@cd src && docker compose -f docker-compose.yaml -f docker-compose.override.yaml --env-file ./.env $(PROD_ENV_ARG) build

prod-up: prod-init
	@echo "--- Starting production services ---"
	@cd src && docker compose -f docker-compose.yaml -f docker-compose.override.yaml --env-file ./.env $(PROD_ENV_ARG) up -d

start-prod: prod

prod-down:
	@echo "--- Stopping production services ---"
	@cd src && docker compose -f docker-compose.yaml -f docker-compose.override.yaml --env-file ./.env $(PROD_ENV_ARG) down

prod-logs:
	@cd src && docker compose -f docker-compose.yaml -f docker-compose.override.yaml --env-file ./.env $(PROD_ENV_ARG) logs -f

prod-voice:
	@echo "--- Starting production services with voice (ngrok) ---"
	@cd src && docker compose -f docker-compose.yaml -f docker-compose.override.yaml --env-file ./.env $(PROD_ENV_ARG) --profile voice up -d

prod-ngrok:
	@echo "--- Starting ngrok tunnel (production) ---"
	@cd src && docker compose -f docker-compose.yaml -f docker-compose.override.yaml --env-file ./.env $(PROD_ENV_ARG) --profile voice up ngrok

# ==========================================
# ENV FILE GENERATION
# ==========================================

gen-env:
	@echo "--- Regenerating src/.dev.env, src/debug.env, src/.env.example from src/env.yaml ---"
	@python scripts/generate_env.py

check-env:
	@echo "--- Checking generated env files match src/env.yaml ---"
	@python scripts/generate_env.py --check

# ==========================================
# UTILITIES
# ==========================================

clean:
	@echo "--- Cleaning up all environments and removing volumes ---"
	@cd src && docker compose -f docker-compose.yaml -f docker-compose.dev.yaml --env-file ./.dev.env down -v --remove-orphans
	@cd src && docker compose -f docker-compose.yaml -f docker-compose.override.yaml --env-file ./.env down -v --remove-orphans

docker-generate-certs:
	@test -n "$(domain)" || (echo "ERROR: domain is required. Usage: make docker-generate-certs domain=example.com" && exit 1)
	docker run --rm -v "$(CURDIR)/src/nginx/certs:/certs" -w /certs alpine \
		sh -c "apk add openssl && openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout privkey.pem -out fullchain.pem -subj '/CN=$(domain)'"
	@echo "SSL certificates generated for domain: $(domain)"

# ==========================================
# LOCAL DJANGO DEVELOPMENT
# ==========================================

# ==========================================
# INTEGRATION TESTS
# ==========================================

# Overridable defaults (set via env or on command line)
DJANGO_URL           ?= http://127.0.0.1:8000/api
OPENAI_KEY           ?=
DJANGO_TEST_USERNAME ?= admin
DJANGO_TEST_PASSWORD ?= admin123!

# f=<file>    — run a specific test file (default: all)
# k=<keyword> — filter tests by keyword (-k)
# ARGS=       — any extra pytest flags (e.g. ARGS="-s --tb=short")
_ITEST_FILE  = $(if $(f),$(f),)
_ITEST_KFLAG = $(if $(k),-k "$(k)",)

integration-test:
	@echo "--- Installing integration test dependencies ---"
	@pip install -r integration_tests/requirements.txt -q
	@echo "--- Running integration tests ---"
ifeq ($(OS),Windows_NT)
	@cd integration_tests && set "DJANGO_URL=$(DJANGO_URL)" && set "OPENAI_KEY=$(OPENAI_KEY)" && set "DJANGO_TEST_USERNAME=$(DJANGO_TEST_USERNAME)" && set "DJANGO_TEST_PASSWORD=$(DJANGO_TEST_PASSWORD)" && pytest $(_ITEST_FILE) $(_ITEST_KFLAG) -v $(ARGS)
else
	@cd integration_tests && \
		DJANGO_URL=$(DJANGO_URL) \
		OPENAI_KEY=$(OPENAI_KEY) \
		DJANGO_TEST_USERNAME=$(DJANGO_TEST_USERNAME) \
		DJANGO_TEST_PASSWORD=$(DJANGO_TEST_PASSWORD) \
		pytest $(_ITEST_FILE) $(_ITEST_KFLAG) -v $(ARGS)
endif

# ==========================================
# LOCAL DJANGO DEVELOPMENT
# ==========================================

django-makemigrations django-migrate django-manage django-tests: export PYTHONPATH = $(CURDIR)

django-makemigrations:
	@cd src/django_app && python manage.py makemigrations $(ARGS)

django-migrate:
	@cd src/django_app && python manage.py migrate $(ARGS)

django-manage:
	@cd src/django_app && python manage.py $(CMD)

django-tests:
	@cd src/django_app && python -m pytest $(ARGS)

# ==========================================
# LOCAL CREW DEVELOPMENT
# ==========================================

crew-tests: export PYTHONPATH = $(CURDIR)

crew-tests:
	@cd src/crew && python -m pytest $(ARGS)