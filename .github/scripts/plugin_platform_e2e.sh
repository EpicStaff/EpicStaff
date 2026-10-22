#!/usr/bin/env bash
# The plugin platform end to end, on a stack of its own, the same way on macOS, on Linux and in CI
# (.github/workflows/plugin-platform-stack.yml). Its stages run in order, and the first failure
# stops it:
#   1. environment: a throwaway env file from scripts/envtool.py --dev with the run's settings and
#      random secrets; it refuses to start while another EpicStaff stack's containers exist, since
#      src/docker-compose.yaml fixes their names, and while the run's Compose project already has
#      containers, volumes or networks, which are not this run's to use or remove;
#   2. names: EpicStaff's and the plugin's host names resolve to 127.0.0.1;
#   3. stack: the services listed in the stage, built with the run's own image tag;
#   4. package: the JS SDK, the sample page, the SDK wheel, and Weather packed for this machine's
#      architecture and signed with the run's own key, which the stack trusts;
#   5. browsers: the seed (people, organizations, Weather installed and granted), then the browser
#      suite in Chromium, Firefox and WebKit;
#   6. smokes: STACK_SMOKES, each of which restores what it changes;
#   7. development: django_app and epicstaff-nginx recreated with PLUGINS_DEV_MODE=true and
#      src/docker-compose.plugins-dev.yaml, then the development smoke;
#   8. final smokes: FINAL_SMOKES, which change the stack for good;
# then, always, the teardown and a summary of the stages with their durations.
#
# Settings, from the environment (all optional):
#   E2E_ARTIFACTS_DIR  where a failed run copies the browser suite's report and traces and the
#                      containers' logs, with the run's secrets replaced (default: a directory
#                      named after the run in TMPDIR, printed at the end)
#   E2E_KEEP_STACK     true: leave the stack running at the end, and print its env file and how
#                      to remove it (default false)
#   E2E_PROJECT        the Compose project (default epicstaff-plugin-e2e); one that has no
#                      containers, volumes or networks yet
#   Any variable of src/env.yaml overrides the env file, the run's settings below included,
#   except IMAGE_TAG, COMPOSE_PROFILES, PLUGINS_NETWORK_SUBNET, PLUGINS_DEV_MODE and the secrets,
#   which every run sets itself.
#
# Needs Docker with Compose 2.24.4 or later, python3 with PyYAML, uv, Node 24.15 or later with
# npm, and curl, plus network access for images, packages and browsers. Nothing it makes outlives
# it: `down -v` removes the containers, volumes and networks, and it removes the images it built
# with its own tag, never :latest and never a pulled one. It prints no secret.
#
# Usage, from anywhere: bash .github/scripts/plugin_platform_e2e.sh
set -euo pipefail

# >>> env_bool
# Strict boolean environment flag, accepting exactly the values Env.bool accepts
# (src/shared/envtools.py). Copied verbatim into every script that needs it;
# .github/scripts/check_env_conventions.py fails CI if the copies or the values drift.
# Usage: if env_bool NAME [DEFAULT]; then ...; fi
# Returns 0 for true and 1 for false. DEFAULT applies only when NAME is unset.
# An unset NAME without DEFAULT, or any other value, exits the script with 64.
env_bool() {
  eval "env_bool_is_set=\${$1+set}"
  if [ -n "$env_bool_is_set" ]; then
    eval "env_bool_value=\${$1}"
  elif [ $# -ge 2 ]; then
    env_bool_value=$2
  else
    echo "ERROR: environment variable $1 is not set." >&2
    exit 64
  fi
  case "$(printf '%s' "$env_bool_value" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | tr '[:upper:]' '[:lower:]')" in
    1|on|t|true|y|yes) return 0 ;;
    0|f|false|n|no|off) return 1 ;;
  esac
  echo "ERROR: environment variable $1='$env_bool_value' is not a boolean. Use one of 1, on, t, true, y, yes for true or 0, f, false, n, no, off for false (case-insensitive)." >&2
  exit 64
}
# <<< env_bool

