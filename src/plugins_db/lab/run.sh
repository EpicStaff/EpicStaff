#!/usr/bin/env bash
# The plugin database lab. Starts a throwaway plugins_db exactly as src/docker-compose.yaml
# defines it (compose.yaml here extends that service: its image, command, init script and
# pg_hba.conf), with random passwords, on a free loopback port. Then:
#
#   - runs every es_plugins and plugin_sdk test marked `postgres` against it, through
#     ES_PLUGINS_TEST_PG_HOST, _PORT and _ADMIN_PASSWORD. ES_PLUGINS_TEST_ASG_MIGRATIONS_DIR is
#     passed on when it is set; ASG's migrations are skipped without it;
#   - checks the server itself: the superuser is refused over TCP, nobody else gets in over the
#     socket, the attributes and memberships of plugins_admin and plugins_backup, CONNECT on
#     postgres and template1 closed to PUBLIC, the server settings, no secret in its log, and
#     that the init script changes nothing when run by hand on the live server;
#   - starts it again on a fresh volume with weak passwords: every start refuses, naming the
#     variables but not their values, and the same volume initializes once they are fixed.
#
# One `ok -` / `not ok -` line per check; removes every container, volume and network it made.
# Needs Docker, the es_plugins and plugin_sdk venvs (`make uv-sync svc=<service>`), and python3
# with PyYAML (scripts/envtool.py writes the env file the extended service needs).
# Usage, from anywhere: bash src/plugins_db/lab/run.sh
set -euo pipefail

lab_dir=$(cd "$(dirname "$0")" && pwd)
repository=$(cd "$lab_dir/../../.." && pwd)
work=$(mktemp -d)
server=plugins-db-lab

python3 "$repository/scripts/envtool.py" --dev --env-file "$work/lab.env" > /dev/null
random_password() { od -An -N32 -tx1 /dev/urandom | tr -d ' \n'; }
# The shell's values win over the env file's.
PLUGINS_DB_SUPERUSER_PASSWORD=$(random_password)
PLUGINS_DB_ADMIN_PASSWORD=$(random_password)
PLUGINS_DB_BACKUP_PASSWORD=$(random_password)
export PLUGINS_DB_SUPERUSER_PASSWORD PLUGINS_DB_ADMIN_PASSWORD PLUGINS_DB_BACKUP_PASSWORD
export PLUGINS_DB_MAX_CONNECTIONS=100

compose() {
  docker compose -p plugins-db-lab -f "$lab_dir/compose.yaml" --env-file "$work/lab.env" \
    --profile plugins "$@"
}
cleanup() {
  compose down -v --remove-orphans > /dev/null 2>&1 || true
  rm -rf "$work"
}
trap cleanup EXIT
compose down -v --remove-orphans > /dev/null 2>&1 || true

failures=0
pass() { echo "ok - $1"; }
fail() {
  echo "not ok - $1"
  failures=$((failures + 1))
}
check() { # description, then a command that succeeds when the check holds
  local description=$1
  shift
  if "$@" > "$work/check-output" 2>&1; then
    pass "$description"
  else
    fail "$description: $(head -c 600 "$work/check-output")"
  fi
}
equals() { # actual, expected
  if [ "$1" = "$2" ]; then return 0; fi
  echo "got '$1', expected '$2'"
  return 1
}
contains() { case "$1" in *"$2"*) return 0 ;; esac; echo "'$2' not in: $1"; return 1; }
lacks() { case "$1" in *"$2"*) echo "found '$2'"; return 1 ;; esac; return 0; }
wait_for() { # seconds, then a command; returns once the command succeeds
  local deadline=$((SECONDS + $1))
  shift
  until "$@" > /dev/null 2>&1; do
    if [ "$SECONDS" -ge "$deadline" ]; then
      return 1
    fi
    sleep 1
  done
}
# The superuser on the container's socket, the one way in that pg_hba.conf leaves it.
superuser_query() { docker exec -u postgres "$server" psql -X -At -v ON_ERROR_STOP=1 -c "$1"; }
start_server() {
  if ! compose up -d --wait --wait-timeout 180 plugins_db > "$work/up.log" 2>&1; then
    cat "$work/up.log"
    docker logs "$server" 2>&1 | tail -n 40
    return 1
  fi
}
refusals_at_least() { # count
  [ "$(docker logs "$server" 2>&1 | grep -c 'must be at least 32 characters')" -ge "$1" ]
}
has_stopped() { [ "$(docker inspect -f '{{.State.Status}}' "$server")" = exited ]; }

