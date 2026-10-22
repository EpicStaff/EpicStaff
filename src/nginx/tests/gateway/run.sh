#!/usr/bin/env bash
# The plugin gateway lab: EpicStaff's nginx templates under the pinned nginx image, against a
# stand-in decision service and two plugin backends. Prints one `ok -` / `not ok -` line per
# check, then the gateway's latency under load, and removes every container, volume, network and
# image it made. Needs Docker. Usage, from anywhere: bash src/nginx/tests/gateway/run.sh
#   DURATION=5s bash .../run.sh    shorter load runs (default 10s)
set -euo pipefail
cd "$(dirname "$0")"
compose() { docker compose -p es-gateway-lab "$@"; }
cleanup() { compose down -v --rmi local > /dev/null 2>&1 || true; }
trap cleanup EXIT
cleanup

compose up -d --build --quiet-pull > /dev/null 2>&1 || { compose logs; exit 1; }
# The published SPAs, readable by nginx's worker user as django_app writes them (0755 and 0644).
compose exec -T tools sh -c 'cp -R /lab/spa/. /srv/plugin-spa/ && chmod -R u=rwX,go=rX /srv/plugin-spa' \
  || { compose logs; exit 1; }
for _ in $(seq 60); do
  if compose exec -T tools curl -s -o /dev/null -H 'Host: alpha.plugins.epicstaff.test' http://nginx/; then
    break
  fi
  sleep 1
done

status=0
compose exec -T tools bash /lab/scripts/checks.sh outside || status=$?
compose exec -T inside bash /lab/scripts/checks.sh inside || status=$?

echo "# from the host, through the published port"
port=$(compose port nginx 80 | sed 's/.*://')
code=$(curl -s -o /dev/null -w '%{http_code}' -H 'Host: alpha.plugins.epicstaff.test' "http://127.0.0.1:$port/api/ping")
if [ "$code" = 200 ]; then
  echo "ok - nginx on plugins-network (internal) still answers on its published port"
else
  echo "not ok - the published port answered $code"
  status=1
fi
for path in /_plugin_gateway_check /_epicstaff/health; do
  code=$(curl -s --path-as-is -o /dev/null -w '%{http_code}' -H 'Host: alpha.plugins.epicstaff.test' "http://127.0.0.1:$port$path")
  if [ "$code" = 404 ]; then
    echo "ok - $path is 404 from the host"
  else
    echo "not ok - $path from the host: $code"
    status=1
  fi
done
if compose port nginx 8081 > /dev/null 2>&1; then
  echo "not ok - the internal API listener (8081) is published"
  status=1
else
  echo "ok - the internal API listener (8081) is not published"
fi

echo "# load (wrk; 0 errors and 0 non-2xx expected)"
{
  compose exec -T -e DURATION="${DURATION:-10s}" inside bash /lab/scripts/bench.sh direct
  compose exec -T -e DURATION="${DURATION:-10s}" tools bash /lab/scripts/bench.sh gateway
} | tee /dev/stderr \
  | grep -E 'errors connect=0 read=0 write=0 timeout=0 non2xx=0' -c | {
    read -r clean
    if [ "$clean" = 6 ]; then
      echo "ok - no errors and no non-2xx under load"
    else
      echo "not ok - $((6 - clean)) load run(s) had errors or non-2xx answers"
      exit 1
    fi
  } || status=1
exit "$status"