repository=$(cd "$(dirname "$0")/../.." && pwd)
scripts_dir="$repository/.github/scripts"
nginx_tests="$repository/src/nginx/tests"
browser_suite="$repository/plugin-sdk/test-browser"
sample="$repository/plugin-samples/weather"
plugin=weather
project=${E2E_PROJECT:-epicstaff-plugin-e2e}
run_id=$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n')
artifacts=${E2E_ARTIFACTS_DIR:-${TMPDIR:-/tmp}/plugin-platform-e2e-$run_id}
keep_stack=0
if env_bool E2E_KEEP_STACK false; then
  keep_stack=1
fi
in_github_actions=0
if env_bool GITHUB_ACTIONS false; then
  in_github_actions=1
fi
work=$(mktemp -d)
chmod 700 "$work"

compose_files=(-f "$repository/src/docker-compose.yaml" -f "$scripts_dir/plugin_platform_e2e.compose.yaml")
compose() { docker compose -p "$project" "${compose_files[@]}" --env-file "$work/e2e.env" "$@"; }
# The services this run builds, with the run's own image tag; the teardown removes those images.
built_services=(crewdb django_app frontend es_plugins plugins_egress)

all_stages=(environment names stack package browsers smokes development final-smokes)
stage_lines=()
current_stage=""
stage_started=0
stack_started=0

fail_run() {
  echo "ERROR: $1" >&2
  exit 1
}

finish_stage() { # result
  if [ -n "$current_stage" ]; then
    stage_lines+=("$(printf '%-14s %-8s %5d s' "$current_stage" "$1" $((SECONDS - stage_started)))")
    current_stage=""
  fi
}
begin_stage() { # name
  finish_stage ok
  current_stage=$1
  stage_started=$SECONDS
  echo
  echo "## $1"
}

# Every secret of the run: masked in GitHub's log as soon as it exists, and replaced in the
# containers' logs a failed run keeps.
remember_secret() {
  printf '%s\n' "$1" >> "$work/secrets"
  if [ "$in_github_actions" = 1 ]; then
    echo "::add-mask::$1"
  fi
}
random_secret() { od -An -N32 -tx1 /dev/urandom | tr -d ' \n'; }

# stack_value PATH: one value of the stack file the seed wrote, by its dotted path
# (people.ada.email). Printed for a caller to capture, never to the log. A value that is missing,
# or still null (the seed writes the file early and fills it in as it goes), fails with the reason.
stack_value() {
  python3 -c '
import json, sys
value = json.load(open(sys.argv[1], encoding="utf-8"))
for part in sys.argv[2].split("."):
    value = value.get(part) if isinstance(value, dict) else None
if value is None:
    sys.exit(
        f"ERROR: the stack file {sys.argv[1]} has no {sys.argv[2]}: the seed did not finish. "
        "Run it again: npm --prefix plugin-sdk/test-browser run e2e:seed"
    )
print(value)' "$work/stack.json" "$1"
}

# wait_for SECONDS COMMAND...: returns once the command succeeds, fails after the time.
wait_for() {
  local deadline=$((SECONDS + $1))
  shift
  until "$@" > /dev/null 2>&1; do
    if [ "$SECONDS" -ge "$deadline" ]; then
      return 1
    fi
    sleep 2
  done
}
is_healthy() { # service
  local container
  container=$(compose ps -q "$1")
  [ -n "$container" ] && [ "$(docker inspect -f '{{.State.Health.Status}}' "$container")" = healthy ]
}
wait_healthy() { # service, seconds
  echo "waiting for $1 to be healthy (at most $2 s)"
  if ! wait_for "$2" is_healthy "$1"; then
    compose logs --no-color --tail 40 "$1" | redact_stream
    fail_run "$1 did not become healthy within $2 s"
  fi
}

# Copies standard input to standard output with every secret of the run replaced.
redact_stream() {
  python3 -c '
import sys
secrets = [line.rstrip("\n") for line in open(sys.argv[1], encoding="utf-8") if line.strip()]
text = sys.stdin.read()
for secret in sorted(secrets, key=len, reverse=True):
    text = text.replace(secret, "<redacted>")
sys.stdout.write(text)' "$work/secrets"
}

