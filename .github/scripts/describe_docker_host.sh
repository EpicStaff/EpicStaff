#!/usr/bin/env bash
# Prints what the plugin labs and the plugin platform stack depend on in the Docker host, so a
# failure on a new runner can be read from the log: the kernel, the cgroup hierarchy and driver
# (the node's bind refusal attaches a cgroup v2 BPF program), Docker's and Compose's versions and
# security options, AppArmor and the kernel lockdown, and whether nftables' connection-count
# match can load. Diagnostics only: it always exits 0, and prints "unknown" for what it cannot
# read. Usage: bash .github/scripts/describe_docker_host.sh
set -u

show() { # label, then a command whose output is the value
  local label=$1 value
  shift
  value=$("$@" 2> /dev/null | tr '\n' ' ' | sed 's/ *$//') || true
  printf '%-34s %s\n' "$label" "${value:-unknown}"
}

show "kernel" uname -srm
show "cgroup file system" stat -fc %T /sys/fs/cgroup
show "docker server" docker version --format '{{.Server.Version}} (API {{.Server.APIVersion}})'
# The kernel containers run on: the host's own on Linux, a virtual machine's with Docker Desktop.
show "docker kernel and system" docker info --format '{{.KernelVersion}}, {{.OperatingSystem}}'
show "docker cgroup version and driver" docker info --format '{{.CgroupVersion}} {{.CgroupDriver}}'
show "docker security options" docker info --format '{{join .SecurityOptions " | "}}'
show "docker compose" docker compose version --short
show "linux security modules" cat /sys/kernel/security/lsm
show "apparmor enabled" cat /sys/module/apparmor/parameters/enabled
show "kernel lockdown" cat /sys/kernel/security/lockdown
show "unprivileged_bpf_disabled" cat /proc/sys/kernel/unprivileged_bpf_disabled
show "nft_connlimit module" sh -c 'grep -w nft_connlimit /proc/modules || modinfo -F filename nft_connlimit'
exit 0
