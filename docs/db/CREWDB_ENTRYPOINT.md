# crewdb roles and service table grants

## Overview

The crewdb container hosts one PostgreSQL database shared by several services. Only crewdb
itself and the django_app test suite use the superuser (`DB_USER`). Every service connects
with a role of its own:

| Service   | Role (env var)       | Access                                                      |
|-----------|----------------------|-------------------------------------------------------------|
| django_app | `DJANGO_DB_USER`    | Owns the objects in `public` and runs the migrations; `CREATE` on `public` and the database. Not a superuser, no `CREATEDB` |
| manager   | `MANAGER_DB_USER`    | The tables its retention, schedule and cleanup jobs touch   |
| knowledge | `KNOWLEDGE_DB_USER`  | RAG configuration (read), indexing status (update), chunks and embeddings (read/write); also `CREATEDB` and `CREATE` on `public` and the database |
| realtime  | `REALTIME_DB_USER`   | Realtime session items                                      |
| sandbox   | `SANDBOX_DB_USER`    | Its own schema (`SANDBOX_DB_SCHEMA`), nothing in `public`   |

Two places set this up, each at the only moment it can be done safely:

1. **crewdb creates the roles** (`src/crewdb/custom-docker-entrypoint.sh`), as soon as the
   database accepts connections.
2. **django_app grants their table privileges** (`manage.py apply_service_grants`, run by
   `src/django_app/entrypoint.sh`) right after `migrate`.

Grants cannot run while migrations do: Postgres `GRANT` and `REVOKE` rewrite a table's catalog
row without locking the table, so one that meets a migration altering the same table fails
with `tuple concurrently updated`.

## crewdb: roles

`custom-docker-entrypoint.sh` wraps the pgvector entrypoint and starts a background setup
that:

1. Waits until the target database accepts connections.
2. Creates the django role (`create_django_user`) and creates the `vector` extension:
   pgvector 0.5.1 is not a trusted extension, so the django role could not. Trusted ones such
   as `pg_trgm` its migrations create themselves. `DJANGO_DB_USER` must differ from `DB_USER`.
3. Moves every object in `public` the superuser owns to the django role
   (`transfer_public_objects_to_django_user`): tables (their indexes and owned sequences
   follow), other sequences, views, routines and types. Extension members stay. Earlier
   releases ran django_app as the superuser; on a database already moved this changes nothing.
4. Creates each other role if missing (`create_<service>_user`): `USAGE ON SCHEMA public`, and
   `ALTER DEFAULT PRIVILEGES ... REVOKE ALL ON TABLES` so a new table grants it nothing. The
   knowledge role also gets `CREATEDB` and `CREATE` on the schema and database; the sandbox
   role owns its own schema and has it as its `search_path`.
5. Drops the legacy auto-grant event triggers (see below).
6. Touches `/tmp/users_created`, which the healthcheck (`custom-docker-entrypoint.sh
   healthcheck-users`) requires together with `pg_isready`.

Role, schema and database names are spliced into SQL, so they must be plain names (letters,
digits, `_`, `.`, `-`). Passwords are never spliced: psql reads them with `\getenv` and
`format()` quotes them. Every statement runs with `ON_ERROR_STOP=1`; any failure stops setup
with `[setup] ERROR` in the log before the flag is written, so crewdb never reports healthy
with a role missing.

### Legacy cleanup

Earlier releases installed the event triggers `auto_grant_on_create_table` and
`auto_grant_on_create_sequence` (functions `auto_grant_table_permissions()` and
`auto_grant_sequence_permissions()`) into the database. They live on the data volume, so an
image upgrade does not remove them, and they would keep granting privileges from a frozen copy
of the old matrix on every `CREATE TABLE`. crewdb drops them on every start, as the superuser
that created them. The cleanup is temporary: it can be deleted once every deployment has
started at least once on a release that contains it.

## django_app: table grants

The grant matrix lives in one place, [`src/django_app/tables/service_db_grants.py`](../../src/django_app/tables/service_db_grants.py):
for each service, the env var holding its role name, the tables with their privileges (and
column-level `UPDATE` where a role may change only some columns), and the sequences.

`apply_service_grants` reads the role names from `MANAGER_DB_USER`, `KNOWLEDGE_DB_USER` and
`REALTIME_DB_USER`, checks that the roles exist, then for every table and sequence in the
matrix runs `REVOKE ALL` followed by the matrix's `GRANT`s. It runs:

- **in one transaction**, so a connected service never sees a table between its `REVOKE`
  and its `GRANT`, and a failure leaves the previous grants in place;
- **on every start**, so an existing database converges on the matrix whenever it changes;
- **strictly**: an unset role variable, a missing role, or a table or sequence that does not
  exist fails the command, and with it django_app's startup.

## Startup order

```
crewdb starts
  +--> postgres up --> roles created, ownership moved --> legacy triggers dropped --> flag --> healthy
                                                                               |
sandbox_new (depends_on crewdb healthy) ---------------------------------------+
  +--> piccolo migrations --> healthy                                          |
                               |                                               |
django_app (depends_on crewdb healthy, sandbox_new healthy) <------------------+
  +--> migrate --> apply_service_grants --> ... --> gunicorn --> healthy (/ht/)
                                                                   |
manager, knowledge_new, realtime (depends_on django_app healthy) <-+
```

The services that use the granted roles wait for django_app to be healthy, which it only
becomes after `apply_service_grants` has succeeded.

## Granting a service a new table

1. Add a `TableGrant` (and a `SequenceGrant` if the service inserts through a sequence it
   does not own) to the service's entry in `src/django_app/tables/service_db_grants.py`,
   with a comment saying why it needs that access.
2. The table must be created by a Django migration: the command fails if it does not exist.
3. Restart django_app. No crewdb rebuild is needed.

For a new restricted role, create it in `custom-docker-entrypoint.sh`, add a
`ServiceRoleGrants` to `SERVICE_ROLE_GRANTS`, and pass its role name variable to django_app
in `src/docker-compose.yaml`.