# A SuperAdmin's access token, from one login; printed for a caller to capture.
superadmin_token() {
  E2E_LOGIN_FILE="$work/login.json" python3 -c '
import json, os
descriptor = os.open(os.environ["E2E_LOGIN_FILE"], os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(descriptor, "w", encoding="utf-8") as login_file:
    json.dump({"email": os.environ["E2E_SUPERADMIN_EMAIL"], "password": os.environ["E2E_SUPERADMIN_PASSWORD"]}, login_file)'
  curl -sS --fail --max-time 30 -X POST -H 'Content-Type: application/json' \
    --data-binary "@$work/login.json" "$epicstaff_url/api/auth/login/" > "$work/login-answer.json"
  rm -f "$work/login.json"
  python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["access"])' "$work/login-answer.json"
  rm -f "$work/login-answer.json"
}

# A stack smoke uses curl, python3 and Docker at most, takes its inputs from the environment,
# prints no secret, and restores what it changes (a trap). Each runs as smoke_<name> below, which
# maps its inputs from the stack file. A new one joins STACK_SMOKES, state-changing ones last; one
# that changes the stack for good joins FINAL_SMOKES instead, which run after the development
# leg, on this script's own stack only.
STACK_SMOKES=(plugins login service_account suspend)
FINAL_SMOKES=(upgrade purge)

smoke_plugins() {
  local token
  token=$(superadmin_token)
  remember_secret "$token"
  SMOKE_ADMIN_TOKEN=$token EPICSTAFF_URL=$epicstaff_url PLUGINS_BASE_DOMAIN=$PLUGINS_BASE_DOMAIN \
    PLUGIN_IDENTIFIER=$plugin PLUGINS_MAX_PACKAGE_MB=$PLUGINS_MAX_PACKAGE_MB \
    bash "$nginx_tests/plugins_smoke.sh"
}
smoke_login() {
  SMOKE_BASE_URL=$epicstaff_url SMOKE_PLUGIN=$plugin SMOKE_EMAIL=$(stack_value people.ada.email) \
    SMOKE_PASSWORD=$(stack_value people.ada.password) SMOKE_ORG_ID=$(stack_value organizations.a.id) \
    bash "$nginx_tests/login_smoke.sh"
}
smoke_service_account() {
  SMOKE_BASE_URL=$epicstaff_url SMOKE_PLUGIN=$plugin SMOKE_ORG_ID=$(stack_value organizations.a.id) \
    SMOKE_PERSON_ID=$(stack_value people.ada.id) SMOKE_OUTSIDER_ID=$(stack_value people.bob.id) \
    SMOKE_NO_VIEW_ID=$(stack_value people.vic.id) \
    bash "$nginx_tests/service_account_smoke.sh"
}
smoke_suspend() {
  SMOKE_BASE_URL=$epicstaff_url SMOKE_PLUGIN=$plugin SMOKE_ORG_ID=$(stack_value organizations.a.id) \
    SMOKE_PLUGIN_FLOW_ID=$(stack_value flow_id) SMOKE_SUPERADMIN_EMAIL=$E2E_SUPERADMIN_EMAIL \
    SMOKE_SUPERADMIN_PASSWORD=$E2E_SUPERADMIN_PASSWORD SMOKE_ORG_ADMIN_EMAIL=$(stack_value people.olga.email) \
    SMOKE_ORG_ADMIN_PASSWORD=$(stack_value people.olga.password) \
    bash "$nginx_tests/suspend_smoke.sh"
}
smoke_development() {
  SMOKE_BASE_URL=$epicstaff_url SMOKE_PLUGINS_BASE_DOMAIN=$PLUGINS_BASE_DOMAIN SMOKE_PLUGIN=$plugin \
    SMOKE_ORG_ID=$(stack_value organizations.a.id) SMOKE_SUPERADMIN_EMAIL=$E2E_SUPERADMIN_EMAIL \
    SMOKE_SUPERADMIN_PASSWORD=$E2E_SUPERADMIN_PASSWORD SMOKE_DEV_API_PORT=$PLUGINS_DEV_API_PORT \
    SMOKE_NODE_KEY=$PLUGINS_NODE_KEY \
    bash "$nginx_tests/development_smoke.sh"
}
smoke_upgrade() {
  local plugin_uid
  plugin_uid=$(docker exec -u root "$(compose ps -q es_plugins)" stat -c %u "/var/lib/es_plugins/data/$plugin")
  SMOKE_BASE_URL=$epicstaff_url SMOKE_PLUGINS_BASE_DOMAIN=$PLUGINS_BASE_DOMAIN SMOKE_PLUGIN=$plugin \
    SMOKE_ORG_ID=$(stack_value organizations.a.id) SMOKE_SAMPLE_DIR=$sample SMOKE_SDK_WHEEL=$sdk_wheel \
    SMOKE_PLUGIN_UID=$plugin_uid SMOKE_SUPERADMIN_EMAIL=$E2E_SUPERADMIN_EMAIL \
    SMOKE_SUPERADMIN_PASSWORD=$E2E_SUPERADMIN_PASSWORD SMOKE_MEMBER_EMAIL=$(stack_value people.ada.email) \
    SMOKE_MEMBER_PASSWORD=$(stack_value people.ada.password) \
    bash "$nginx_tests/upgrade_smoke.sh" --yes
}
smoke_purge() {
  SMOKE_BASE_URL=$epicstaff_url SMOKE_PLUGINS_BASE_DOMAIN=$PLUGINS_BASE_DOMAIN SMOKE_PLUGIN=$plugin \
    SMOKE_ORG_ID=$(stack_value organizations.a.id) SMOKE_ORG_NAME=$(stack_value organizations.a.name) \
    SMOKE_SUPERADMIN_EMAIL=$E2E_SUPERADMIN_EMAIL SMOKE_SUPERADMIN_PASSWORD=$E2E_SUPERADMIN_PASSWORD \
    bash "$nginx_tests/purge_smoke.sh" --yes
}