echo "# plugins_db with the init script and pg_hba.conf"
start_server
port=$(compose port plugins_db 5432)
port=${port##*:}
pass "plugins_db initializes and becomes healthy ($(superuser_query 'SHOW server_version'))"
check "the init script made exactly plugins_admin and plugins_backup" \
  equals "$(superuser_query "SELECT string_agg(rolname, ' ' ORDER BY rolname) FROM pg_roles WHERE rolname !~ '^pg_'")" \
  'plugins_admin plugins_backup postgres'

echo "# the tests marked postgres"
if [ -n "${ES_PLUGINS_TEST_ASG_MIGRATIONS_DIR:-}" ]; then
  echo "# ASG's migrations: $ES_PLUGINS_TEST_ASG_MIGRATIONS_DIR"
else
  echo "# ASG's migrations: skipped (ES_PLUGINS_TEST_ASG_MIGRATIONS_DIR is not set)"
fi
for service in es_plugins plugin_sdk; do
  if ES_PLUGINS_TEST_PG_HOST=127.0.0.1 ES_PLUGINS_TEST_PG_PORT=$port \
    ES_PLUGINS_TEST_PG_ADMIN_PASSWORD=$PLUGINS_DB_ADMIN_PASSWORD \
    make -C "$repository" --no-print-directory "$service-tests" ARGS="-m postgres"; then
    pass "$service: every test marked postgres passes against plugins_db"
  else
    fail "$service: tests marked postgres (output above)"
  fi
done

echo "# who gets in"
container_address=$(docker exec "$server" hostname -i | awk '{ print $1 }')
for address in 127.0.0.1 "$container_address"; do
  refused=$(PGPASSWORD=$PLUGINS_DB_SUPERUSER_PASSWORD docker exec -e PGPASSWORD "$server" \
    psql -X "host=$address user=postgres dbname=postgres connect_timeout=5" -c 'SELECT 1' 2>&1 || true)
  check "the superuser is refused over TCP to $address, with its own password" \
    contains "$refused" 'pg_hba.conf rejects connection'
done
refused=$(docker exec -u postgres "$server" psql -X -U plugins_admin -d postgres -c 'SELECT 1' 2>&1 || true)
check "no role but the superuser gets in over the socket" \
  contains "$refused" 'pg_hba.conf rejects connection for host "[local]"'
wrong_password=$(PGPASSWORD=not-the-password docker exec -e PGPASSWORD "$server" \
  psql -X "host=127.0.0.1 user=plugins_admin dbname=postgres connect_timeout=5" -c 'SELECT 1' 2>&1 || true)
check "plugins_admin with a wrong password is refused" \
  contains "$wrong_password" 'password authentication failed for user "plugins_admin"'
admin_over_tcp=$(PGPASSWORD=$PLUGINS_DB_ADMIN_PASSWORD docker exec -e PGPASSWORD "$server" \
  psql -X -At "host=127.0.0.1 user=plugins_admin dbname=postgres" -c 'SELECT current_user' 2>&1 || true)
check "plugins_admin logs in over TCP with its password" equals "$admin_over_tcp" plugins_admin
check "plugins_admin's password is stored as a SCRAM verifier" \
  equals "$(superuser_query "SELECT rolpassword LIKE 'SCRAM-SHA-256\$%' FROM pg_authid WHERE rolname = 'plugins_admin'")" t

echo "# the roles the init script made"
roles="SELECT rolsuper, rolcreaterole, rolcreatedb, rolcanlogin, rolreplication, rolbypassrls FROM pg_roles WHERE rolname ="
check "plugins_admin: LOGIN CREATEDB CREATEROLE, no SUPERUSER, REPLICATION or BYPASSRLS" \
  equals "$(superuser_query "$roles 'plugins_admin'")" 'f|t|t|t|f|f'
check "plugins_backup: LOGIN BYPASSRLS, no SUPERUSER, CREATEDB, CREATEROLE or REPLICATION" \
  equals "$(superuser_query "$roles 'plugins_backup'")" 'f|f|f|t|f|t'
memberships="SELECT coalesce(string_agg(r.rolname || ' admin=' || m.admin_option || ' inherit=' || m.inherit_option
  || ' set=' || m.set_option, ', ' ORDER BY r.rolname), '-') FROM pg_auth_members m
  JOIN pg_roles r ON r.oid = m.roleid JOIN pg_roles u ON u.oid = m.member WHERE u.rolname ="
