#!/bin/bash
set -e

# Flag file to indicate users have been created
USERS_CREATED_FLAG="/tmp/users_created"

# Function to check Django health
check_django_health() {
    
    if curl -f -H "Host: localhost" "http://django_app:${DJANGO_PORT}/ht/" > /dev/null 2>&1; then
        echo "Django is healthy"
        return 0
    else
        echo "Django is not healthy yet"
        return 1
    fi
}

# Function to create manager user
create_manager_user() {
    echo "=== Creating/Checking Manager User ==="

    manager_user="${DB_MANAGER_USER}"
    manager_password="${DB_MANAGER_PASSWORD}"
    
    # Check if required environment variables are set
    if [[ -z "$manager_user" || -z "$manager_password" ]]; then
        echo "WARNING: DB_MANAGER_USER or DB_MANAGER_PASSWORD not set, skipping manager user creation"
        return 0
    fi
    
    echo "Creating manager_user (${manager_user})..."
    psql -U "${POSTGRES_USER:-postgres}" -d "$target_db" -p ${DB_PORT} <<EOF
DO \$\$
BEGIN
   IF NOT EXISTS (
      SELECT FROM pg_catalog.pg_roles WHERE rolname = '${manager_user}'
   ) THEN
      EXECUTE format('CREATE USER %I WITH PASSWORD %L', '${manager_user}', '${manager_password}');
      RAISE NOTICE 'Created manager_user with read-only access to tables_session';
   ELSE
      RAISE NOTICE 'manager_user already exists, skipping creation';
   END IF;
END
\$\$;

-- Revoke any existing privileges (for safety)
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM "${manager_user}";

-- Grant USAGE on the schema
GRANT USAGE ON SCHEMA public TO "${manager_user}";

-- Grant SELECT only on the tables_session table (if it exists)
DO \$\$
BEGIN
   IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'tables_session' AND table_schema = 'public') THEN
      GRANT SELECT ON TABLE tables_session TO "${manager_user}";
      RAISE NOTICE 'Granted SELECT on tables_session to manager_user';
   ELSE
      RAISE NOTICE 'tables_session table does not exist yet, permissions will need to be granted later';
   END IF;
END
\$\$;

-- Prevent future tables from automatically granting access to this user
ALTER DEFAULT PRIVILEGES IN SCHEMA public 
  REVOKE ALL ON TABLES FROM "${manager_user}";
EOF
    
    echo "Manager user created or already exists with appropriate permissions: ${manager_user}"
    echo "=== Manager User Setup Complete ==="
    

}

