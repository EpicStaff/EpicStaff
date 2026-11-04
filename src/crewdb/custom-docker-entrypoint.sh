#!/bin/bash
set -e

# Wraps the pgvector entrypoint to create the services' restricted database roles
# (manager, knowledge, realtime, sandbox) as soon as the database accepts connections.
# The roles start with no table privileges: django_app grants them, from
# src/django_app/tables/service_db_grants.py, right after its migrations have run
# (`manage.py apply_service_grants`), when no migration can race the grants.

# Flag file: the roles have been created, so crewdb reports healthy.
USERS_CREATED_FLAG="/tmp/users_created"

# HEALTH CHECK ENTRY POINT
# Only checks if postgres is ready + flag is set.
# Called by Docker healthcheck — must be fast.
if [[ "$1" = "healthcheck-users" ]]; then
    pg_isready -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -p "${POSTGRES_PORT}" || exit 1
    if [[ -f "$USERS_CREATED_FLAG" ]]; then
        exit 0
    else
        exit 1
    fi
fi

# Without ON_ERROR_STOP psql exits 0 after a failed statement, so a role that was
# never created would still let setup finish and report healthy.
setup_psql() {
    psql -X -v ON_ERROR_STOP=1 -U "${POSTGRES_USER}" -d "$TARGET_DB" -p "${POSTGRES_PORT}" "$@"
}

# Role, schema and database names are spliced into the SQL below as both literals
# and quoted identifiers, so only plain names are accepted. An empty value passes
# here: an unset role is skipped, and any other empty name fails in its statement.
require_plain_name() {
    local variable_name="$1"
    local value="${!variable_name:-}"
    if [[ -n "$value" && ! "$value" =~ ^[A-Za-z_][A-Za-z0-9_.-]{0,62}$ ]]; then
        echo "[setup] ERROR: ${variable_name} must be 1-63 letters, digits, '_', '.' or '-', starting with a letter or '_'" >&2
        return 1
    fi
}

# USER CREATION FUNCTIONS
# These only create the DB roles — no table grants.
# Safe to run as soon as postgres is up.
# Passwords are read by psql (\getenv) and quoted by format(); the shell never splices
# them into SQL. A failing statement may carry one, so its text is kept out of the
# server log and psql prints only the error message.

create_manager_user() {
    local manager_user="${MANAGER_DB_USER}"
    local manager_password="${MANAGER_DB_PASSWORD}"

    if [[ -z "$manager_user" || -z "$manager_password" ]]; then
        echo "[manager] WARNING: MANAGER_DB_USER or MANAGER_DB_PASSWORD not set, skipping"
        return 0
    fi

    echo "[manager] Creating role if not exists..."
    setup_psql <<EOF
\set VERBOSITY terse
\getenv password MANAGER_DB_PASSWORD
SET log_min_error_statement = panic;
SET log_statement = 'none';
SELECT format('CREATE USER %I WITH PASSWORD %L', '${manager_user}', :'password')
WHERE NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '${manager_user}')
\gexec

GRANT USAGE ON SCHEMA public TO "${manager_user}";

ALTER DEFAULT PRIVILEGES IN SCHEMA public
    REVOKE ALL ON TABLES FROM "${manager_user}";
EOF
    echo "[manager] Role ready: ${manager_user}"
}

create_knowledge_user() {
    local knowledge_user="${KNOWLEDGE_DB_USER}"
    local knowledge_password="${KNOWLEDGE_DB_PASSWORD}"

    if [[ -z "$knowledge_user" || -z "$knowledge_password" ]]; then
        echo "[knowledge] WARNING: KNOWLEDGE_DB_USER or KNOWLEDGE_DB_PASSWORD not set, skipping"
        return 0
    fi

    echo "[knowledge] Creating role if not exists..."
    setup_psql <<EOF
\set VERBOSITY terse
\getenv password KNOWLEDGE_DB_PASSWORD
SET log_min_error_statement = panic;
SET log_statement = 'none';
SELECT format('CREATE USER %I WITH PASSWORD %L', '${knowledge_user}', :'password')
WHERE NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '${knowledge_user}')
\gexec

GRANT USAGE ON SCHEMA public TO "${knowledge_user}";
ALTER USER "${knowledge_user}" CREATEDB;
GRANT CREATE ON SCHEMA public TO "${knowledge_user}";
GRANT CREATE ON DATABASE "${TARGET_DB}" TO "${knowledge_user}";

ALTER DEFAULT PRIVILEGES IN SCHEMA public
    REVOKE ALL ON TABLES FROM "${knowledge_user}";
EOF
    echo "[knowledge] Role ready: ${knowledge_user}"
}

create_realtime_user() {
    local realtime_user="${REALTIME_DB_USER}"
    local realtime_password="${REALTIME_DB_PASSWORD}"

    if [[ -z "$realtime_user" || -z "$realtime_password" ]]; then
        echo "[realtime] WARNING: REALTIME_DB_USER or REALTIME_DB_PASSWORD not set, skipping"
        return 0
    fi

    echo "[realtime] Creating role if not exists..."
    setup_psql <<EOF
\set VERBOSITY terse
\getenv password REALTIME_DB_PASSWORD
SET log_min_error_statement = panic;
SET log_statement = 'none';
SELECT format('CREATE USER %I WITH PASSWORD %L', '${realtime_user}', :'password')
WHERE NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '${realtime_user}')
\gexec

