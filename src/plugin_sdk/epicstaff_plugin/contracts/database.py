"""How a plugin's database migrations name roles, and where the applied ones are recorded.

A migration is a `database/migrations/NNN_<name>.sql` file of the package. It never spells a
role's name: it writes `${owner_role}`, `${app_role}` or `${job_role}`, and whoever applies it
replaces each with that role's name as a quoted SQL identifier:

- `owner_role` owns the database and every object the migrations create; migrations run as it.
- `app_role` is the role the backend logs in as (`DATABASE_URL`).
- `job_role` is the role `epicstaff_plugin.database.job_transaction` switches to.

The plugin node gives each its own role. `epicstaff-plugin dev --apply-migrations` applies the
same files to an author's local database, where the login role plays owner and app.

Each applied file is recorded in the ledger table `_epicstaff.migrations`, in the database the
migrations ran in: `name text PRIMARY KEY` (the file name), `sha256 text NOT NULL` (of the
file's bytes, before any placeholder is replaced) and `applied_at timestamptz NOT NULL DEFAULT
now()`. A file the ledger lists with the same digest is skipped; with another digest, the run
stops.
"""

MIGRATION_PLACEHOLDERS = ("owner_role", "app_role", "job_role")
"""The role names a migration may use, each written as `${<name>}`."""

MIGRATIONS_LEDGER_SCHEMA = "_epicstaff"
MIGRATIONS_LEDGER_TABLE = "migrations"
