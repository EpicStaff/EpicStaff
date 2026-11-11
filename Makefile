# Makefile for local backend development: uv lockfiles/venvs, Django management
# commands, and per-service test suites. The Docker stack is driven directly with
# `docker compose` from src/ -- see docs/makefile_commands.md.
# Use cmd.exe as the shell on Windows
ifeq ($(OS),Windows_NT)
	SHELL := cmd.exe
else
	SHELL := /bin/sh
endif

# IMPORTANT: This Makefile must be run from the project's root directory
# (the same directory this file is in).

.DEFAULT_GOAL := help

# Every backend service that uv manages, derived from the pyproject files so a
# new service is picked up without editing this list.
uv_services := $(patsubst src/%/pyproject.toml,%,$(wildcard src/*/pyproject.toml))
uv_lock_targets := $(addprefix uv-lock-,$(uv_services))

# django_app keeps its own django-tests name (next to the other django-* targets);
# shared has no single test session, so it has its own shared-tests target below.
test_targets := $(addsuffix -tests,$(filter-out django_app shared,$(uv_services)))

# The suites under src/shared. Each has its own pytest.ini (or none) and cannot
# join another suite's pytest session, so shared-tests runs them one by one.
shared_suites := tools models audit dotdict epicstaff_storage communication
shared_test_targets := $(addprefix shared-tests-,$(shared_suites))

.PHONY: help \
        uv-lock \
        uv-sync \
        django-makemigrations django-migrate django-manage django-tests \
        env-update \
        $(test_targets) shared-tests $(shared_test_targets)

# --- Help ---

help:
ifeq ($(OS),Windows_NT)
	@type make_scripts\help.txt
else
	@cat make_scripts/help.txt
endif

# ==========================================
# UV DEPENDENCY MANAGEMENT
# ==========================================

# Use each service's own uv-managed venv interpreter explicitly so these
# targets work regardless of what (if anything) is currently activated on
# PATH. Every service's venv lives at a plain .venv. A missing .venv fails
# loudly; `make uv-sync svc=<service>` is the one-command fix.
ifeq ($(OS),Windows_NT)
VENV_PY := .venv\Scripts\python.exe
SHARED_VENV_PY := src\shared\$(VENV_PY)
SHARED_SUITE_VENV_PY := ..\$(VENV_PY)
else
VENV_PY := .venv/bin/python
SHARED_VENV_PY := src/shared/$(VENV_PY)
SHARED_SUITE_VENV_PY := ../$(VENV_PY)
endif

# Regenerate every service's uv.lock. `--project` avoids a per-service cd and
# resolves each pyproject's relative [tool.uv.sources] paths (crew's
# ../shared/dotdict) against the service directory rather than the CWD.
# No --upgrade: this refreshes the lock to match pyproject.toml, it does not
# bump pinned versions.
#
# Deliberately NOT listing uv-lock-% (the expanded $(uv_lock_targets)) in
# .PHONY: GNU Make registers any name appearing in .PHONY's prerequisite list
# as already having an explicit (empty) rule, which then blocks the pattern
# rule below from ever matching it -- every uv-lock-<service> silently turns
# into a no-op ("Nothing to be done"). None of these names correspond to real
# files on disk, so they always rebuild anyway without needing .PHONY.
uv-lock: $(uv_lock_targets)

uv-lock-%:
	@echo "--- Locking src/$* ---"
	@uv lock --project src/$*

# --no-install-project keeps this target in lockstep with the Docker builders.
# The svc guard is a make function (not shell `test`) so it also works under
# cmd.exe on Windows.
uv-sync:
	$(if $(strip $(svc)),,$(error svc is required. Usage: make uv-sync svc=<service>))
	@cd src/$(svc) && uv sync --frozen --no-install-project --all-groups

# ==========================================
# LOCAL DJANGO DEVELOPMENT
# ==========================================

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
# SERVICE TESTS
# ==========================================

# One <service>-tests target per uv service (crew-tests, agent-tests,
# sandbox-tests, ...). A static pattern rule, so these are explicit targets and
# listing them in .PHONY above is safe -- unlike the uv-lock-% implicit rule.
$(test_targets): export PYTHONPATH = $(CURDIR)

$(test_targets): %-tests:
	@cd src/$* && $(VENV_PY) -m pytest $(ARGS)

# src/shared holds the cross-service models, built-in tools and libraries; its
# test environment is `make uv-sync svc=shared`. shared-tests runs every suite in
# its own pytest session and stops at the first one that fails. To run one
# suite, or to pass ARGS, use shared-tests-<suite> (tools, models, audit,
# dotdict, epicstaff_storage, communication): ARGS aimed at one suite would make
# the others fail on "no tests ran".
shared-tests: $(shared_test_targets)

$(shared_test_targets): export PYTHONPATH = $(CURDIR)

# These suites run from their own directory, where their pytest.ini lives. The
# venv is the one of src/shared, a directory up.
shared-tests-tools shared-tests-dotdict shared-tests-epicstaff_storage shared-tests-communication: shared-tests-%:
	@echo --- Testing src/shared/$* ---
	@cd src/shared/$* && $(SHARED_SUITE_VENV_PY) -m pytest $(ARGS)

# models has no pytest.ini and imports `shared.models`, so it runs from the repo
# root. audit must too: `python -m pytest` puts the working directory first on
# sys.path, and from src/shared/audit its token.py shadows the standard library's.
shared-tests-models:
	@echo --- Testing src/shared/models ---
	@$(SHARED_VENV_PY) -m pytest src/shared/models/tests $(ARGS)

shared-tests-audit:
	@echo --- Testing src/shared/audit ---
	@$(SHARED_VENV_PY) -m pytest -c src/shared/audit/pytest.ini src/shared/audit/tests $(ARGS)

# ==========================================
# ENV FILE
# ==========================================

# Host-side scripts run on any Python 3.11+ (envtool also needs PyYAML), not on a
# service venv. Override with `make <target> PYTHON=<interpreter>`.
ifeq ($(OS),Windows_NT)
PYTHON ?= python
else
PYTHON ?= python3
endif

# Appends the variables src/.env lacks; existing lines are never changed.
# DEV=1 takes the development defaults instead of the production ones.
env-update:
	@$(PYTHON) scripts/envtool.py --update $(if $(filter 1,$(DEV)),--dev)