check "plugins_admin is a member of pg_use_reserved_connections only" \
  equals "$(superuser_query "$memberships 'plugins_admin'")" 'pg_use_reserved_connections admin=false inherit=true set=true'
check "plugins_backup is a member of pg_read_all_data only" \
  equals "$(superuser_query "$memberships 'plugins_backup'")" 'pg_read_all_data admin=false inherit=true set=true'

echo "# CONNECT on the maintenance databases"
connect="SELECT has_database_privilege('public', datname, 'CONNECT') || ' ' || has_database_privilege('plugins_admin', datname, 'CONNECT')
  || ' ' || has_database_privilege('plugins_backup', datname, 'CONNECT') FROM pg_database WHERE datname ="
check "postgres: closed to PUBLIC and plugins_backup, open to plugins_admin" \
  equals "$(superuser_query "$connect 'postgres'")" 'false true false'
check "template1: closed to PUBLIC, plugins_admin and plugins_backup" \
  equals "$(superuser_query "$connect 'template1'")" 'false false false'

echo "# the server"
settings=$(superuser_query "SELECT current_setting('hba_file') || ' ' || current_setting('password_encryption') || ' '
  || current_setting('max_connections') || ' ' || current_setting('reserved_connections') || ' '
  || current_setting('authentication_timeout')")
check "hba_file, password_encryption, max_connections, reserved_connections, authentication_timeout" \
  equals "$settings" '/etc/postgresql/pg_hba.conf scram-sha-256 100 5 10s'
check "the server runs with no-new-privileges" \
  contains "$(docker inspect -f '{{.HostConfig.SecurityOpt}}' "$server")" 'no-new-privileges:true'
server_log=$(docker logs "$server" 2>&1)
for name in PLUGINS_DB_SUPERUSER_PASSWORD PLUGINS_DB_ADMIN_PASSWORD PLUGINS_DB_BACKUP_PASSWORD; do
  check "$name's value is nowhere in the server's log" lacks "$server_log" "${!name}"
done
check "no SCRAM verifier is in the server's log" lacks "$server_log" 'SCRAM-SHA-256$'

rerun=$(docker exec -u postgres "$server" /docker-entrypoint-initdb.d/001_plugins_admin.sh 2>&1 || true)
check "run by hand on the live server, the init script refuses" \
  contains "$rerun" 'runs only while the image initializes'
check "... and the server keeps its roles" \
  equals "$(superuser_query "SELECT count(*) FROM pg_roles WHERE rolname IN ('plugins_admin', 'plugins_backup')")" 2

echo "# weak passwords"
compose down -v > /dev/null 2>&1
weak_backup_password=$(random_password | cut -c 1-31)
PLUGINS_DB_ADMIN_PASSWORD=none PLUGINS_DB_BACKUP_PASSWORD=$weak_backup_password \
  compose up -d plugins_db > /dev/null 2>&1 || true
if wait_for 120 refusals_at_least 2; then
  # Let the attempt under way finish, so no start is cut off between initdb and the script.
  docker update --restart=no "$server" > /dev/null
  wait_for 60 has_stopped || true
  weak_log=$(docker logs "$server" 2>&1)
  check "every start refuses, naming exactly the two weak variables" \
    contains "$weak_log" 'plugins_db: PLUGINS_DB_ADMIN_PASSWORD PLUGINS_DB_BACKUP_PASSWORD must be at least 32 characters'
  check "the refusal never prints the weak value" lacks "$weak_log" "$weak_backup_password"
  check "a refused start leaves no cluster: the next start initializes again instead of skipping it" \
    lacks "$weak_log" 'Skipping initialization'
  if start_server; then
    check "with the values fixed, the same volume initializes and has plugins_admin" \
      equals "$(superuser_query "SELECT count(*) FROM pg_roles WHERE rolname = 'plugins_admin'")" 1
  else
    fail "plugins_db did not start on the refused volume with the values fixed"
  fi
else
  fail "plugins_db with weak passwords did not refuse twice: $(docker logs "$server" 2>&1 | tail -n 20)"
fi

if [ "$failures" -ne 0 ]; then
  echo "FAILED: $failures check(s)"
  exit 1
fi
echo "All plugin database lab checks passed."