collect_artifacts() {
  mkdir -p "$artifacts"
  for directory in playwright-report test-results; do
    if [ -d "$browser_suite/$directory" ]; then
      cp -R "$browser_suite/$directory" "$artifacts/"
    fi
  done
  if [ "$stack_started" = 1 ]; then
    compose logs --no-color --timestamps 2>&1 | redact_stream > "$artifacts/compose.log"
  fi
  echo "the browser report, traces and container logs are in $artifacts"
}

# The teardown: every profile (es_plugins, plugins_egress and plugins_db are in one) and every
# compose file the run used, the development one once the development leg added it. remove_stack
# runs it; a kept stack prints it.
teardown_command() {
  teardown=(docker compose -p "$project" "${compose_files[@]}" --env-file "$work/e2e.env"
    --profile '*' down -v --remove-orphans)
}
project_containers() { docker ps -a -q --filter "label=com.docker.compose.project=$project"; }

remove_stack() {
  local images image teardown
  images=$(compose config --format json 2> /dev/null | python3 -c '
import json, sys
services = json.load(sys.stdin)["services"]
for name in sys.argv[1:]:
    print(services[name].get("image", ""))' "${built_services[@]}" 2> /dev/null || true)
  teardown_command
  "${teardown[@]}" > "$work/down.log" 2>&1 || cat "$work/down.log"
  # Only the images this run built: each carries the run's own tag.
  for image in $images; do
    case "$image" in
      *":$IMAGE_TAG") docker image rm "$image" > /dev/null 2>&1 || true ;;
    esac
  done
}

finish() {
  local status=$?
  set +e
  if [ "$status" = 0 ]; then
    finish_stage ok
  else
    finish_stage failed
    collect_artifacts
  fi
  echo
  echo "## teardown"
  # Only containers this run made: the environment stage refuses a project that has any.
  if [ "$stack_started" = 1 ] && [ "$keep_stack" = 1 ] && [ -n "$(project_containers)" ]; then
    local teardown
    teardown_command
    echo "the stack keeps running as Compose project $project; its env file is $work/e2e.env and its stack file $work/stack.json"
    echo "remove it with: $(printf '%q ' "${teardown[@]}")&& rm -rf $(printf '%q' "$work")"
  else
    if [ "$stack_started" = 1 ]; then
      remove_stack
      echo "the stack, its volumes and the images built for this run are removed"
    fi
    rm -rf "$work"
  fi
  echo
  echo "## summary"
  local line stage reached
  for line in "${stage_lines[@]+"${stage_lines[@]}"}"; do
    echo "  $line"
  done
  for stage in "${all_stages[@]}"; do
    reached=0
    for line in "${stage_lines[@]+"${stage_lines[@]}"}"; do
      case "$line" in "$stage "*) reached=1 ;; esac
    done
    if [ "$reached" = 0 ]; then
      printf '  %-14s %s\n' "$stage" "not run"
    fi
  done
  echo "  total: $SECONDS s"
  exit "$status"
}
trap finish EXIT
trap 'exit 130' INT TERM

