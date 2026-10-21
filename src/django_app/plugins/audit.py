"""Actor log lines for plugin decisions, in the form the rbac governance services write theirs.

Every line names the acting user by e-mail and id. `utils.logger` keeps only the first 200
characters of a message, so a package's SHA-256 (64 hex digits) goes on a second line of its
own, tied to the first by the package id. Nothing secret and no file content is ever logged.
"""

from dataclasses import dataclass

from utils.logger import logger

from plugins.models import PluginGrant, PluginPackage


def actor_label(actor) -> str:
    return f"{getattr(actor, 'email', 'system')} (id {getattr(actor, 'pk', None)})"


@dataclass(frozen=True)
class PackageFacts:
    """What the log says about a package, taken while its row still exists."""

    package_id: int
    identifier: str
    version: str
    sha256: str

    @classmethod
    def of(cls, package: PluginPackage) -> "PackageFacts":
        return cls(
            package_id=package.pk,
            identifier=package.plugin.identifier,
            version=package.version,
            sha256=package.sha256,
        )


def log_package_action(action: str, actor, package: PackageFacts, **details: object) -> None:
    """Log one decision on a package: who, which package, the `details`, then its SHA-256."""
    logger.info(
        "PluginInstallationService.{action} actor={actor} package={package_id} plugin={identifier} "
        "version={version}{details}",
        action=action,
        actor=actor_label(actor),
        package_id=package.package_id,
        identifier=package.identifier,
        version=package.version,
        details="".join(f" {name}={value}" for name, value in details.items()),
    )
    logger.info(
        "PluginInstallationService.{action} package={package_id} sha256={sha256}",
        action=action,
        package_id=package.package_id,
        sha256=package.sha256,
    )


def log_grant(actor, grant: PluginGrant) -> None:
    logger.info(
        "PluginGrantService.grant actor={actor} plugin={identifier} grant={grant_id} "
        "org={org_id} org_name={org_name!r}",
        actor=actor_label(actor),
        identifier=grant.plugin.identifier,
        grant_id=grant.pk,
        org_id=grant.org_id,
        org_name=grant.org.name,
    )


def log_grant_suspended(actor, grant: PluginGrant, previous_state: str) -> None:
    logger.info(
        "plugins.grant.suspended actor={actor} plugin={identifier} grant={grant_id} org={org_id} "
        "previous_state={previous_state} purge_after={purge_after} cause={cause}",
        actor=actor_label(actor),
        identifier=grant.plugin.identifier,
        grant_id=grant.pk,
        org_id=grant.org_id,
        previous_state=previous_state,
        purge_after=grant.purge_after.isoformat(),
        cause=grant.suspension_cause,
    )


def log_grant_resumed(actor, grant: PluginGrant) -> None:
    logger.info(
        "plugins.grant.resumed actor={actor} plugin={identifier} grant={grant_id} org={org_id} "
        "state={state}",
        actor=actor_label(actor),
        identifier=grant.plugin.identifier,
        grant_id=grant.pk,
        org_id=grant.org_id,
        state=grant.state,
    )


def log_suspended_sessions_stopped(
    *, identifier: str, grant_id: int, org_id: int, count: int, failed: int
) -> None:
    """Log how many running sessions a suspension stopped, and how many stops failed."""
    logger.info(
        "plugins.grant.sessions_stopped plugin={identifier} grant={grant_id} org={org_id} "
        "count={count} failed={failed}",
        identifier=identifier,
        grant_id=grant_id,
        org_id=org_id,
        count=count,
        failed=failed,
    )


def log_refused_sessions_stopped(*, org_id: int, count: int, failed: int) -> None:
    """Log the sessions the periodic enforcement stopped: ones that started while a
    suspension committed."""
    logger.info(
        "plugins.retention.sessions_stopped org={org_id} count={count} failed={failed}",
        org_id=org_id,
        count=count,
        failed=failed,
    )


def log_role_plugin_actions(
    actor, *, role_id: int, org_id: int, identifier: str, before: list[str], after: list[str]
) -> None:
    """Log one change of a custom role's actions on a plugin."""
    logger.info(
        "PluginRolePermissionService.replace actor={actor} role={role_id} org={org_id} "
        "plugin={identifier} actions={after} was={before}",
        actor=actor_label(actor),
        role_id=role_id,
        org_id=org_id,
        identifier=identifier,
        after=",".join(after) or "none",
        before=",".join(before) or "none",
    )


def log_setting_changes(actor, identifier: str, keys: list[str]) -> None:
    """Log which settings of a plugin changed; values, secret or not, are never logged."""
    logger.info(
        "PluginSettingsService.update actor={actor} plugin={identifier} keys={keys}",
        actor=actor_label(actor),
        identifier=identifier,
        keys=",".join(keys),
    )


