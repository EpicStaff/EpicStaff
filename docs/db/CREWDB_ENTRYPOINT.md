# crewdb Custom Docker Entrypoint

## Overview

`custom-docker-entrypoint.sh` is a wrapper around the default pgvector/PostgreSQL entrypoint.
It creates least-privilege database roles for each microservice and grants per-table permissions
before handing off to the standard `docker-entrypoint.sh`.

The crewdb container hosts a single PostgreSQL database (`crew`) shared by four services,
each connecting with its own restricted role:

| Service   | Role (env var)       | Purpose                                      |
|-----------|----------------------|----------------------------------------------|
| manager   | `DB_MANAGER_USER`    | Read-only access to session data              |
| knowledge | `DB_KNOWLEDGE_USER`  | Read/write access to RAG and embedding tables |
| realtime  | `DB_REALTIME_USER`   | CRUD on realtime session items                |
| crew      | `DB_CREW_USER`       | CRUD on memory database                       |

## How It Works

The script runs a **background worker** (`background_setup`) alongside the normal PostgreSQL
startup. The worker operates in two phases:

### Phase 1 -- Role Creation + Event Triggers

Runs as soon as PostgreSQL accepts connections on the target database.

1. **Create roles** -- Each `create_<service>_user` function creates a role (if not exists),
   grants `USAGE ON SCHEMA public`, and sets `ALTER DEFAULT PRIVILEGES ... REVOKE ALL ON TABLES`
   so the role has zero table access by default.

2. **Install event triggers** -- Two PostgreSQL event triggers are registered:
   - `auto_grant_on_create_table` (fires on `CREATE TABLE`)
   - `auto_grant_on_create_sequence` (fires on `CREATE SEQUENCE`)

   These triggers fire inside the same transaction as the DDL, so permissions are granted
   atomically the moment Django migrations create a table or sequence. This eliminates the
   race condition where the grant script could run before a table exists.

   The trigger functions contain per-table grant logic matching the permission matrix below.
   Role names are interpolated from env vars at function-creation time via bash heredoc.

### Phase 2 -- Catch-up Grants (Polling)

Handles the case where tables already exist (container restart, no new migrations).

1. Polls `all_tables_exist()` every 10 seconds (up to 20 minutes) checking for a set of
   required tables.
2. Once all required tables are found, runs `grant_<service>_permissions` for each service.
   Each function does a per-table `REVOKE` then `GRANT` to ensure a clean permission state.
3. Touches `/tmp/users_created` flag file to signal the healthcheck.

### Healthcheck

Called by Docker's `healthcheck` directive (see `docker-compose.yaml`):

```yaml
healthcheck:
  test: bash -c 'pg_isready ... && custom-docker-entrypoint.sh healthcheck-users'
```

Returns healthy only when:
- PostgreSQL is accepting connections (`pg_isready`)
- The `/tmp/users_created` flag exists (Phase 2 completed)

Downstream services (`crew`, `knowledge`, `realtime`, `manager`) use
`depends_on: crewdb: condition: service_healthy` so they start only after all permissions
are in place.

`django_app` uses `depends_on: crewdb: condition: service_started` (not `service_healthy`)
so it can begin running migrations immediately.

## Permission Matrix

### Tables

| Table                            | manager | knowledge | realtime | crew |
|----------------------------------|---------|-----------|----------|------|
| `tables_session`                 | SELECT  |           |          |      |
| `tables_provider`                |         | SELECT    |          |      |
| `tables_embeddingmodel`          |         | SELECT    |          |      |
| `tables_embeddingconfig`         |         | SELECT    |          |      |
| `tables_sourcecollection`        |         | SELECT    |          |      |
| `tables_documentmetadata`        |         | SELECT    |          |      |
| `tables_documentcontent`         |         | SELECT    |          |      |
| `tables_baseragtype`             |         | SELECT    |          |      |
| `tables_naiverag`                |         | SEL+UPD   |          |      |
| `tables_naiveragdocumentconfig`  |         | SEL+UPD   |          |      |
| `tables_naiveragchunk`           |         | CRUD      |          |      |
| `tables_naiveragpreviewchunk`    |         | CRUD      |          |      |
| `tables_naiveragembedding`       |         | CRUD      |          |      |
| `realtime_session_items`         |         |           | CRUD     |      |
| `tables_memorydatabase`          |         |           |          | CRUD |

### Sequences

| Sequence                              | Granted to | Privileges           |
|---------------------------------------|------------|----------------------|
| `tables_naiveragchunk_chunk_id_seq`   | knowledge  | USAGE, SELECT, UPDATE|
| `realtime_session_items_id_seq`       | realtime   | USAGE                |

## Required Environment Variables

Set in `.env` and passed to crewdb via `docker-compose.yaml`:

```
POSTGRES_DB          -- Target database name (default: crew)
POSTGRES_PASSWORD    -- Superuser password
DB_PORT              -- PostgreSQL port (default: 5432)

DB_MANAGER_USER      -- Manager service role name
DB_MANAGER_PASSWORD
DB_KNOWLEDGE_USER    -- Knowledge service role name
DB_KNOWLEDGE_PASSWORD
DB_REALTIME_USER     -- Realtime service role name
DB_REALTIME_PASSWORD
DB_CREW_USER         -- Crew service role name
DB_CREW_PASSWORD
```

## Startup Sequence Diagram

```
crewdb container starts
  |
  +--> background_setup() &          (background process)
  |      |
  |      +--> wait for DB to accept connections
  |      +--> Phase 1: create roles
  |      +--> Phase 1: install event triggers
  |      |      (triggers now auto-grant on CREATE TABLE / CREATE SEQUENCE)
  |      +--> Phase 2: poll for tables every 10s
  |      |      ...
  |      +--> tables found -> catch-up grants -> touch flag -> healthy
  |
  +--> exec docker-entrypoint.sh postgres   (main process, immediate)
         |
         +--> PostgreSQL ready
               |
               +--> django_app connects (depends_on: service_started)
               |      +--> runs migrations
               |      |      +--> CREATE TABLE fires event trigger -> auto-grant
               |      |      +--> CREATE SEQUENCE fires event trigger -> auto-grant
               |      +--> migrations complete -> Django healthy
               |
               +--> crew, knowledge, realtime, manager wait (depends_on: service_healthy)
                      +--> start after crewdb flag is set
```

## Adding Permissions for a New Table

1. Add the table name and grant level to `auto_grant_table_permissions()` in `install_event_triggers`.
2. Add the same table to the appropriate `grant_<service>_permissions` catch-up function.
3. If the table has a sequence that needs granting, add it to both
   `auto_grant_sequence_permissions()` and the catch-up function.
4. If the table should block startup until it exists, add it to the `REQUIRED_TABLES` array.
5. Rebuild the crewdb image (`docker compose build crewdb`).
