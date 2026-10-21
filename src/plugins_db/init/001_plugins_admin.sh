#!/usr/bin/env bash
# The only step plugins_db runs as the superuser. The postgres image runs this once, as the
# postgres OS user over the local socket, while it initializes an empty data directory. It creates
# the two roles the platform logs in with and closes the maintenance databases to everyone else.
# The plugin node makes every plugin's roles afterwards, as plugins_admin, never as the superuser.
set -euo pipefail

# pg_hba.conf lets in only this superuser name, and only on the socket.
superuser_psql=(psql -X -v ON_ERROR_STOP=1 --username postgres --dbname postgres)

# The image initializes with a server that listens on no TCP address; the server it runs
# afterwards listens. Run by hand against a live server, this script changes nothing.
if [ -n "$("${superuser_psql[@]}" -Atc 'SHOW listen_addresses')" ]; then
  echo "plugins_db: this script runs only while the image initializes an empty data directory" >&2
  exit 1
fi

# The image runs this directory only on an empty data directory. A cluster left behind by a failed
# run would make the next start skip this script and serve without plugins_admin. So a failure
# stops the initialization server and removes the cluster this start made: every later start
# initializes again, and refuses again until the values are fixed.
discard_new_cluster() {
  local status=$?
  if [ "$status" -ne 0 ]; then
    pg_ctl -D "$PGDATA" -m fast -w stop > /dev/null 2>&1 || true
    find "$PGDATA" -mindepth 1 -delete
    echo "plugins_db: initialization failed; the new cluster was removed, so the next start initializes again" >&2
  fi
}
trap discard_new_cluster EXIT

# The plugin node refuses a weak admin password by the same rule. Names only, never values.
weak_variables=()
refuse_weak() { # the variable in this container, the name the operator sets
  local value=${!1:-}
  if [ "$value" = none ] || [ "${#value}" -lt 32 ]; then
    weak_variables+=("$2")
  fi
}
refuse_weak POSTGRES_PASSWORD PLUGINS_DB_SUPERUSER_PASSWORD
refuse_weak PLUGINS_DB_ADMIN_PASSWORD PLUGINS_DB_ADMIN_PASSWORD
refuse_weak PLUGINS_DB_BACKUP_PASSWORD PLUGINS_DB_BACKUP_PASSWORD
if [ "${#weak_variables[@]}" -ne 0 ]; then
  echo "plugins_db: ${weak_variables[*]} must be at least 32 characters and not 'none' (openssl rand -hex 32)" >&2
  exit 1
fi

# \getenv reads the passwords inside psql, so they never appear on a command line, which every
# user of the Docker host can read. A failing statement may carry a password, so its text is never
# logged: not in this session, and not in any session of plugins_admin, which only a superuser
# could change back. psql applies --single-transaction to -f, not to plain standard input.
"${superuser_psql[@]}" --single-transaction -f - <<'SQL'
SET log_min_error_statement = panic;
\getenv admin_password PLUGINS_DB_ADMIN_PASSWORD
\getenv backup_password PLUGINS_DB_BACKUP_PASSWORD
CREATE ROLE plugins_admin LOGIN CREATEDB CREATEROLE NOSUPERUSER NOREPLICATION NOBYPASSRLS PASSWORD :'admin_password';
ALTER ROLE plugins_admin SET log_min_error_statement = panic;
ALTER ROLE plugins_admin SET log_statement = 'none';
-- pg_hba.conf refuses its logins until backups use it.
CREATE ROLE plugins_backup LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION BYPASSRLS PASSWORD :'backup_password';
GRANT pg_read_all_data TO plugins_backup;
-- Connection slots no plugin can take, so plugins cannot lock the node out.
GRANT pg_use_reserved_connections TO plugins_admin;
-- Ending a plugin's sessions (never a superuser's), before its owner is closed or its database
-- dropped.
GRANT pg_signal_backend TO plugins_admin;
REVOKE CONNECT ON DATABASE postgres, template1 FROM PUBLIC;
GRANT CONNECT ON DATABASE postgres TO plugins_admin;
SQL