GRANT USAGE ON SCHEMA public TO "${realtime_user}";

ALTER DEFAULT PRIVILEGES IN SCHEMA public
    REVOKE ALL ON TABLES FROM "${realtime_user}";
EOF
    echo "[realtime] Role ready: ${realtime_user}"
}

create_sandbox_user() {
    local sandbox_user="${SANDBOX_DB_USER}"
    local sandbox_password="${SANDBOX_DB_PASSWORD}"
    local sandbox_schema="${SANDBOX_DB_SCHEMA}"

    if [[ -z "$sandbox_user" || -z "$sandbox_password" ]]; then
        echo "[sandbox] WARNING: SANDBOX_DB_USER or SANDBOX_DB_PASSWORD not set, skipping"
        return 0
    fi

    echo "[sandbox] Creating role and owned schema if not exists..."
    setup_psql <<EOF
\set VERBOSITY terse
\getenv password SANDBOX_DB_PASSWORD
SET log_min_error_statement = panic;
SET log_statement = 'none';
SELECT format('CREATE USER %I WITH PASSWORD %L', '${sandbox_user}', :'password')
WHERE NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '${sandbox_user}')
\gexec

-- The sandbox role owns its own schema and everything it creates there (its venv
-- table and Piccolo's own migration table). Default the role's search_path to it so
-- every sandbox connection and migration targets this namespace. No public grants.
CREATE SCHEMA IF NOT EXISTS "${sandbox_schema}" AUTHORIZATION "${sandbox_user}";
ALTER ROLE "${sandbox_user}" SET search_path = "${sandbox_schema}";
EOF
    echo "[sandbox] Role and schema ready: ${sandbox_user} owns schema ${sandbox_schema}"
}

# LEGACY CLEANUP
# Removes the auto_grant_on_create_table and auto_grant_on_create_sequence event triggers
# and their functions, auto_grant_table_permissions() and auto_grant_sequence_permissions().
# Earlier releases installed them into the database itself, so they live on the data volume
# and survive an image upgrade. Left in place, they would keep granting privileges on every
# CREATE TABLE from a frozen copy of an old grant matrix: a second, hidden source of grants
# next to src/django_app/tables/service_db_grants.py. They are dropped here because only
# their owner or a superuser can drop them, and crewdb setup runs as the superuser that
# created them.
# Temporary: delete this function once every deployment has started at least once on a
# release that contains it.
drop_legacy_auto_grant_triggers() {
    echo "[cleanup] Dropping legacy auto-grant event triggers, if any..."
    setup_psql <<EOF
DROP EVENT TRIGGER IF EXISTS auto_grant_on_create_table;
DROP EVENT TRIGGER IF EXISTS auto_grant_on_create_sequence;
DROP FUNCTION IF EXISTS auto_grant_table_permissions();
DROP FUNCTION IF EXISTS auto_grant_sequence_permissions();
EOF
}

# BACKGROUND WORKER
# Waits for the target database, creates the roles, then writes the healthcheck flag.
# Table privileges are not granted here: django_app grants them after its migrations.

background_setup() {
    (
        export TARGET_DB="${POSTGRES_DB}"

        # set -e ends setup on the first failure, before the healthcheck flag is
        # written; -E lets this trap fire for failures inside the functions too.
        set -E
        trap 'echo "=== [setup] ERROR: setup stopped on the error above; crewdb will not report healthy ===" >&2' ERR

        for name_variable in POSTGRES_DB MANAGER_DB_USER KNOWLEDGE_DB_USER REALTIME_DB_USER SANDBOX_DB_USER SANDBOX_DB_SCHEMA; do
            require_plain_name "$name_variable"
        done

        echo "=== [setup] Waiting for PostgreSQL and target database to be ready ==="
        # pg_isready only checks if postgres accepts connections — it returns true
        # even during the initdb temp-server phase, before POSTGRES_DB is created.
        # We must wait until we can actually connect to the target database.
        until psql -U "${POSTGRES_USER}" -p "${POSTGRES_PORT}" -d "$TARGET_DB" -c "SELECT 1" > /dev/null 2>&1; do
            echo "[setup] Waiting for database '${TARGET_DB}' to exist..."
            sleep 2
        done
        echo "=== [setup] PostgreSQL is up and database '${TARGET_DB}' exists ==="

        create_manager_user
        create_knowledge_user
        create_realtime_user
        create_sandbox_user
        # Before the flag, so the triggers are gone before django_app starts migrating.
        drop_legacy_auto_grant_triggers

        touch "$USERS_CREATED_FLAG"
        echo "=== [setup] All roles created. crewdb is ready; django_app grants table privileges after migrating ==="
    ) &
}

if [[ "$1" = 'postgres' ]] || [[ "$1" = 'docker-entrypoint.sh' && "$2" = 'postgres' ]]; then
    echo "=== Starting Custom PostgreSQL Entrypoint ==="
    # /tmp survives a container restart; a flag left by the previous run would report
    # healthy before this run's setup has succeeded.
    rm -f "$USERS_CREATED_FLAG"
    background_setup
fi

echo "=== Handing off to original pgvector entrypoint ==="
exec docker-entrypoint.sh "$@"