begin_stage environment

for tool in docker python3 uv node npm curl; do
  command -v "$tool" > /dev/null 2>&1 || fail_run "this run needs $tool on PATH"
done
python3 -c 'import yaml' 2> /dev/null || fail_run "python3 has no PyYAML (python3 -m pip install pyyaml)"
compose_version=$(docker compose version --short 2> /dev/null || true)
python3 -c '
import re, sys
numbers = [int(part) for part in re.findall(r"\d+", sys.argv[1])[:3]]
sys.exit(0 if numbers >= [2, 24, 4] else 1)' "$compose_version" \
  || fail_run "Docker Compose ${compose_version:-is missing}: 2.24.4 or later is needed (the development compose file uses !override)"
node -e 'const [major, minor] = process.versions.node.split(".").map(Number); process.exit(major > 24 || (major === 24 && minor >= 15) ? 0 : 1)' \
  || fail_run "Node $(node --version) is too old: the browser suite needs 24.15 or later"

# Nothing from the shell may pick other compose files, another project or other profiles.
unset COMPOSE_FILE COMPOSE_PROJECT_NAME COMPOSE_PATH_SEPARATOR COMPOSE_ENV_FILES COMPOSE_PROFILES
python3 "$repository/scripts/envtool.py" --dev --env-file "$work/e2e.env" > /dev/null

