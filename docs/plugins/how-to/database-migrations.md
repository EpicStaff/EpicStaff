# Write database migrations

A plugin with a backend can keep its data in a PostgreSQL database of its own. You describe the
database's tables in SQL migrations in the package; the plugin node runs them before your
backend first starts. This page shows how to write them, and how your backend keeps every
organization's rows apart. [Plugin database](../reference/database.md) is the reference for the
roles, grants and limits.

## 1. Ask for a database

```json
"backend": { "python": "3.13", "entrypoint": "my_plugin.app:app" },
"database": {},
"limits": { "db_connections": 3, "statement_timeout_seconds": 10 }
```

`database` takes no fields and needs `backend`. The two limits are optional; without them your
plugin gets the deployment's defaults ([Limits](../reference/limits.md)). Add a driver to
`backend/requirements.in`, for example `psycopg[binary,pool]`: the SDK depends on none.

## 2. Add migration files

Put them in `database/migrations/` next to `manifest.json`:

```
database/migrations/001_places.sql
database/migrations/002_place_notes.sql
```

- Names are `NNN_<name>.sql`: three digits, then lower-case letters, digits and `_`. Each
  number is used once. Files run in name order.
- Each file is UTF-8 SQL. It may hold any number of statements, and `DO` blocks.
- Each file runs once. The node records it in its ledger and skips it from then on.
- All of them together hold at most 64 MiB.
- `epicstaff-plugin validate` and `pack` check the names and the size. `pack` copies `database/`
  into the package as it is.

## 3. One transaction per file, and nothing that leaves it

The node runs each file whole, in one transaction, with your owner role as the session user. If
any statement fails, that file is rolled back, the run stops, and the backend is not started;
the Runtime tab shows "`<file>` line `<n>`: [`<SQLSTATE>`] `<message>`", or
"`<file>`: [`<SQLSTATE>`] `<message>`" for an error PostgreSQL gives no position, such as one
raised while a statement ran. Files that ran before it
stay applied.

So a file must not control the transaction: no `BEGIN`, `COMMIT` or `ROLLBACK`. A `COMMIT` in
the middle would break the guarantee that a file applies entirely or not at all.
Statements that cannot run in a transaction, such as `CREATE INDEX CONCURRENTLY` or `VACUUM`,
cannot run in a migration.

Each file has up to 15 minutes, and fails when it waits more than 60 seconds for a lock.

## 4. Name roles with placeholders

Your plugin has three roles: the **owner**, which runs the migrations and owns what they create,
the **app** role your backend logs in as, and a **job** role the app role can switch to
([Roles](../reference/database.md#roles)). Name them with placeholders, never literally:

| Placeholder | Becomes, for the plugin `weather` |
|---|---|
| `${owner_role}` | `"weather_owner"` |
| `${app_role}` | `"weather_app"` |
| `${job_role}` | `"weather_job"` |

The node replaces each one with the quoted role name before the file runs.

## 5. Grant your app role what it needs

The app role starts with nothing in your database. Grant it what your backend uses, and no more:

```sql
CREATE SCHEMA places;

CREATE TABLE places.saved (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    org_id bigint NOT NULL,
    name text NOT NULL
);

GRANT USAGE ON SCHEMA places TO ${app_role};
GRANT SELECT, INSERT, UPDATE, DELETE ON places.saved TO ${app_role};
GRANT USAGE ON SEQUENCE places.saved_id_seq TO ${app_role};
```

## 6. Keep organizations apart with row-level security

One database serves every organization your plugin is granted to. Give every table an `org_id`
column and a policy that compares it with the setting `app.org_id`:

```sql
ALTER TABLE places.saved ENABLE ROW LEVEL SECURITY;
ALTER TABLE places.saved FORCE ROW LEVEL SECURITY;
CREATE POLICY org_rows ON places.saved
    USING (org_id = NULLIF(current_setting('app.org_id', true), '')::bigint)
    WITH CHECK (org_id = NULLIF(current_setting('app.org_id', true), '')::bigint);
```

- `USING` hides other organizations' rows from `SELECT`, `UPDATE` and `DELETE`; `WITH CHECK`
  refuses writing a row for another organization.
- `FORCE` applies the policy to the table's owner as well.
- When nothing set `app.org_id` in the current transaction, `current_setting('app.org_id', true)`
  is NULL, or an empty string on a connection where an earlier transaction set it. `NULLIF` turns
  both into NULL, which equals no organization: a session that forgot to set it sees nothing and
  can write nothing.

In your backend, run every query inside `org_transaction` from the Python SDK, with the
organization of the request's [gateway context](../reference/gateway-context.md):

```python
from epicstaff_plugin.database import connection_limit, database_url, org_transaction
from psycopg_pool import AsyncConnectionPool

# In the app's lifespan:
pool = AsyncConnectionPool(database_url(), min_size=1, max_size=connection_limit(), open=False)
await pool.open(wait=True)

# For a request:
async with pool.connection() as connection, org_transaction(connection, context.org.id):
    cursor = await connection.execute("SELECT id, name FROM places.saved ORDER BY name")
    rows = await cursor.fetchall()
```

`org_transaction` opens a transaction and runs
`SELECT pg_catalog.set_config('app.org_id', '<org id>', true)`: the setting lasts for that
transaction only, so a pooled connection never carries one organization into the next request.
It works for one organization at a time in a task: nested inside an open one for the same
organization it is a savepoint, and for another organization it raises
`NestedOrgTransactionError` before any SQL runs, on any connection. A nested savepoint's setting
would otherwise outlive it, and leave the rest of the outer transaction working for the other
organization. Finish one organization's transaction before you start the next.

The Weather sample does exactly this:
`plugin-samples/weather/database/migrations/001_weather.sql` for the tables, and
`plugin-samples/weather/backend/src/weather_plugin/database.py` for the transaction.

## 7. Set defaults on the database, not on the role

The platform owns the app role's settings: it resets any setting it finds on the role and keeps
only the statement timeout of your limits. Set defaults for your database instead. The database's
name depends on your plugin's id, so set them from a `DO` block:

```sql
DO $$
BEGIN
    EXECUTE format('ALTER DATABASE %I SET timezone TO %L', current_database(), 'UTC');
    EXECUTE format('ALTER DATABASE %I SET idle_in_transaction_session_timeout TO %L', current_database(), '60s');
END
$$;
```

New connections get them. The role's statement timeout still takes precedence over a database
default.

## 8. Extensions

Trusted extensions work, created by your owner role in a migration:

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;
```

Untrusted ones, such as `dblink`, `postgres_fdw` or `plpython3u`, cannot be created: PostgreSQL
allows them to superusers only, and no plugin role is one.

## 9. Never change a file that ran

The node keeps a ledger in `_epicstaff.migrations`: each file's name, its SHA-256 and when it
ran. A file that ran is skipped from then on, and a file whose content changed after it ran is
refused with "`<file>` changed after it was applied". To change your schema, add a new file.

The ledger is owned by your owner role, so a migration could rewrite it. It catches mistakes,
such as an edited file, not your own code doing so on purpose. Leave the `_epicstaff` schema
alone.

## Test your migrations before you upload

A SuperAdmin cannot replace an approved package in this version, so a migration that fails keeps
the backend from starting. Run your migrations against a PostgreSQL 17 set up the way the node
sets one up: the three roles, the owner as the session user, each file in one transaction, the
placeholders replaced. The Weather sample's tests do that, in
`src/plugin_sdk/tests/test_weather_sample_database.py` in the EpicStaff repository, and then run
the backend's stores against the result, as the app role.
