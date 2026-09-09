# Makefile for managing Docker volume backups, image tags, and environments
# Use cmd.exe as the shell for executing .bat files on Windows
ifeq ($(OS),Windows_NT)
	SHELL := cmd.exe
else
	SHELL := /bin/sh
endif

# IMPORTANT: This Makefile must be run from the project's root directory
# (the same directory this file is in).

# Single compose file + single env file for every environment.
COMPOSE := docker compose -f docker-compose.yaml --env-file ./.env

# Guard for single-service targets: warn (but still proceed) when s=<service>
# is missing, in which case docker compose acts on ALL services. A make
# function (not shell `test`) so it also works under cmd.exe on Windows.
warn-no-s = $(if $(strip $(s)),,$(warning no s=<service> given - applying to ALL services))

.DEFAULT_GOAL := help
.PHONY: help \
        backup apply-backup stash-tags apply-tags switch \
        init ensure-env up down build rebuild rebuild-s restart logs logs-s \
        clean docker-generate-certs \
        django-makemigrations django-migrate django-manage django-tests crew-tests agent-tests

# --- Help ---

help:
ifeq ($(OS),Windows_NT)
	@type make_scripts\help.txt
else
	@cat make_scripts/help.txt
endif

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
# ENVIRONMENT
# ==========================================

init:
	@echo "--- Creating external volumes and networks ---"
	@docker volume create sandbox_venvs      || true
	@docker volume create crew_pgdata        || true
	@docker volume create media_data         || true
	@docker volume create graph_data         || true
	@docker network create mcp-network       || true
	@echo "--- Done ---"

# Create src/.env from the tracked template on first run. src/.env is gitignored,
# so a fresh clone has none; every target that starts containers depends on this.
ensure-env:
ifeq ($(OS),Windows_NT)
	@if not exist src\.env ( echo --- Creating src\.env from src\.env.example --- & copy src\.env.example src\.env >NUL )
else
	@test -f src/.env || (echo "--- Creating src/.env from src/.env.example ---" && cp src/.env.example src/.env)
endif

up: init ensure-env
	@echo "--- Starting services ---"
	@cd src && $(COMPOSE) up -d

down:
	@echo "--- Stopping services ---"
	@cd src && $(COMPOSE) down

build: init ensure-env
	@echo "--- Building images ---"
	@cd src && $(COMPOSE) build

rebuild: init ensure-env
	@echo "--- Rebuilding all services (no cache) ---"
	@cd src && $(COMPOSE) build --no-cache
	@cd src && $(COMPOSE) up -d

rebuild-s: ensure-env
	$(warn-no-s)
	@echo "--- Rebuilding and restarting a single service (uses cache) ---"
	@cd src && $(COMPOSE) up --build -d $(s)

restart:
	$(warn-no-s)
	@cd src && $(COMPOSE) restart $(s)

logs:
	@cd src && $(COMPOSE) logs -f

logs-s:
	$(warn-no-s)
	@cd src && $(COMPOSE) logs -f $(s)

# ==========================================
# UTILITIES
# ==========================================

clean:
	@echo "--- Stopping services and removing volumes. WARNING: wipes DB data. ---"
	@cd src && $(COMPOSE) down -v --remove-orphans

docker-generate-certs:
	@test -n "$(domain)" || (echo "ERROR: domain is required. Usage: make docker-generate-certs domain=example.com" && exit 1)
	docker run --rm -v "$(CURDIR)/src/nginx/certs:/certs" -w /certs alpine \
		sh -c "apk add openssl && openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout privkey.pem -out fullchain.pem -subj '/CN=$(domain)'"
	@echo "SSL certificates generated for domain: $(domain)"

# ==========================================
# LOCAL DJANGO DEVELOPMENT
# ==========================================

# Use each service's OWN venv interpreter explicitly so these targets work
# regardless of which venv (if any) is currently activated on PATH.
ifeq ($(OS),Windows_NT)
VENV_PY := venv\Scripts\python.exe
else
VENV_PY := venv/bin/python
endif

django-makemigrations django-migrate django-manage django-tests: export PYTHONPATH = $(CURDIR)

django-makemigrations:
	@cd src/django_app && $(VENV_PY) manage.py makemigrations $(ARGS)

django-migrate:
	@cd src/django_app && $(VENV_PY) manage.py migrate $(ARGS)

django-manage:
	@cd src/django_app && $(VENV_PY) manage.py $(CMD)

django-tests:
	@cd src/django_app && $(VENV_PY) -m pytest $(ARGS)

# ==========================================
# LOCAL CREW DEVELOPMENT
# ==========================================

crew-tests: export PYTHONPATH = $(CURDIR)

crew-tests:
	@cd src/crew && $(VENV_PY) -m pytest $(ARGS)

agent-tests: export PYTHONPATH = $(CURDIR)

agent-tests:
	@cd src/agent && $(VENV_PY) -m pytest $(ARGS)