create_knowledge_user(){
      echo "=== Creating/Checking Knowledge User ==="
      knowledge_user="${DB_KNOWLEDGE_USER}"
      knowledge_password="${DB_KNOWLEDGE_PASSWORD}"

      # Check if required environment variables are set
      if [[ -z "$knowledge_user" || -z "$knowledge_password" ]]; then
          echo "WARNING: DB_KNOWLEDGE_USER or DB_KNOWLEDGE_PASSWORD not set, skipping knowledge user creation"
          return 0
      fi

      echo "Creating knowledge_user (${knowledge_user})..."
      psql -U "${POSTGRES_USER:-postgres}" -d "$target_db" -p ${DB_PORT} <<EOF
      DO \$\$
      BEGIN
          IF NOT EXISTS (
              SELECT FROM pg_catalog.pg_roles WHERE rolname = '${knowledge_user}'
          ) THEN
              EXECUTE format('CREATE USER %I WITH PASSWORD %L', '${knowledge_user}', '${knowledge_password}');
              RAISE NOTICE 'Created knowledge_user with appropriate permissions';
          ELSE
              RAISE NOTICE 'knowledge_user already exists, skipping creation';
          END IF;
      END
      \$\$;

      -- Revoke any existing privileges (for safety)
      REVOKE ALL ON ALL TABLES IN SCHEMA public FROM "${knowledge_user}";

      -- Grant USAGE on the schema
      GRANT USAGE ON SCHEMA public TO "${knowledge_user}";

      -- Grant permission to create extensions (needed for uuid-ossp and pgvector)
      ALTER USER "${knowledge_user}" CREATEDB;
      GRANT CREATE ON SCHEMA public TO "${knowledge_user}";

      -- Grant CREATE privilege on the current database
      GRANT CREATE ON DATABASE "$target_db" TO "${knowledge_user}";

      -- === READ-ONLY TABLES ===

      -- Core configuration tables
      GRANT SELECT ON TABLE tables_provider TO "${knowledge_user}";
      GRANT SELECT ON TABLE tables_embeddingmodel TO "${knowledge_user}";
      GRANT SELECT ON TABLE tables_embeddingconfig TO "${knowledge_user}";

      -- Collection and document tables
      GRANT SELECT ON TABLE tables_sourcecollection TO "${knowledge_user}";
      GRANT SELECT ON TABLE tables_documentmetadata TO "${knowledge_user}";
      GRANT SELECT ON TABLE tables_documentcontent TO "${knowledge_user}";

      -- BaseRagType table
      GRANT SELECT ON TABLE tables_baseragtype TO "${knowledge_user}";

      -- === STATUS UPDATE TABLES ===

      GRANT SELECT, UPDATE ON TABLE tables_naiverag TO "${knowledge_user}";

      GRANT SELECT, UPDATE ON TABLE tables_naiveragdocumentconfig TO "${knowledge_user}";

      -- === FULL CRUD TABLES ===

      -- NaiveRagChunk table
      GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE tables_naiveragchunk TO "${knowledge_user}";
      
      -- NaiveRagPreviewChunk table
      GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE tables_naiveragpreviewchunk TO "${knowledge_user}";

      -- NaiveRagEmbedding table
      GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE tables_naiveragembedding TO "${knowledge_user}";

      -- === SEQUENCES ===

      -- Sequence for NaiveRagChunk (chunk_id autoincrement)
      GRANT USAGE, SELECT, UPDATE ON SEQUENCE tables_naiveragchunk_chunk_id_seq TO "${knowledge_user}";

      -- tables_naiveragembedding uses UUID primary key so no sequence needed

      -- Prevent automatic access to future tables (security measure)
      ALTER DEFAULT PRIVILEGES IN SCHEMA public
      REVOKE ALL ON TABLES FROM "${knowledge_user}";

EOF
      echo "Knowledge user created or already exists with appropriate permissions: ${knowledge_user}"
}

create_realtime_user() {
    echo "=== Creating/Checking Realtime User ==="
    realtime_user="${DB_REALTIME_USER}"
    realtime_password="${DB_REALTIME_PASSWORD}"
    # Check if required environment variables are set
    if [[ -z "$realtime_user" || -z "$realtime_password" ]]; then
        echo "WARNING: DB_REALTIME_USER or DB_REALTIME_PASSWORD not set, skipping manager user creation"
        return 0
    fi
    echo "Creating realtime_user (${realtime_user})..."
    psql -U "${POSTGRES_USER:-postgres}" -d "$target_db" -p ${DB_PORT} <<EOF
    DO \$\$
    BEGIN
    IF NOT EXISTS (
        SELECT FROM pg_catalog.pg_roles WHERE rolname = '${realtime_user}'
    ) THEN
        EXECUTE format('CREATE USER %I WITH PASSWORD %L', '${realtime_user}', '${realtime_password}');
        RAISE NOTICE 'Created realtime_user with CRUD access to realtime_session_items';
    ELSE
        RAISE NOTICE 'realtime_user already exists, skipping creation';
    END IF;
    END
    \$\$;

    -- Revoke all existing privileges for safety
    REVOKE ALL ON ALL TABLES IN SCHEMA public FROM "${realtime_user}";

    -- Grant basic usage
    GRANT USAGE ON SCHEMA public TO "${realtime_user}";

    -- Grant CRUD access to realtime_session_items
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE realtime_session_items TO "${realtime_user}";

    -- Grant USAGE on sequences only for tables with INSERT permissions
    DO \$\$
    BEGIN
        -- Grant sequence access for realtime_session_items (has INSERT permission)
        IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'realtime_session_items' AND table_schema = 'public') THEN
            GRANT USAGE ON SEQUENCE realtime_session_items_id_seq TO "${realtime_user}";
            RAISE NOTICE 'Granted USAGE on realtime_session_items_id_seq to realtime_user';
        END IF;
    EXCEPTION
        WHEN undefined_object THEN
            RAISE NOTICE 'Sequence realtime_session_items_id_seq does not exist yet';
    END
    \$\$;

    -- Prevent future tables from being auto-accessible
    ALTER DEFAULT PRIVILEGES IN SCHEMA public 
    REVOKE ALL ON TABLES FROM "${realtime_user}";