# The run's settings: the local development names, plugins on, and the raised login and refresh
# rates the browser suite needs. The shell's values win.
export PLUGINS_ENABLED=${PLUGINS_ENABLED:-true}
export NGINX_SERVER_NAME=${NGINX_SERVER_NAME:-epicstaff.localhost}
export NGINX_SSL_MODE=${NGINX_SSL_MODE:-off}
export DJANGO_FRONTEND_BASE_URL=${DJANGO_FRONTEND_BASE_URL:-http://epicstaff.localhost}
export PLUGINS_BASE_DOMAIN=${PLUGINS_BASE_DOMAIN:-plugins.epicstaff.localhost}
export DJANGO_REFRESH_COOKIE_SECURE=${DJANGO_REFRESH_COOKIE_SECURE:-false}
export PLUGINS_DEV_API_PORT=${PLUGINS_DEV_API_PORT:-8082}
export DJANGO_LOGIN_THROTTLE_RATE=${DJANGO_LOGIN_THROTTLE_RATE:-100/min}
export DJANGO_LOGIN_IP_THROTTLE_RATE=${DJANGO_LOGIN_IP_THROTTLE_RATE:-300/min}
export DJANGO_TOKEN_REFRESH_THROTTLE_RATE=${DJANGO_TOKEN_REFRESH_THROTTLE_RATE:-600/min}
export PLUGINS_MAX_PACKAGE_MB=${PLUGINS_MAX_PACKAGE_MB:-300}
# Set by the run whatever the shell holds: images under the run's own tag (never :latest), only
# the plugins profile, a plugins subnet apart from a developer's stack and the labs, and
# development mode off until the development leg, which adds the development compose file that
# mode needs (nginx and django_app refuse it without that file).
export IMAGE_TAG="e2e-$run_id" COMPOSE_PROFILES=plugins PLUGINS_NETWORK_SUBNET=10.235.252.0/24 \
  PLUGINS_DEV_MODE=false
# Random for every run, and never printed.
for name in PLUGINS_GATEWAY_SECRET PLUGINS_NODE_KEY PLUGINS_DB_SUPERUSER_PASSWORD \
  PLUGINS_DB_ADMIN_PASSWORD PLUGINS_DB_BACKUP_PASSWORD; do
  value=$(random_secret)
  remember_secret "$value"
  export "$name=$value"
done
export E2E_SUPERADMIN_EMAIL=e2e-superadmin@example.com
E2E_SUPERADMIN_PASSWORD="$(random_secret | cut -c1-32)Aa"
remember_secret "$E2E_SUPERADMIN_PASSWORD"
export E2E_SUPERADMIN_PASSWORD
epicstaff_url=${DJANGO_FRONTEND_BASE_URL%/}
plugin_url="${epicstaff_url%%://*}://$plugin.$PLUGINS_BASE_DOMAIN"

# The run's signing key, the only one the stack trusts.
(cd "$repository" && uv run --frozen --project src/plugin_sdk epicstaff-plugin keygen --out "$work/e2e-signing") \
  > "$work/keygen.out"
PLUGINS_TRUSTED_SIGNING_KEYS=$(sed -n 's/^PLUGINS_TRUSTED_SIGNING_KEYS entry: //p' "$work/keygen.out")
[ -n "$PLUGINS_TRUSTED_SIGNING_KEYS" ] || fail_run "epicstaff-plugin keygen printed no trusted key entry"
export PLUGINS_TRUSTED_SIGNING_KEYS

# The run's project must be new: its teardown runs `down -v`, which would remove the volumes of a
# project that is not this run's (E2E_PROJECT=src: a developer's src_* volumes), and a killed
# run's leftovers would break this one. Nothing is removed here.
project_filter="label=com.docker.compose.project=$project"
project_leftovers=$(
  docker ps -a --filter "$project_filter" --format 'container {{.Names}}'
  docker volume ls --filter "$project_filter" --format 'volume {{.Name}}'
  docker network ls --filter "$project_filter" --format 'network {{.Name}}'
)
if [ -n "$project_leftovers" ]; then
  echo "Compose project $project already has:" >&2
  while read -r leftover; do
    echo "  $leftover" >&2
  done <<< "$project_leftovers"
  echo "Run with another E2E_PROJECT. If these are left over from an earlier run of this script, remove them first with" >&2
  echo "  docker compose -p $(printf '%q' "$project") down -v" >&2
  echo "which deletes the project's volumes and their data. This script never removes them." >&2
  fail_run "Compose project $project is not new"
fi

# src/docker-compose.yaml fixes container names, so a second stack cannot start next to one that
# exists, running or stopped. This script never stops or removes another stack.
compose --profile '*' config --format json | python3 -c '
import json, sys
for service in json.load(sys.stdin)["services"].values():
    if service.get("container_name"):
        print(service["container_name"])' > "$work/container-names"
existing=$(docker ps -a --format '{{.Names}}' | grep -Fx -f "$work/container-names" || true)
if [ -n "$existing" ]; then
  echo "These containers have the names this stack needs:" >&2
  for container in $existing; do
    echo "  $container (Compose project: $(docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' "$container" 2> /dev/null || echo unknown))" >&2
  done
  fail_run "another EpicStaff stack exists on this machine. Bring it down first, for example docker compose -p <its project> down (its named volumes stay); this script never stops or removes it"
fi
if docker network ls -q | xargs docker network inspect -f '{{range .IPAM.Config}}{{.Subnet}} {{end}}' 2> /dev/null \
  | tr ' ' '\n' | grep -qx "$PLUGINS_NETWORK_SUBNET"; then
  fail_run "a Docker network already uses $PLUGINS_NETWORK_SUBNET, this run's plugins subnet"
fi
for port in 80 443 "$PLUGINS_DEV_API_PORT"; do
  if python3 -c 'import socket, sys; socket.create_connection(("127.0.0.1", int(sys.argv[1])), 2).close()' "$port" 2> /dev/null; then
    fail_run "something already listens on 127.0.0.1:$port, which this stack publishes"
  fi
done
echo "Compose project $project, image tag $IMAGE_TAG, plugins subnet $PLUGINS_NETWORK_SUBNET"

begin_stage names
epicstaff_host=${epicstaff_url#*://}
epicstaff_host=${epicstaff_host%%[:/]*}
for host_name in "$epicstaff_host" "$plugin.$PLUGINS_BASE_DOMAIN"; do
  address=$(python3 -c 'import socket, sys; print(socket.gethostbyname(sys.argv[1]))' "$host_name" 2> /dev/null || true)
  if [ "$address" != 127.0.0.1 ]; then
    echo "$host_name resolves to ${address:-nothing}, not 127.0.0.1. Add this line to /etc/hosts:" >&2
    echo "  127.0.0.1 $epicstaff_host $plugin.$PLUGINS_BASE_DOMAIN" >&2
    echo "for example: echo '127.0.0.1 $epicstaff_host $plugin.$PLUGINS_BASE_DOMAIN' | sudo tee -a /etc/hosts" >&2
    fail_run "$host_name does not resolve to this machine"
  fi
  echo "$host_name resolves to 127.0.0.1"
done

begin_stage stack
# The services this run needs, and nothing more:
stack_services=(
  crewdb         # EpicStaff's database
  redis          # django_app's cache, throttles and message streams
  storage        # object storage: uploaded packages and EpicStaff's files
  storage-init   # creates EpicStaff's bucket
  django_app     # the API, the plugin registry, the gateway and page decisions
  frontend       # EpicStaff's pages, where the browser suite opens the plugin
  plugins_db     # Weather's database
  plugins_egress # Weather's way out to its forecast provider
  es_plugins     # the plugin node, which runs Weather's backend
)
stack_started=1
echo "building ${built_services[*]} (log: compose build)"
if ! compose build "${built_services[@]}" > "$work/build.log" 2>&1; then
  tail -n 60 "$work/build.log" | redact_stream
  fail_run "the images did not build"
fi
compose up -d --no-build "${stack_services[@]}"
wait_healthy django_app 900
# epicstaff-nginx last, without its other dependency (realtime, which nothing here uses).
compose up -d --no-build --no-deps epicstaff-nginx
wait_for 120 curl -sf -o /dev/null "$epicstaff_url/" || fail_run "EpicStaff does not answer at $epicstaff_url"
wait_healthy plugins_db 300
wait_healthy plugins_egress 300
wait_healthy es_plugins 300

begin_stage package
npm --prefix "$repository/plugin-sdk" ci --ignore-scripts
npm --prefix "$repository/plugin-sdk" run build
npm --prefix "$sample/spa" ci --ignore-scripts
npm --prefix "$sample/spa" run build
(cd "$repository" && uv build --project src/plugin_sdk --wheel -o "$work/dist")
sdk_wheel=$(ls "$work"/dist/epicstaff_plugin-*.whl)
case "$(docker info --format '{{.Architecture}}')" in
  x86_64 | amd64) architecture=x86_64 ;;
  aarch64 | arm64) architecture=aarch64 ;;
  *) fail_run "the Docker host's architecture $(docker info --format '{{.Architecture}}') has no plugin wheels" ;;
