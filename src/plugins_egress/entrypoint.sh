#!/bin/sh
# Ranges and setpriv options are split into words on purpose (set -f below).
# shellcheck disable=SC2086
# plugins_egress start-up, as root with NET_ADMIN, SETPCAP, CHOWN, SETUID and SETGID. It refuses
# to run with IPv6 on, installs and verifies a firewall that keeps every connection this container
# opens off private destinations, waits for the plugin node's policy files, and then runs Squid in
# the foreground with only SETUID and SETGID left in any capability set: neither Squid nor a
# helper can change the firewall.
set -eu
# The ranges are expanded unquoted on purpose (one argument each); never as file name patterns.
set -f

RANGES=/etc/squid/private_ranges.txt
POLICY=/etc/squid/policy
CHAIN=EGRESS_PRIVATE

log() { echo "plugins_egress: $*" >&2; }

# The container's sysctls turn IPv6 off; on a kernel without IPv6 the switch does not exist.
ipv6_switch=/proc/sys/net/ipv6/conf/all/disable_ipv6
if [ -e "$ipv6_switch" ] && [ "$(cat "$ipv6_switch")" != 1 ]; then
  log "IPv6 is on in this container; it needs the sysctl net.ipv6.conf.all.disable_ipv6=1"
  exit 1
fi

# Squid starts with everything but SETUID and SETGID, which it needs to switch from root to its
# own user, out of the bounding set, so no process it starts can get the rest back. setpriv
# reports success even when it cannot shrink the bounding set (it needs SETPCAP for that), so the
# same settings are tried first, before anything else, on a process that only reads its own
# capability sets.
SQUID_PRIVILEGES="--inh-caps=-all --ambient-caps=-all --bounding-set=-all,+setuid,+setgid"
SETUID_AND_SETGID=0xc0
capability_sets=$(setpriv $SQUID_PRIVILEGES sed -n 's/^Cap[A-Za-z]*:[[:space:]]*/0x/p' /proc/self/status)
checked=0
for capability_set in $capability_sets; do
  checked=$((checked + 1))
  if [ $((capability_set & ~SETUID_AND_SETGID)) -ne 0 ]; then
    log "Squid would start with more than SETUID and SETGID ($capability_set); refusing to start"
    exit 1
  fi
done
# Inheritable, permitted, effective, bounding and ambient.
if [ "$checked" -ne 5 ]; then
  log "could not read the capability sets Squid would start with; refusing to start"
  exit 1
fi

# Squid checks the resolved address before it connects, but resolves the name again for the
# connection itself, so a DNS answer that changes in between could reach a private address. These
# rules refuse that connection in the kernel. DNS goes to any address: the resolver Docker or the
# host gives may be private, and Squid opens tunnels to port 443 only.
install_chain() { # iptables or ip6tables, then the ranges it refuses
  tables=$1
  shift
  if ! "$tables" -N "$CHAIN" 2> /dev/null; then
    "$tables" -F "$CHAIN"
  fi
  "$tables" -A "$CHAIN" -o lo -j ACCEPT
  "$tables" -A "$CHAIN" -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
  "$tables" -A "$CHAIN" -p udp --dport 53 -j ACCEPT
  "$tables" -A "$CHAIN" -p tcp --dport 53 -j ACCEPT
  for range in "$@"; do
    "$tables" -A "$CHAIN" -d "$range" -j REJECT
  done
  if ! "$tables" -C OUTPUT -j "$CHAIN" 2> /dev/null; then
    "$tables" -I OUTPUT 1 -j "$CHAIN"
  fi
}

verify_chain() { # iptables or ip6tables, then the ranges it must refuse
  tables=$1
  shift
  "$tables" -C OUTPUT -j "$CHAIN" || return 1
  rules=$("$tables" -S "$CHAIN")
  for range in "$@"; do
    case "$rules" in
      *"-A $CHAIN -d $range -j REJECT"*) ;;
      *)
        log "$tables has no rule refusing $range"
        return 1
        ;;
    esac
  done
}

ipv4_ranges=$(grep -v ':' "$RANGES")
ipv6_ranges=$(grep ':' "$RANGES")
install_chain iptables $ipv4_ranges
verify_chain iptables $ipv4_ranges || exit 1
if ip6tables -S > /dev/null 2>&1; then
  install_chain ip6tables $ipv6_ranges
  verify_chain ip6tables $ipv6_ranges || exit 1
else
  log "no ip6tables filter table: IPv6 is disabled, no IPv6 rules installed"
fi
log "egress firewall installed"

# Squid stops at once without its password file. The plugin node writes both files at its start.
waited=0
until [ -f "$POLICY/passwords" ] && [ -f "$POLICY/hosts.json" ]; do
  if [ $((waited % 30)) -eq 0 ]; then
    log "waiting for the plugin node's policy files in $POLICY"
  fi
  sleep 1
  waited=$((waited + 1))
done

# Squid writes its PID file as root, so the directory stays root's; it writes nothing else.
mkdir -p /run/squid
# Squid opens its logs as its own user, and this container's stdout and stderr are root's pipes.
chown squid /proc/self/fd/1 /proc/self/fd/2

# No -d: Squid's cache log is already stderr, and -d would print every line of it twice.
exec setpriv $SQUID_PRIVILEGES squid -N -f /etc/squid/squid.conf
