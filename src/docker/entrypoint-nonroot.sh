#!/bin/sh
# Drop privileges to an unprivileged user before exec'ing the service.
#
# Why this exists instead of a plain `USER app` line: Docker only seeds a named
# volume's ownership from the image directory when the volume is *new*. A volume
# that already exists — every live deployment — keeps its original root:root
# ownership, so a straight switch to `USER app` leaves the service unable to
# write to its own data and it fails on upgrade. This runs as root just long
# enough to correct ownership on the mounted paths, then permanently drops.
#
# APP_UID/APP_GID default to 1000 (the uid baked into the images), but can end
# up overridden below by NONROOT_ADAPT_PATHS before the final drop.
set -e

APP_UID="${APP_UID:-1000}"
APP_GID="${APP_GID:-1000}"

if [ "$(id -u)" = "0" ]; then
    # NONROOT_ADAPT_PATHS lists host bind mounts (the operator's own
    # directories — e.g. CREW_SAVEFILES_PATH). `chown -R` must never run on
    # these unconditionally: that would silently rewrite a real person's own
    # files to a container-chosen uid. Instead, for each path:
    #   - missing, or owned by root -> nothing of the operator's to preserve.
    #     Docker itself auto-creates a missing bind-mount source as root:root,
    #     and a pre-hardening image wrote here as root too — so root ownership
    #     never means "a real person's own uid" in practice. Safe to take over,
    #     same as any other container-managed path below.
    #   - owned by anyone else -> that uid IS the real owner. Never touch their
    #     files; instead adopt THEIR uid/gid as this container's own runtime
    #     identity, so any new files it creates come out matching.
    # This runs before NONROOT_CHOWN_PATHS so that container-owned volumes are
    # chowned to the final (possibly adopted) identity, not the baked default.
    # shellcheck disable=SC2086 # word splitting is intended: this is a list
    for d in $(eval echo ${NONROOT_ADAPT_PATHS}); do
        [ -n "$d" ] || continue
        if [ ! -e "$d" ]; then
            mkdir -p "$d"
            chown -R "${APP_UID}:${APP_GID}" "$d"
            echo "entrypoint-nonroot: created $d, owned by ${APP_UID}:${APP_GID}" >&2
            continue
        fi
        owner_uid=$(stat -c %u "$d")
        owner_gid=$(stat -c %g "$d")
        if [ "$owner_uid" = "0" ]; then
            echo "entrypoint-nonroot: $d is root-owned (bootstrap or pre-hardening artifact) -> taking ownership" >&2
            chown -R "${APP_UID}:${APP_GID}" "$d"
        elif [ "$owner_uid" != "$APP_UID" ] || [ "$owner_gid" != "$APP_GID" ]; then
            if [ -n "${ADOPTED_FROM:-}" ] && [ "${owner_uid}:${owner_gid}" != "$ADOPTED_FROM" ]; then
                echo "entrypoint-nonroot: ERROR $d is owned by ${owner_uid}:${owner_gid}, which conflicts with ${ADOPTED_FROM} already adopted from ${ADOPTED_FROM_PATH}." >&2
                echo "  A single container can only run as one uid — align the ownership of these paths on the host." >&2
                exit 1
            fi
            echo "entrypoint-nonroot: $d is owned by ${owner_uid}:${owner_gid} -> adopting that as the runtime identity (no chown)" >&2
            APP_UID="$owner_uid"
            APP_GID="$owner_gid"
            ADOPTED_FROM="${owner_uid}:${owner_gid}"
            ADOPTED_FROM_PATH="$d"
        fi
    done

    # NONROOT_CHOWN_PATHS lists container-owned paths only — named volumes and
    # tmpfs mounts nothing outside the container controls. Chowned unconditionally
    # relative to the (possibly adopted) identity above.
    # shellcheck disable=SC2086 # word splitting is intended: this is a list
    for d in $(eval echo ${NONROOT_CHOWN_PATHS}); do
        [ -n "$d" ] || continue
        [ -e "$d" ] || mkdir -p "$d"
        if [ "$(stat -c %u "$d")" != "$APP_UID" ]; then
            echo "entrypoint-nonroot: taking ownership of $d" >&2
            chown -R "${APP_UID}:${APP_GID}" "$d"
        fi
    done

    # --clear-groups, not --init-groups: the latter looks APP_UID up in
    # /etc/passwd and only uid 1000 exists there, so any other value (the
    # default override, or an adopted host uid) would die with "failed to get
    # user info".
    # --bounding-set=-all leaves the app unable to regain capabilities even via
    # a setuid-root binary. It needs CAP_SETPCAP and silently does nothing
    # without it, so the compose cap_add lists must keep SETPCAP.
    exec setpriv --reuid="$APP_UID" --regid="$APP_GID" \
                 --clear-groups --bounding-set=-all "$@"
fi

# Already unprivileged (e.g. compose pinned `user:`) — nothing to drop.
exec "$@"
