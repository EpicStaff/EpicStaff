#!/bin/sh
# The options are split into words on purpose.
# shellcheck disable=SC2086
# es_plugins start-up, as root with NET_ADMIN, BPF, SETPCAP, SETUID, SETGID and CHOWN. It installs
# the per-plugin connection caps and the bind refusal (es_plugins.network_limits), then runs the
# launcher as PID 1 with only SETUID, SETGID and CHOWN left in any capability set: neither the
# launcher, the agent nor a plugin can change them.
set -eu

log() { echo "es_plugins: $*" >&2; }

# setpriv reports success even when it cannot shrink the bounding set (that needs SETPCAP), so the
# same options are tried first on a process that only reads its own capability sets.
LAUNCHER_PRIVILEGES="--inh-caps=-all --ambient-caps=-all --bounding-set=-all,+setuid,+setgid,+chown"
SETUID_SETGID_AND_CHOWN=0xc1
capability_sets=$(setpriv $LAUNCHER_PRIVILEGES sed -n 's/^Cap[A-Za-z]*:[[:space:]]*/0x/p' /proc/self/status)
checked=0
for capability_set in $capability_sets; do
  checked=$((checked + 1))
  if [ $((capability_set & ~SETUID_SETGID_AND_CHOWN)) -ne 0 ]; then
    log "the launcher would start with more than SETUID, SETGID and CHOWN ($capability_set); refusing to start"
    exit 1
  fi
done
# Inheritable, permitted, effective, bounding and ambient.
if [ "$checked" -ne 5 ]; then
  log "could not read the capability sets the launcher would start with; refusing to start"
  exit 1
fi

python -m es_plugins.network_limits

exec setpriv $LAUNCHER_PRIVILEGES python -m es_plugins.launcher
