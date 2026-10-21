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


def log_signing_key_rotation(new_kid: str, retired_kids: list[str]) -> None:
    logger.info(
        "PluginSigningKeyService.rotate kid={kid} retired={retired}",
        kid=new_kid,
        retired=",".join(retired_kids) or "none",
    )
