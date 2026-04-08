#!/bin/bash
set -e

# Flag file to indicate all table-level permissions have been granted
USERS_CREATED_FLAG="/tmp/users_created"

# HEALTH CHECK ENTRY POINT
# Only checks if postgres is ready + flag is set.
# Called by Docker healthcheck — must be fast.
if [[ "$1" = "healthcheck-users" ]]; then
    pg_isready -U "${POSTGRES_USER:-postgres}" -p "${DB_PORT:-5432}" || exit 1
    if [[ -f "$USERS_CREATED_FLAG" ]]; then
        exit 0
    else
        exit 1
    fi
fi

# USER CREATION FUNCTIONS
# These only create the DB roles — no table grants.
# Safe to run as soon as postgres is up.

create_manager_user() {
    local manager_user="${DB_MANAGER_USER}"
    local manager_password="${DB_MANAGER_PASSWORD}"

    if [[ -z "$manager_user" || -z "$manager_password" ]]; then
        echo "[manager] WARNING: DB_MANAGER_USER or DB_MANAGER_PASSWORD not set, skipping"
        return 0
    fi

    echo "[manager] Creating role if not exists..."
    psql -U "${POSTGRES_USER:-postgres}" -d "$TARGET_DB" -p "${DB_PORT:-5432}" <<EOF
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '${manager_user}') THEN
        EXECUTE format('CREATE USER %I WITH PASSWORD %L', '${manager_user}', '${manager_password}');
        RAISE NOTICE '[manager] Created user ${manager_user}';
    ELSE
        RAISE NOTICE '[manager] User ${manager_user} already exists, skipping';
    END IF;
END
\$\$;

GRANT USAGE ON SCHEMA public TO "${manager_user}";

ALTER DEFAULT PRIVILEGES IN SCHEMA public
    REVOKE ALL ON TABLES FROM "${manager_user}";
EOF
    echo "[manager] Role ready: ${manager_user}"
}

create_knowledge_user() {
    local knowledge_user="${DB_KNOWLEDGE_USER}"
    local knowledge_password="${DB_KNOWLEDGE_PASSWORD}"

    if [[ -z "$knowledge_user" || -z "$knowledge_password" ]]; then
        echo "[knowledge] WARNING: DB_KNOWLEDGE_USER or DB_KNOWLEDGE_PASSWORD not set, skipping"
        return 0
    fi

    echo "[knowledge] Creating role if not exists..."
    psql -U "${POSTGRES_USER:-postgres}" -d "$TARGET_DB" -p "${DB_PORT:-5432}" <<EOF
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '${knowledge_user}') THEN
        EXECUTE format('CREATE USER %I WITH PASSWORD %L', '${knowledge_user}', '${knowledge_password}');
        RAISE NOTICE '[knowledge] Created user ${knowledge_user}';
    ELSE
        RAISE NOTICE '[knowledge] User ${knowledge_user} already exists, skipping';
    END IF;
END
\$\$;

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
    local realtime_user="${DB_REALTIME_USER}"
    local realtime_password="${DB_REALTIME_PASSWORD}"

    if [[ -z "$realtime_user" || -z "$realtime_password" ]]; then
        echo "[realtime] WARNING: DB_REALTIME_USER or DB_REALTIME_PASSWORD not set, skipping"
        return 0
    fi

    echo "[realtime] Creating role if not exists..."
    psql -U "${POSTGRES_USER:-postgres}" -d "$TARGET_DB" -p "${DB_PORT:-5432}" <<EOF
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '${realtime_user}') THEN
        EXECUTE format('CREATE USER %I WITH PASSWORD %L', '${realtime_user}', '${realtime_password}');
        RAISE NOTICE '[realtime] Created user ${realtime_user}';
    ELSE
        RAISE NOTICE '[realtime] User ${realtime_user} already exists, skipping';
    END IF;
END
\$\$;

GRANT USAGE ON SCHEMA public TO "${realtime_user}";

ALTER DEFAULT PRIVILEGES IN SCHEMA public
    REVOKE ALL ON TABLES FROM "${realtime_user}";
EOF
    echo "[realtime] Role ready: ${realtime_user}"
}