esac
(cd "$repository" && uv run --frozen --project src/plugin_sdk epicstaff-plugin pack "$sample" \
  --spa-dir "$sample/spa/dist" --download-wheels --platform "manylinux_2_28_$architecture" \
  --local-wheel "$sdk_wheel" --key "$work/e2e-signing.key" --out "$work/$plugin.esplugin")

begin_stage browsers
npm --prefix "$browser_suite" ci --ignore-scripts
install_options=()
if env_bool CI false; then
  install_options=(--with-deps)
fi
(cd "$browser_suite" && npx playwright install ${install_options[@]+"${install_options[@]}"} chromium firefox webkit)
export E2E_EPICSTAFF_URL=$epicstaff_url E2E_PLUGIN=$plugin E2E_PLUGIN_URL=$plugin_url \
  E2E_PACKAGE="$work/$plugin.esplugin" E2E_STACK_FILE="$work/stack.json"
npm --prefix "$browser_suite" run e2e:seed
for person in ada olga vic bob; do
  remember_secret "$(stack_value "people.$person.password")"
done
npm --prefix "$browser_suite" run e2e

begin_stage smokes
for smoke in "${STACK_SMOKES[@]}"; do
  echo "### $smoke"
  "smoke_$smoke"
done

begin_stage development
export PLUGINS_DEV_MODE=true
compose_files+=(-f "$repository/src/docker-compose.plugins-dev.yaml")
compose up -d --no-build --no-deps --force-recreate django_app epicstaff-nginx
wait_healthy django_app 600
wait_for 120 curl -sf -o /dev/null "$epicstaff_url/" || fail_run "EpicStaff does not answer at $epicstaff_url in development mode"
smoke_development

begin_stage final-smokes
for smoke in "${FINAL_SMOKES[@]}"; do
  echo "### $smoke"
  "smoke_$smoke"
done