EOF
    echo "Realtime user created or already exists with appropriate permissions: ${realtime_user}"
}

create_crew_user() {
    echo "=== Creating/Checking Crew User ==="
    crew_user="${DB_CREW_USER}"
    crew_password="${DB_CREW_PASSWORD}"
    # Check if required environment variables are set
    if [[ -z "$crew_user" || -z "$crew_password" ]]; then
        echo "WARNING: DB_CREW_USER or DB_CREW_PASSWORD not set, skipping manager user creation"
        return 0
    fi
    echo "Creating crew_user (${crew_user})..."
    psql -U "${POSTGRES_USER:-postgres}" -d "$target_db" -p ${DB_PORT} <<EOF
    DO \$\$
    BEGIN
    IF NOT EXISTS (
        SELECT FROM pg_catalog.pg_roles WHERE rolname = '${crew_user}'
    ) THEN
        EXECUTE format('CREATE USER %I WITH PASSWORD %L', '${crew_user}', '${crew_password}');
        RAISE NOTICE 'Created crew_user with CRUD access to tables_memorydatabase';
    ELSE
        RAISE NOTICE 'crew_user already exists, skipping creation';
    END IF;
    END
    \$\$;

    -- Revoke all existing privileges for safety
    REVOKE ALL ON ALL TABLES IN SCHEMA public FROM "${crew_user}";

    -- Grant basic schema usage
    GRANT USAGE ON SCHEMA public TO "${crew_user}";

    -- Grant full CRUD access to the required table
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE tables_memorydatabase TO "${crew_user}";

    -- Prevent automatic access to future tables (security measure)
    ALTER DEFAULT PRIVILEGES IN SCHEMA public 
    REVOKE ALL ON TABLES FROM "${crew_user}";
EOF
    echo "Crew user created or already exists with appropriate permissions: ${crew_user}"
}

# Function to wait for Django health and then create users
wait_for_django_and_create_users() {
    (
        echo "Starting user creation process - waiting for Django health..."
        
        # Wait for Django to be healthy
        while ! check_django_health; do
            echo "Waiting for Django to be healthy..."
            sleep 7
        done
        
        echo "Django is healthy, proceeding with user creation"

        # Wait for PostgreSQL to be ready
        until pg_isready -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-postgres}" -h localhost -p "${DB_PORT}"; do
            echo "Waiting for PostgreSQL to be ready on port ${DB_PORT}..."
            sleep 2
        done
        target_db="${POSTGRES_DB:-postgres}"
        create_manager_user
        create_knowledge_user
        create_realtime_user
        create_crew_user

        # Set the flag that users have been created
        echo "All users created successfully"
        touch "$USERS_CREATED_FLAG"
        echo "USERS_CREATED flag set. Container crewdb is healthy"
        

    ) &
}

# Health check function for users created
users_created_healthcheck() {
    if [[ -f "$USERS_CREATED_FLAG" ]]; then
        echo "Users have been created"
        exit 0
    else
        echo "Users not created yet"
        exit 1
    fi
}

# Handle health check command
if [[ "$1" = "healthcheck-users" ]]; then
    users_created_healthcheck
fi

# Check if this is the main postgres command
if [[ "$1" = 'postgres' ]] || [[ "$1" = 'docker-entrypoint.sh' && "$2" = 'postgres' ]]; then
    echo "=== Starting Custom PostgreSQL Entrypoint ==="
    
    # If we're starting postgres, run our user creation process
    wait_for_django_and_create_users
fi

# Execute the original pgvector entrypoint with all arguments
echo "=== Executing Original pgvector Entrypoint ==="
exec docker-entrypoint.sh "$@"