create_crew_user() {
    local crew_user="${DB_CREW_USER}"
    local crew_password="${DB_CREW_PASSWORD}"

    if [[ -z "$crew_user" || -z "$crew_password" ]]; then
        echo "[crew] WARNING: DB_CREW_USER or DB_CREW_PASSWORD not set, skipping"
        return 0
    fi

    echo "[crew] Creating role if not exists..."
    psql -U "${POSTGRES_USER:-postgres}" -d "$TARGET_DB" -p "${DB_PORT:-5432}" <<EOF
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '${crew_user}') THEN
        EXECUTE format('CREATE USER %I WITH PASSWORD %L', '${crew_user}', '${crew_password}');
        RAISE NOTICE '[crew] Created user ${crew_user}';
    ELSE
        RAISE NOTICE '[crew] User ${crew_user} already exists, skipping';
    END IF;
END
\$\$;

GRANT USAGE ON SCHEMA public TO "${crew_user}";

ALTER DEFAULT PRIVILEGES IN SCHEMA public
    REVOKE ALL ON TABLES FROM "${crew_user}";
EOF
    echo "[crew] Role ready: ${crew_user}"
}

# TABLE PERMISSION GRANT FUNCTIONS
# Called only after Django migrations have run.
# Each function is safe to call multiple times.

grant_manager_permissions() {
    local manager_user="${DB_MANAGER_USER}"
    [[ -z "$manager_user" ]] && return 0

    echo "[manager] Granting table permissions..."
    psql -U "${POSTGRES_USER:-postgres}" -d "$TARGET_DB" -p "${DB_PORT:-5432}" <<EOF
DO \$\$
BEGIN
    IF EXISTS (
        SELECT FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'tables_session'
    ) THEN
        REVOKE ALL ON TABLE tables_session FROM "${manager_user}";
        GRANT SELECT ON TABLE tables_session TO "${manager_user}";
        RAISE NOTICE '[manager] Granted SELECT on tables_session';
    ELSE
        RAISE NOTICE '[manager] tables_session not found, skipping';
    END IF;
END
\$\$;
EOF
    echo "[manager] Permissions granted"
}

grant_knowledge_permissions() {
    local knowledge_user="${DB_KNOWLEDGE_USER}"
    [[ -z "$knowledge_user" ]] && return 0

    echo "[knowledge] Granting table permissions..."
    psql -U "${POSTGRES_USER:-postgres}" -d "$TARGET_DB" -p "${DB_PORT:-5432}" <<EOF
DO \$\$
DECLARE
    tbl  text;

    -- Read-only tables
    ro_tables text[] := ARRAY[
        'tables_provider',
        'tables_embeddingmodel',
        'tables_embeddingconfig',
        'tables_sourcecollection',
        'tables_documentmetadata',
        'tables_documentcontent',
        'tables_baseragtype'
    ];

    -- Select + Update only
    su_tables text[] := ARRAY[
        'tables_naiverag',
        'tables_naiveragdocumentconfig'
    ];

    -- Full CRUD
    crud_tables text[] := ARRAY[
        'tables_naiveragchunk',
        'tables_naiveragpreviewchunk',
        'tables_naiveragembedding'
    ];

    all_managed text[] := ARRAY[
        'tables_provider','tables_embeddingmodel','tables_embeddingconfig',
        'tables_sourcecollection','tables_documentmetadata',
        'tables_documentcontent','tables_baseragtype',
        'tables_naiverag','tables_naiveragdocumentconfig',
        'tables_naiveragchunk','tables_naiveragpreviewchunk','tables_naiveragembedding'
    ];

BEGIN
    -- Revoke stale permissions only on tables this function manages
    FOREACH tbl IN ARRAY all_managed LOOP
        IF EXISTS (SELECT FROM information_schema.tables WHERE table_schema='public' AND table_name=tbl) THEN
            EXECUTE format('REVOKE ALL ON TABLE %I FROM %I', tbl, '${knowledge_user}');
        END IF;
    END LOOP;

    FOREACH tbl IN ARRAY ro_tables LOOP
        IF EXISTS (SELECT FROM information_schema.tables WHERE table_schema='public' AND table_name=tbl) THEN
            EXECUTE format('GRANT SELECT ON TABLE %I TO %I', tbl, '${knowledge_user}');
            RAISE NOTICE '[knowledge] SELECT granted on %', tbl;
        ELSE
            RAISE NOTICE '[knowledge] % not found, skipping', tbl;
        END IF;
    END LOOP;

    FOREACH tbl IN ARRAY su_tables LOOP
        IF EXISTS (SELECT FROM information_schema.tables WHERE table_schema='public' AND table_name=tbl) THEN
            EXECUTE format('GRANT SELECT, UPDATE ON TABLE %I TO %I', tbl, '${knowledge_user}');
            RAISE NOTICE '[knowledge] SELECT,UPDATE granted on %', tbl;
        ELSE
            RAISE NOTICE '[knowledge] % not found, skipping', tbl;
        END IF;
    END LOOP;

    FOREACH tbl IN ARRAY crud_tables LOOP
        IF EXISTS (SELECT FROM information_schema.tables WHERE table_schema='public' AND table_name=tbl) THEN
            EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE %I TO %I', tbl, '${knowledge_user}');
            RAISE NOTICE '[knowledge] CRUD granted on %', tbl;
        ELSE
            RAISE NOTICE '[knowledge] % not found, skipping', tbl;
        END IF;
    END LOOP;

    -- Sequence for naiveragchunk
    IF EXISTS (SELECT FROM pg_sequences WHERE schemaname='public' AND sequencename='tables_naiveragchunk_chunk_id_seq') THEN
        GRANT USAGE, SELECT, UPDATE ON SEQUENCE tables_naiveragchunk_chunk_id_seq TO "${knowledge_user}";
        RAISE NOTICE '[knowledge] Sequence tables_naiveragchunk_chunk_id_seq granted';
    END IF;
END
\$\$;
EOF
    echo "[knowledge] Permissions granted"
}

