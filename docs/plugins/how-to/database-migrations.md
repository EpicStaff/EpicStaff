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

- Names are `NNN_<name>.sql`: three digits, then lower-case letters, digits and `_`, 255
  characters at most for the whole file name. Each number is used once. Files run in name
  order.
- Each file is UTF-8 SQL. It may hold any number of statements, and `DO` blocks.
- Each file runs once. The node records it in its ledger and skips it from then on.
- A new version of your plugin adds files after the last one, and never changes a file an
  earlier version shipped ([section 9](#9-never-change-a-file-that-ran),
  [section 11](#11-change-the-schema-in-a-new-version)).
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

For the same reason, `org_transaction` needs a connection with no transaction open. psycopg
opens one by itself for a query you run outside a transaction block, and a savepoint inside it
would leave the organization set for the rest of that transaction. Such a connection raises
`ConnectionInTransactionError` before any SQL runs. A connection fresh from the pool never has
one open, so take one per request, as above.

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

EpicStaff checks the same before your plugin goes offline. A new version whose package holds a
file with the name of one the installed version ships, or one the ledger lists, but with other
content, is refused when it is uploaded: 409 `plugin_upgrade_unavailable`, "`<name>` is already
applied; a new version must keep it unchanged". A new version may leave out a file an earlier
one shipped: the node ignores ledger entries it has no file for.

The ledger is owned by your owner role, so a migration could rewrite it. It catches mistakes,
such as an edited file, not your own code doing so on purpose. Leave the `_epicstaff` schema
alone.

## 10. Work across organizations with the job role

Some work is about every organization at once: deleting rows that are past their time, for
example. Do it as the plugin's job role, `${job_role}` in your migrations, never by looping
over organizations, and never by giving the app role a policy that sees every organization.
The job role has only what you grant it, and its own policies:

```sql
-- The organization policy is for requests only.
ALTER POLICY org_rows ON places.lookups TO ${app_role};

CREATE INDEX lookups_looked_up_at ON places.lookups (looked_up_at);

-- A DELETE whose WHERE reads a column needs SELECT on it, under the SELECT policies.
CREATE POLICY expired_rows_read ON places.lookups
    FOR SELECT TO ${job_role}
    USING (looked_up_at < now() - interval '1 day');
CREATE POLICY expired_rows_delete ON places.lookups
    FOR DELETE TO ${job_role}
    USING (looked_up_at < now() - interval '1 day');

GRANT USAGE ON SCHEMA places TO ${job_role};
GRANT SELECT (looked_up_at), DELETE ON places.lookups TO ${job_role};
```

- **Put the rule in the policy.** The job role can then see and delete only expired rows,
  whatever its statements say, and read nothing but the timestamp.
- **Narrow the organization policy to the app role.** A policy without `TO` applies to every
  role, the job role included. A job transaction sets no organization, but nothing should let a
  live row through if one were set.
- **Index the column the rule reads.** The work spans every organization, so the index starts
  with that column, not with `org_id`.

In your backend, run the work in `job_transaction` from the Python SDK. It switches the
transaction to the job role, and works for no organization:

```python
from epicstaff_plugin.database import job_transaction

async with pool.connection() as connection, job_transaction(connection):
    await connection.execute(
        "DELETE FROM places.lookups WHERE looked_up_at < now() - interval '1 day'"
    )
```

It refuses to run inside an `org_transaction`, and the other way round, and needs a connection
with no transaction open, like `org_transaction`. Keep each transaction short: for a table that
can pile up rows, delete in batches, each in a `job_transaction` of its own, so no statement
comes near your statement timeout. Start each batch after the timestamp the last one ended at,
not from the oldest row again: a batch that starts from the beginning reads every row the
earlier batches deleted, so a backlog costs the square of its size. The Weather sample's
`plugin-samples/weather/database/migrations/002_retention.sql` and
`plugin-samples/weather/backend/src/weather_plugin/retention.py` delete old rows hourly, 5,000
at a time.

## 11. Change the schema in a new version

A new version of your plugin brings its new files in `database/migrations/`, numbered after the
last one. Weather 0.7.0 adds `003_place_conditions.sql` to 0.6.0's `001_weather.sql` and
`002_retention.sql`. During the upgrade:

1. The plugin goes offline, and its process stops.
2. EpicStaff backs the database up. No migration runs without a backup taken for this upgrade.
3. The node runs the files its ledger does not list yet, in name order, each in one transaction,
   as in [section 3](#3-one-transaction-per-file-and-nothing-that-leaves-it).
4. The new version's process starts, and then each organization's
   [upgrade hook](upgrade-hook.md) runs.

The plugin is offline from step 1 until its new process runs, so a long migration keeps it
offline that long. Each file has up to 15 minutes, and fails when it waits more than 60 seconds
for a lock. Keep the work a migration does on existing rows small. Work that can wait belongs in
the backend after the upgrade, in batches.

### Data migrations under row-level security

A migration that changes existing rows runs as your owner role, and `FORCE ROW LEVEL SECURITY`
applies the organization policy to the owner too. The migration sets no organization, so it
sees no row: an `UPDATE` changes nothing, and a `SET NOT NULL` after it fails. Lift `FORCE` for
the file's own transaction, and put it back in the same file:

```sql
ALTER TABLE weather.saved_places NO FORCE ROW LEVEL SECURITY;
UPDATE weather.saved_places AS place SET position = numbered.position
  FROM (SELECT id, row_number() OVER (PARTITION BY org_id ORDER BY created_at, id) AS position
        FROM weather.saved_places) AS numbered
  WHERE place.id = numbered.id;
ALTER TABLE weather.saved_places FORCE ROW LEVEL SECURITY;
```

The file runs in one transaction, so no other session ever sees the table without `FORCE`. Never
end a file with it off. The Weather sample numbers each organization's saved places this way,
in `plugin-samples/weather/database/migrations/003_place_conditions.sql`.

A new table needs what the first ones have: `ENABLE` and `FORCE ROW LEVEL SECURITY`, an
organization policy `TO ${app_role}`, and grants to the roles that use it and no others. A table
whose rows belong to another table's rows names the organization in its foreign key, as
Weather's `place_conditions` does with `(org_id, place_id)`. Foreign key checks bypass
row-level security, so a key on the other row's id alone would let a row of one organization
point at another organization's row.

### When a migration fails

The run stops at the failing file, which is rolled back. The files before it stay applied. The
plugin stays offline, and the upgrade shows the failure: "`<file>` line `<n>`: [`<SQLSTATE>`]
`<message>`". The SuperAdmin can then:

- **Retry**, when the cause has passed, such as a lock held for too long;
- **Cancel the upgrade**, when none of the new version's files has run yet: the old version
  starts again;
- **Restore the backup**, when some have, and then cancel: the database goes back to what it
  was before the upgrade, and changes made since are lost;
- **upload a newer version** that fixes the file and keeps the files that already ran unchanged.

EpicStaff never rolls back by itself. See [the plugin lifecycle](../explanation/lifecycle.md).

## Test your migrations before you upload

A migration that fails at the first install keeps your backend from starting, and one that fails
during an upgrade keeps the plugin offline until a SuperAdmin restores or retries. Run your
migrations against a PostgreSQL 17 set up the way the node sets one up: the three roles, the
owner as the session user, each file in one transaction, the placeholders replaced. For a new
version, run the earlier version's files first, add rows for more than one organization, and
then run the new files. The Weather sample's tests do both, in
`src/plugin_sdk/tests/test_weather_sample_database.py` in the EpicStaff repository, and then run
the backend's stores against the result, as the app role.
