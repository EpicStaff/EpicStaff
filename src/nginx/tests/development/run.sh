#!/usr/bin/env bash
# The plugin development lab: EpicStaff's nginx templates rendered with PLUGINS_DEV_MODE on and off
# under the nginx image pinned in src/docker-compose.yaml, against a stand-in django_app (both
# checks, controlled per test), a stand-in frontend development server and a plugin backend.
# Checks, one `ok -` / `not ok -` line each:
#   - page routing: the page decision's 204 serves the published files, its 403 with an upstream
#     the development server (path and query kept, server-sent events unbuffered, a WebSocket
#     upgraded), which, like esbuild's, refuses any Host but localhost and 127.0.0.1;
#   - headers: the development server's cookie, framing rule and policy are hidden and the
#     platform's headers added; it is asked for localhost and its port, with the plugin's host in
#     X-Forwarded-Host; a browser's cookie, login, API key and plugin context never reach it;
#   - failures: no upstream, nothing listening, a failed or missing decision all give 503;
#   - the paths development mode leaves alone, and the maintenance page before the decision;
#   - the development API listener: its network secret and development header, never a caller's,
#     its 404s, and its refusal of the plugins network;
#   - with the mode off: no page request asks the decision, and nothing listens on 8082;
#   - with the mode on but without src/docker-compose.plugins-dev.yaml's marker
#     (PLUGINS_DEV_LOOPBACK_ONLY): nginx refuses to start, exit 64.
# Every run has a Compose project of its own and removes every container, volume, network and
# image it made. Needs Docker. Usage, from anywhere: bash src/nginx/tests/development/run.sh
set -euo pipefail
cd "$(dirname "$0")"

compose_file=../../../docker-compose.yaml
DEVELOPMENT_LAB_NGINX_IMAGE=$(awk '/^  epicstaff-nginx:$/ { in_service = 1; next }
                                   in_service && /^    image:/ { print $2; exit }' "$compose_file")
if [ -z "$DEVELOPMENT_LAB_NGINX_IMAGE" ]; then
  echo "ERROR: no image found for the epicstaff-nginx service in $compose_file" >&2
  exit 2
fi
export DEVELOPMENT_LAB_NGINX_IMAGE

project="es-development-lab-$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n')"
compose() { docker compose -p "$project" "$@"; }
cleanup() { compose down -v --rmi local > /dev/null 2>&1 || true; }
trap cleanup EXIT

if ! compose up -d --build --quiet-pull > "${TMPDIR:-/tmp}/$project-up.log" 2>&1; then
  cat "${TMPDIR:-/tmp}/$project-up.log"
  compose logs
  rm -f "${TMPDIR:-/tmp}/$project-up.log"
  exit 1
fi
rm -f "${TMPDIR:-/tmp}/$project-up.log"
# The published SPA, readable by nginx's worker user as django_app writes it (0755 and 0644).
compose exec -T tools sh -c 'cp -R /lab/spa/. /srv/plugin-spa/ && chmod -R u=rwX,go=rX /srv/plugin-spa' \
  || { compose logs; exit 1; }
for server in nginx nginx-off; do
  ready=0
  for _ in $(seq 60); do
    if compose exec -T tools curl -s -o /dev/null -H 'Host: epicstaff.localhost' "http://$server/"; then
      ready=1
      break
    fi
    sleep 1
  done
  if [ "$ready" != 1 ]; then
    echo "not ok - $server did not start"
    compose logs "$server"
    exit 1
  fi
done

status=0
compose exec -T tools bash /lab/scripts/checks.sh outside || status=$?
compose exec -T inside bash /lab/scripts/checks.sh inside || status=$?
compose exec -T tools bash /lab/scripts/checks.sh off || status=$?

echo "# inside each nginx container, where the stack's healthcheck runs"
for server in nginx nginx-off; do
  code=$(compose exec -T "$server" curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8081/nginx-health || true)
  if [ "$code" = 204 ]; then
    echo "ok - $server: /nginx-health on 127.0.0.1:8081 answers 204, next to the internal API listener on the same port"
  else
    echo "not ok - $server: /nginx-health on 127.0.0.1:8081 answered $code"
    status=1
  fi
done

echo "# development mode without the development compose file"
refusal_status=0
refusal=$(compose run --rm --no-deps -T nginx-unmarked nginx -t 2>&1) || refusal_status=$?
if [ "$refusal_status" = 64 ] \
  && grep -qF 'Start EpicStaff with -f src/docker-compose.plugins-dev.yaml' <<< "$refusal"; then
  echo "ok - nginx with PLUGINS_DEV_MODE=true and no PLUGINS_DEV_LOOPBACK_ONLY refuses to start (64), naming the development compose file"
else
  echo "not ok - nginx with PLUGINS_DEV_MODE=true and no PLUGINS_DEV_LOOPBACK_ONLY: exit $refusal_status, $(tail -n 3 <<< "$refusal" | tr '\n' ' ')"
  status=1
fi

if [ "$status" -ne 0 ]; then
  echo "FAILED: see the not ok lines above"
  exit 1
fi
echo "All development lab checks passed."