grant_realtime_permissions() {
    local realtime_user="${DB_REALTIME_USER}"
    [[ -z "$realtime_user" ]] && return 0

    echo "[realtime] Granting table permissions..."
    psql -U "${POSTGRES_USER:-postgres}" -d "$TARGET_DB" -p "${DB_PORT:-5432}" <<EOF
DO \$\$
BEGIN
    IF EXISTS (
        SELECT FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'realtime_session_items'
    ) THEN
        REVOKE ALL ON TABLE realtime_session_items FROM "${realtime_user}";
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE realtime_session_items TO "${realtime_user}";
        RAISE NOTICE '[realtime] CRUD granted on realtime_session_items';

        IF EXISTS (SELECT FROM pg_sequences WHERE schemaname='public' AND sequencename='realtime_session_items_id_seq') THEN
            GRANT USAGE ON SEQUENCE realtime_session_items_id_seq TO "${realtime_user}";
            RAISE NOTICE '[realtime] Sequence realtime_session_items_id_seq granted';
        END IF;
    ELSE
        RAISE NOTICE '[realtime] realtime_session_items not found, skipping';
    END IF;
END
\$\$;
EOF
    echo "[realtime] Permissions granted"
}

grant_crew_permissions() {
    local crew_user="${DB_CREW_USER}"
    [[ -z "$crew_user" ]] && return 0

    echo "[crew] Granting table permissions..."
    psql -U "${POSTGRES_USER:-postgres}" -d "$TARGET_DB" -p "${DB_PORT:-5432}" <<EOF
DO \$\$
BEGIN
    IF EXISTS (
        SELECT FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'tables_memorydatabase'
    ) THEN
        REVOKE ALL ON TABLE tables_memorydatabase FROM "${crew_user}";
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE tables_memorydatabase TO "${crew_user}";
        RAISE NOTICE '[crew] CRUD granted on tables_memorydatabase';
    ELSE
        RAISE NOTICE '[crew] tables_memorydatabase not found, skipping';
    END IF;
END
\$\$;
EOF
    echo "[crew] Permissions granted"
}

# TABLE EXISTENCE CHECK
# Returns 0 only when ALL required tables are present.

REQUIRED_TABLES=(
    "tables_session"
    "tables_naiveragchunk"
    "tables_naiveragembedding"
    "tables_memorydatabase"
    "realtime_session_items"
)