def log_limit_overrides(actor, identifier: str, overrides: dict) -> None:
    logger.info(
        "PluginLimitsService.update actor={actor} plugin={identifier} overrides={overrides}",
        actor=actor_label(actor),
        identifier=identifier,
        overrides=",".join(f"{name}={value}" for name, value in sorted(overrides.items()))
        or "none",
    )


def log_restart(actor, identifier: str, restart_generation: int) -> None:
    logger.info(
        "PluginRuntimeService.restart actor={actor} plugin={identifier} "
        "restart_generation={restart_generation}",
        actor=actor_label(actor),
        identifier=identifier,
        restart_generation=restart_generation,
    )


def log_database_record_created(*, identifier: str, database: str, server: str) -> None:
    """Log that a plugin got the record of its own database; its app password never is."""
    logger.info(
        "plugins.database.record_created plugin={identifier} database={database} server={server}",
        identifier=identifier,
        database=database,
        server=server,
    )


def log_signing_key_rotation(new_kid: str, retired_kids: list[str]) -> None:
    logger.info(
        "PluginSigningKeyService.rotate kid={kid} retired={retired}",
        kid=new_kid,
        retired=",".join(retired_kids) or "none",
    )


# The login lines name people by id only and never carry a code, verifier, token, cookie or
# `state`: the code and the token are credentials, and `state` binds the browser's login.
def log_login_token_issued(*, user_id: int, org_id: int, identifier: str, jti: str) -> None:
    logger.info(
        "plugins.login.token_issued user_id={user_id} org_id={org_id} plugin={identifier} "
        "jti={jti}",
        user_id=user_id,
        org_id=org_id,
        identifier=identifier,
        jti=jti,
    )


def log_login_access_denied(*, user_id: int, identifier: str, reason: str) -> None:
    """Log a refused plugin login; `reason` is `not_eligible`, `org_not_eligible` or
    `no_eligible_org`."""
    logger.info(
        "plugins.login.access_denied user_id={user_id} plugin={identifier} reason={reason}",
        user_id=user_id,
        identifier=identifier,
        reason=reason,
    )


def log_origin_refused(*, origin: str, method: str, path: str) -> None:
    """Log a request from a plugin page that EpicStaff refused; values are quoted, as the
    browser's page controls the path and a non-browser client the origin and method too."""
    logger.info(
        "plugins.origin_refused origin={origin!r} method={method!r} path={path!r}",
        origin=origin,
        method=method,
        path=path,
    )


# The service-account and hook lines never carry a key, a key hash, a hook assertion, a hook
# body or a person's permissions.
def log_service_account_keys_minted(identifier: str, org_ids: list[int]) -> None:
    logger.info(
        "plugins.service_account.keys_minted plugin={identifier} org_ids={org_ids} count={count}",
        identifier=identifier,
        org_ids=",".join(str(org_id) for org_id in org_ids),
        count=len(org_ids),
    )


def log_service_account_refused(*, identifier: str | None, reason: str) -> None:
    """Log a refused service-account key; `identifier` is None when the key named no plugin.

    `reason` is `outside_internal_listener`, `unknown_key`, `revoked`, `superseded`,
    `grant_state`, `org_inactive` or `no_backend`.
    """
    logger.info(
        "plugins.service_account.refused plugin={identifier} reason={reason}",
        identifier=identifier or "-",
        reason=reason,
    )


def log_on_behalf_of_refused(*, identifier: str, org_id: int, user_id: int) -> None:
    logger.info(
        "plugins.on_behalf_of.refused plugin={identifier} org={org_id} user_id={user_id}",
        identifier=identifier,
        org_id=org_id,
        user_id=user_id,
    )


def log_hook_claimed(*, identifier: str, job_id: int, kind: str, org_id: int, attempt: int) -> None:
    logger.info(
        "plugins.hook.claimed plugin={identifier} job={job_id} kind={kind} org={org_id} "
        "attempt={attempt}",
        identifier=identifier,
        job_id=job_id,
        kind=kind,
        org_id=org_id,
        attempt=attempt,
    )


def log_hook_finished(
    *,
    identifier: str,
    job_id: int,
    kind: str,
    org_id: int,
    attempt: int,
    outcome: str,
    duration_ms: int | None,
) -> None:
    """Log a hook's outcome; `duration_ms` is None when the node never reported one."""
    logger.info(
        "plugins.hook.finished plugin={identifier} job={job_id} kind={kind} org={org_id} "
        "attempt={attempt} outcome={outcome} duration_ms={duration_ms}",
        identifier=identifier,
        job_id=job_id,
        kind=kind,
        org_id=org_id,
        attempt=attempt,
        outcome=outcome,
        duration_ms="-" if duration_ms is None else duration_ms,
    )


