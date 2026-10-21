# Plugin database

A plugin whose manifest has `"database": {}` (which needs a `backend`) gets a PostgreSQL
database of its own, on the deployment's plugin database server. This page is the reference
for what it gets: the database, its roles and their grants, the environment, the limits and
the ledger. [Write database migrations](../how-to/database-migrations.md) shows how to use it,
and part 2 of the [tutorial](../tutorial/build-your-first-plugin.md#part-2-saved-places-in-the-plugins-database)
walks through the Weather sample's.

## When it is set up

- **Approval.** When a SuperAdmin approves a package with a `database` section, EpicStaff
  records a database for the plugin. An EpicStaff with no plugin database server registered
  refuses the approval with `409 no_plugin_database_server` ([Error codes](error-codes.md)).
- **Before the backend first starts**, the plugin node creates the database and its roles, and
  runs the package's migrations. The backend is started only once that succeeded. The plugin's
  Runtime tab shows the state: waiting for the node, setting up, ready, or failed with the
  reason.
- **At every start of the node**, it runs the set-up again before the backend starts: it puts
  the roles' attributes, the app role's password and limits, and the CONNECT grants back as this
  page describes. Roles whose memberships were changed outside EpicStaff are not put back: the
  backend is not started (see [Errors](#errors-on-the-runtime-tab)).
- **Suspending** the plugin in an organization leaves the database as it is.

This version runs the migrations of the version a SuperAdmin approved; installing a later
version of a plugin, with its new migrations, comes later.

## Names

`<id_>` is the plugin's id with every `-` replaced by `_`: `weather` gives `weather`, and
`my-plugin` gives `my_plugin`.

| Object | Name | Example for `weather` |
|---|---|---|
| Database | `plugin_<id_>` | `plugin_weather` |
| Owner role | `<id_>_owner` | `weather_owner` |
| App role | `<id_>_app` | `weather_app` |
| Job role | `<id_>_job` | `weather_job` |

The database is created from `template0`, with UTF-8 encoding, owned by the owner role.

## Roles

None of the three is a superuser, and none may create databases or roles, replicate, or bypass
row-level security (`NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS`).

| Role | Logs in | What it may do |
|---|---|---|
| Owner (`<id_>_owner`) | Only to run your migrations: the node gives it a one-time password valid for 10 minutes and one connection, and sets it back to `NOLOGIN` afterwards, whether the migrations succeeded or not | Owns the database, so it owns everything your migrations create. Your migrations run with it as the session user |
| App (`<id_>_app`) | Yes, through `DATABASE_URL`, with at most the plugin's connection limit | Only what your migrations grant it. It is a member of the job role with `SET` but without `INHERIT`: it may `SET ROLE` to the job role, and has none of the job role's privileges otherwise |
| Job (`<id_>_job`) | Never | Only what your migrations grant it. For work your backend does under `SET LOCAL ROLE <id_>_job`, with other privileges than a request has. In migrations, `${job_role}` names it |

The plugin node holds the owner role with `SET` but without `INHERIT`. It uses it to set up the
database and to give the owner its one-time password; it never connects to your database.

**CONNECT** on the database is revoked from `PUBLIC` and granted to the three roles, to the
plugin node, and to the role EpicStaff backs plugin databases up with. Your roles cannot
connect to any other database on the server, and no other plugin's roles can connect to yours.

**What your app role starts with:** nothing in your database beyond CONNECT. Grant it, in a
migration, `USAGE` on your schemas, the table privileges it needs, and `USAGE` on the sequences
of identity and serial columns it inserts into.

## Environment

The backend's process gets these, on top of the [runtime environment](runtime.md#environment):

| Variable | Value |
|---|---|
| `DATABASE_URL` | `postgresql://<id_>_app:<password>@<host>:<port>/plugin_<id_>?application_name=<id>`. It holds the app role's password: never log it, show it, or put it on a command line |
| `EPICSTAFF_PLUGIN_DB_CONNECTIONS` | The app role's connection limit, a positive integer. Size your connection pool to it |

The Python SDK reads both: `epicstaff_plugin.database.database_url()` and `connection_limit()`
([Python SDK](python-sdk.md#epicstaff_plugindatabase)).

## Limits

| Limit | Manifest field | What it does |
|---|---|---|
| Connections | `limits.db_connections` | The app role's `CONNECTION LIMIT`. **Hard:** PostgreSQL refuses a connection over it |
| Statement timeout | `limits.statement_timeout_seconds` | The app role's default `statement_timeout`. **Advisory:** a session can change it for itself (`SET statement_timeout`), and the platform restores the role's default within about a minute when the role's own setting is changed |

Both are capped by the deployment's maximums, and a SuperAdmin may lower them per plugin
([Limits](limits.md)). A change restarts the backend.

The platform owns every role-level setting of the app role: it resets any other setting it
finds on the role, in any database. Set defaults for your database with `ALTER DATABASE … SET`
in a migration ([Write database migrations](../how-to/database-migrations.md#7-set-defaults-on-the-database-not-on-the-role)); the
role's statement timeout still takes precedence.

## Migrations

- Files `database/migrations/NNN_<name>.sql` in the package: `NNN` three digits, `<name>`
  lower-case letters, digits and `_`, each number once. They run in name order.
- At most 64 MiB of migrations in total (`epicstaff_plugin.package_layout.MAX_MIGRATIONS_TOTAL_BYTES`):
  the node holds them in memory while it runs them. `epicstaff-plugin validate` and `pack`, and
  EpicStaff's upload, refuse more at `package.database`.
- Each file runs once, whole, in its own transaction, with the owner as the session user, with
  a statement timeout of 15 minutes and a lock timeout of 60 seconds. A file that fails is rolled
  back alone, the run stops, and the backend is not started. The Runtime tab names the file and
  PostgreSQL's error code and message: `<name> line <n>: [<SQLSTATE>] <message>` when PostgreSQL
  gives the error a position in the file (a syntax error, for example), and
  `<name>: [<SQLSTATE>] <message>` for an error raised while a statement ran, which has none.
- Placeholders, replaced by the quoted role names before a file runs: `${owner_role}`,
  `${app_role}`, `${job_role}`.
- Trusted extensions can be created (for example `pgcrypto`); untrusted ones, such as `dblink`
  and `postgres_fdw`, cannot.

### The ledger

The node records each file it ran in `_epicstaff.migrations`, with its name, its SHA-256 and
when it ran, and skips it the next time. A file whose content changed after it ran is refused:
"`<name>` changed after it was applied". The ledger is owned by your owner role, so a
migration could rewrite it: it guards against mistakes, not against your own code. Leave the
`_epicstaff` schema alone.

## What other plugins can see

Several plugins share the database server. Another plugin's roles cannot connect to your
database, so they can never read your data. But PostgreSQL's catalogs of databases and roles are
shared by the whole server, so other plugins can see your database's name and your roles' names.
Keep nothing secret in names.

## Shared server

- **Connection slots.** The server's connections are shared by every plugin on it. Your
  connection limit caps what you can hold, but plugins together can hold all of the server's
  free slots, and a new connection then fails until one is closed. Hold connections in a pool,
  sized to your limit, and return them promptly. The node keeps slots of its own, so it can always
  reach the server.
- **No disk quota.** PostgreSQL cannot cap one database's size. The Runtime tab shows your
  database's size; operators watch the server's volume.

## Errors on the Runtime tab

| Message | What happened |
|---|---|
| "plugins_db already has … that this plugin installation did not create, …" | The server holds a database or roles of that name from somewhere else, for example from an EpicStaff database that was reset or restored without the plugin database server. The node refuses to adopt them. An operator resolves it ([Enable the plugin platform](../operator/enable-plugins.md)), then a SuperAdmin presses Restart |
| "`<name>` line `<n>`: [`<SQLSTATE>`] `<message>`" | That migration failed at that line, and was rolled back |
| "`<name>`: [`<SQLSTATE>`] `<message>`" | That migration failed while a statement ran (a constraint, a timeout, a missing object, for example), and was rolled back |
| "`<name>` changed after it was applied" | A migration's content differs from the one that ran |
| "database permissions changed outside EpicStaff: …" | The roles' memberships or the database's CONNECT grants were changed; the node stopped the backend |