all_tables_exist() {
    for tbl in "${REQUIRED_TABLES[@]}"; do
        local count
        count=$(psql -U "${POSTGRES_USER:-postgres}" -d "$TARGET_DB" -p "${DB_PORT:-5432}" -tAc \
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public' AND table_name='${tbl}'" 2>/dev/null || echo "0")
        if [[ "$count" != "1" ]]; then
            echo "[check] Table '${tbl}' not yet present"
            return 1
        fi
    done
    return 0
}

# EVENT TRIGGER SETUP
# Creates PostgreSQL event triggers that auto-grant permissions when
# Django migrations create tables/sequences. Eliminates the race condition
# where Phase 2 polling could miss newly created objects.
# Uses CREATE OR REPLACE so it is safe to call on every container start.

install_event_triggers() {
    local manager_user="${DB_MANAGER_USER}"
    local knowledge_user="${DB_KNOWLEDGE_USER}"
    local realtime_user="${DB_REALTIME_USER}"
    local crew_user="${DB_CREW_USER}"

    echo "[triggers] Installing event triggers for auto-grant..."
    psql -U "${POSTGRES_USER:-postgres}" -d "$TARGET_DB" -p "${DB_PORT:-5432}" <<EOF
-- Auto-grant table permissions on CREATE TABLE
CREATE OR REPLACE FUNCTION auto_grant_table_permissions()
RETURNS event_trigger
LANGUAGE plpgsql
AS \$func\$
DECLARE
    obj record;
    tbl_name text;
BEGIN
    FOR obj IN SELECT * FROM pg_event_trigger_ddl_commands()
                WHERE command_tag = 'CREATE TABLE'
    LOOP
        tbl_name := split_part(obj.object_identity, '.', 2);

        -- manager: SELECT only
        IF tbl_name = 'tables_session' THEN
            EXECUTE format('GRANT SELECT ON TABLE %I TO %I', tbl_name, '${manager_user}');
            RAISE NOTICE '[auto-grant] SELECT on % to ${manager_user}', tbl_name;
        END IF;

        -- knowledge: read-only tables
        IF tbl_name IN ('tables_provider','tables_embeddingmodel','tables_embeddingconfig',
                         'tables_sourcecollection','tables_documentmetadata',
                         'tables_documentcontent','tables_baseragtype') THEN
            EXECUTE format('GRANT SELECT ON TABLE %I TO %I', tbl_name, '${knowledge_user}');
            RAISE NOTICE '[auto-grant] SELECT on % to ${knowledge_user}', tbl_name;
        END IF;

        -- knowledge: SELECT + UPDATE
        IF tbl_name IN ('tables_naiverag','tables_naiveragdocumentconfig') THEN
            EXECUTE format('GRANT SELECT, UPDATE ON TABLE %I TO %I', tbl_name, '${knowledge_user}');
            RAISE NOTICE '[auto-grant] SELECT,UPDATE on % to ${knowledge_user}', tbl_name;
        END IF;

        -- knowledge: full CRUD
        IF tbl_name IN ('tables_naiveragchunk','tables_naiveragpreviewchunk','tables_naiveragembedding') THEN
            EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE %I TO %I', tbl_name, '${knowledge_user}');
            RAISE NOTICE '[auto-grant] CRUD on % to ${knowledge_user}', tbl_name;
        END IF;

        -- realtime: full CRUD
        IF tbl_name = 'realtime_session_items' THEN
            EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE %I TO %I', tbl_name, '${realtime_user}');
            RAISE NOTICE '[auto-grant] CRUD on % to ${realtime_user}', tbl_name;
        END IF;

        -- crew: full CRUD
        IF tbl_name = 'tables_memorydatabase' THEN
            EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE %I TO %I', tbl_name, '${crew_user}');
            RAISE NOTICE '[auto-grant] CRUD on % to ${crew_user}', tbl_name;
        END IF;
    END LOOP;
END;
\$func\$;

-- Auto-grant sequence permissions on CREATE SEQUENCE
CREATE OR REPLACE FUNCTION auto_grant_sequence_permissions()
RETURNS event_trigger
LANGUAGE plpgsql
AS \$func\$
DECLARE
    obj record;
    seq_name text;
BEGIN
    FOR obj IN SELECT * FROM pg_event_trigger_ddl_commands()
                WHERE command_tag = 'CREATE SEQUENCE'
    LOOP
        seq_name := split_part(obj.object_identity, '.', 2);

        -- knowledge: naiveragchunk sequence
        IF seq_name = 'tables_naiveragchunk_chunk_id_seq' THEN
            EXECUTE format('GRANT USAGE, SELECT, UPDATE ON SEQUENCE %I TO %I', seq_name, '${knowledge_user}');
            RAISE NOTICE '[auto-grant] USAGE,SELECT,UPDATE on % to ${knowledge_user}', seq_name;
        END IF;

        -- realtime: session_items sequence
        IF seq_name = 'realtime_session_items_id_seq' THEN
            EXECUTE format('GRANT USAGE ON SEQUENCE %I TO %I', seq_name, '${realtime_user}');
            RAISE NOTICE '[auto-grant] USAGE on % to ${realtime_user}', seq_name;
        END IF;
    END LOOP;
END;
\$func\$;

-- Create or replace event triggers (DROP + CREATE since ALTER is not supported)
DROP EVENT TRIGGER IF EXISTS auto_grant_on_create_table;
CREATE EVENT TRIGGER auto_grant_on_create_table
    ON ddl_command_end
    WHEN TAG IN ('CREATE TABLE')
    EXECUTE FUNCTION auto_grant_table_permissions();

DROP EVENT TRIGGER IF EXISTS auto_grant_on_create_sequence;
CREATE EVENT TRIGGER auto_grant_on_create_sequence
    ON ddl_command_end
    WHEN TAG IN ('CREATE SEQUENCE')
    EXECUTE FUNCTION auto_grant_sequence_permissions();
EOF
    echo "[triggers] Event triggers installed"
}

# BACKGROUND WORKER
# Phase 1: Wait for postgres → create roles + install event triggers.
# Phase 2: Wait for tables (created by Django migrations) → grant permissions
#           for tables that already exist (catch-up on restart).
# Event triggers handle the race condition for newly created tables.

background_setup() {
    (
        export TARGET_DB="${POSTGRES_DB:-postgres}"

        echo "=== [setup] Phase 1: Waiting for PostgreSQL and target database to be ready ==="
        # pg_isready only checks if postgres accepts connections — it returns true
        # even during the initdb temp-server phase, before POSTGRES_DB is created.
        # We must wait until we can actually connect to the target database.
        until psql -U "${POSTGRES_USER:-postgres}" -p "${DB_PORT:-5432}" -d "$TARGET_DB" -c "SELECT 1" > /dev/null 2>&1; do
            echo "[setup] Waiting for database '${TARGET_DB}' to exist..."
            sleep 2
        done
        echo "=== [setup] PostgreSQL is up and database '${TARGET_DB}' exists ==="

        # Phase 1 — create roles (no tables needed)
        create_manager_user
        create_knowledge_user
        create_realtime_user
        create_crew_user
        install_event_triggers
        echo "=== [setup] Phase 1 complete: all roles created, event triggers installed ==="

        # Phase 2 — wait for Django to run migrations, then grant permissions
        echo "=== [setup] Phase 2: Waiting for Django to create tables via migrations ==="
        local attempt=0
        local max_attempts=120   # 120 × 10s = 20 minutes max

        while [[ $attempt -lt $max_attempts ]]; do
            if all_tables_exist; then
                echo "=== [setup] All required tables found. Granting permissions... ==="
                grant_manager_permissions
                grant_knowledge_permissions
                grant_realtime_permissions
                grant_crew_permissions
                touch "$USERS_CREATED_FLAG"
                echo "=== [setup] Phase 2 complete: all permissions granted. crewdb is FULLY READY ==="
                exit 0
            fi
            attempt=$(( attempt + 1 ))
            echo "[setup] Attempt ${attempt}/${max_attempts} — tables not ready yet, retrying in 10s..."
            sleep 10
        done

        echo "=== [setup] ERROR: Timed out waiting for Django migrations after $(( max_attempts * 10 ))s ==="
        exit 1
    ) &
}

if [[ "$1" = 'postgres' ]] || [[ "$1" = 'docker-entrypoint.sh' && "$2" = 'postgres' ]]; then
    echo "=== Starting Custom PostgreSQL Entrypoint ==="
    background_setup
fi

echo "=== Handing off to original pgvector entrypoint ==="
exec docker-entrypoint.sh "$@"