def log_hook_gave_up(*, identifier: str, job_id: int, org_id: int, attempts: int) -> None:
    """Log an organization removed hook that failed on every attempt of its retry window."""
    logger.warning(
        "plugins.hook.gave_up plugin={identifier} job={job_id} org={org_id} attempts={attempts}",
        identifier=identifier,
        job_id=job_id,
        org_id=org_id,
        attempts=attempts,
    )


def log_org_removed_hook_action(
    action: str, actor, *, identifier: str, job_id: int, org_id: int
) -> None:
    """Log a retry or skip of an organization removed hook; `actor` None is the platform."""
    logger.info(
        "plugins.hook.{action} actor={actor} plugin={identifier} job={job_id} org={org_id}",
        action=action,
        actor=_actor_or_platform(actor),
        identifier=identifier,
        job_id=job_id,
        org_id=org_id,
    )


def log_grant_purge_started(
    actor, *, identifier: str, grant_id: int, org_id: int, reason: str, previous_state: str
) -> None:
    """Log that deleting a grant's data began; `actor` None is the platform."""
    logger.info(
        "plugins.grant.purge_started actor={actor} plugin={identifier} grant={grant_id} "
        "org={org_id} reason={reason} previous_state={previous_state}",
        actor=_actor_or_platform(actor),
        identifier=identifier,
        grant_id=grant_id,
        org_id=org_id,
        reason=reason,
        previous_state=previous_state,
    )


def log_grant_purged(*, identifier: str, grant_id: int, org_id: int) -> None:
    logger.info(
        "plugins.grant.purged plugin={identifier} grant={grant_id} org={org_id}",
        identifier=identifier,
        grant_id=grant_id,
        org_id=org_id,
    )


def log_plugin_uninstalled(actor, *, identifier: str, purge_after, grants: int) -> None:
    logger.info(
        "plugins.plugin.uninstalled actor={actor} plugin={identifier} purge_after={purge_after} "
        "grants={grants}",
        actor=actor_label(actor),
        identifier=identifier,
        purge_after=purge_after.isoformat(),
        grants=grants,
    )


def log_plugin_reinstalled(actor, *, identifier: str, grants_resumed: int) -> None:
    logger.info(
        "plugins.plugin.reinstalled actor={actor} plugin={identifier} grants_resumed={grants_resumed}",
        actor=actor_label(actor),
        identifier=identifier,
        grants_resumed=grants_resumed,
    )


def log_plugin_purge_started(actor, *, identifier: str, reason: str) -> None:
    """Log that deleting a plugin began; `actor` None is the platform."""
    logger.info(
        "plugins.plugin.purge_started actor={actor} plugin={identifier} reason={reason}",
        actor=_actor_or_platform(actor),
        identifier=identifier,
        reason=reason,
    )


def log_plugin_removal_requested(*, identifier: str, placement_id: int, node: str) -> None:
    logger.info(
        "plugins.plugin.removal_requested plugin={identifier} placement={placement_id} node={node}",
        identifier=identifier,
        placement_id=placement_id,
        node=node,
    )


def log_plugin_removal_failed(*, identifier: str, placement_id: int, error: str | None) -> None:
    logger.warning(
        "plugins.plugin.removal_failed plugin={identifier} placement={placement_id} error={error}",
        identifier=identifier,
        placement_id=placement_id,
        error=error,
    )


def log_plugin_purged(*, identifier: str, had_database: bool) -> None:
    logger.info(
        "plugins.plugin.purged plugin={identifier} had_database={had_database}",
        identifier=identifier,
        had_database=had_database,
    )


def log_organization_deleted(*, org_id: int, grants: int, data_removals: int) -> None:
    logger.info(
        "plugins.organization_deleted org={org_id} grants={grants} data_removals={data_removals}",
        org_id=org_id,
        grants=grants,
        data_removals=data_removals,
    )


def log_retention_tick(counts: dict[str, int]) -> None:
    """Log what one scheduled maintenance run did, naming only the counts above zero."""
    done = {name: count for name, count in counts.items() if count}
    if done:
        logger.info(
            "plugins.retention.tick {counts}",
            counts=" ".join(f"{name}={count}" for name, count in done.items()),
        )


def _actor_or_platform(actor) -> str:
    return actor_label(actor) if actor is not None else "platform"
