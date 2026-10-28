#!/usr/bin/env bash
# Gateway overhead under load, in the tools container. wrk keeps its client connections open;
# a 2 s warm-up is discarded before each measured run.
set -u
# wrk refuses a host name with an underscore, so the baseline uses plugin-bravo (same server).
duration=${DURATION:-10s}

measure() { # label, connections, threads, url, [wrk args...]
  local label=$1 connections=$2 threads=$3 url=$4
  shift 4
  wrk -t "$threads" -c "$connections" -d 2s "$@" "$url" > /dev/null 2>&1
  printf '%-44s c=%-2s ' "$label" "$connections"
  wrk -t "$threads" -c "$connections" -d "$duration" -s /lab/scripts/wrk_report.lua "$@" "$url" \
    | grep -E '^(requests|p50)' | tr '\n' ' '
  echo
}

# `bench.sh direct` runs in the inside container (the backends are on the plugins network only),
# `bench.sh gateway` in the tools container (the gateway refuses the plugins network).
for connections in 1 8; do
  threads=$((connections > 1 ? 2 : 1))
  case "${1:?usage: bench.sh direct|gateway}" in
    direct)
      measure "direct to a plugin backend" "$connections" "$threads" http://plugin-bravo:20002/api/public/bench
      ;;
    gateway)
      measure "gateway, check answers at once" "$connections" "$threads" http://nginx/api/public/bench \
        -H 'Host: alpha.plugins.epicstaff.test'
      measure "gateway, check takes 2 ms" "$connections" "$threads" http://nginx/api/public/bench \
        -H 'Host: slow.plugins.epicstaff.test'
      ;;
  esac
done
