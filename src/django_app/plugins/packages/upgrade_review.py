"""What the SuperAdmin reviews before approving a new version of an installed plugin.

Computed when asked, never stored: the baseline it compares with is the latest approved
package (the open upgrade's target, else the current package), and that moves. Access growth
(`GROWTH_RULES`) is what the new version may do that the baseline may not; approving it needs
an explicit acknowledgement, bound to the baseline the review named. Everything else in
`UpgradeReview` is shown without one.

Adding a growth rule: a comparer in `GROWTH_RULES`, keyed by the `AccessGrowth` field it
fills, then the frontend's review section for it and its row in
`reference/compatibility-and-versioning.md`.
"""

from collections.abc import Callable
from dataclasses import dataclass, fields

from epicstaff_plugin.contracts.manifest import PluginManifest, PublicPath

from plugins.configuration.setting_values import NeededSetting, settings_needed
from plugins.lifecycle.open_upgrades import latest_approved_package, open_upgrade_of
from plugins.models import (
    GrantState,
    PluginDatabase,
    PluginGrant,
    PluginPackage,
    PluginUpgrade,
    ReviewState,
    Trust,
)
from plugins.packages.review import resource_label

HOOK_KINDS = ("install", "upgrade", "org_removed")
_PUBLIC_PATH_FIELDS = {"path", "match", "methods", "rate_limit_per_minute", "max_body_kb"}
LIMIT_NAMES = (
    "memory_mb",
    "db_connections",
    "statement_timeout_seconds",
    "requests_per_minute",
    "cpu_priority",
)


@dataclass(frozen=True)
class AccessGrowth:
    """What a new version may do that its baseline may not, by kind."""

    access: list[dict]
    outbound_hosts: list[dict]
    public_paths: list[dict]

    @property
    def requires_acknowledgement(self) -> bool:
        return any(getattr(self, field.name) for field in fields(self))


def _new_access(baseline: PluginManifest, new: PluginManifest) -> list[dict]:
    """The `(resource type, action)` pairs the baseline does not declare, one row per type."""
    declared = {
        (declaration.resource_type, action)
        for declaration in baseline.access
        for action in declaration.actions
    }
    rows = []
    for declaration in new.access:
        actions = [
            action
            for action in declaration.actions
            if (declaration.resource_type, action) not in declared
        ]
        if actions:
            rows.append(
                {
                    "resource_type": declaration.resource_type,
                    "resource_label": resource_label(declaration.resource_type),
                    "actions": actions,
                    "reason": declaration.reason,
                }
            )
    return rows


def _new_outbound_hosts(baseline: PluginManifest, new: PluginManifest) -> list[dict]:
    """Hosts the baseline does not list, as written: a new wildcard is new even when it covers
    a host the baseline lists."""
    listed = {outbound.host for outbound in baseline.outbound_hosts}
    return [
        {"host": outbound.host, "reason": outbound.reason}
        for outbound in new.outbound_hosts
        if outbound.host not in listed
    ]


def _covers(wider: PublicPath, narrower: PublicPath) -> bool:
    return (
        wider.path == narrower.path
        and wider.match == narrower.match
        and set(narrower.methods) <= set(wider.methods)
        and wider.rate_limit_per_minute >= narrower.rate_limit_per_minute
        and wider.max_body_kb >= narrower.max_body_kb
    )


def _wider_public_paths(baseline: PluginManifest, new: PluginManifest) -> list[dict]:
    """Public path rules no baseline rule covers: `new` for a path the baseline does not make
    public, `widened` for one it does with a narrower rule (`exact` to `prefix`, more
    methods, higher limits)."""
    baseline_paths = {rule.path for rule in baseline.public_paths}
    return [
        {
            **rule.model_dump(include=_PUBLIC_PATH_FIELDS),
            "change": "widened" if rule.path in baseline_paths else "new",
        }
        for rule in new.public_paths
        if not any(_covers(known, rule) for known in baseline.public_paths)
    ]


GROWTH_RULES: dict[str, Callable[[PluginManifest, PluginManifest], list[dict]]] = {
    "access": _new_access,
    "outbound_hosts": _new_outbound_hosts,
    "public_paths": _wider_public_paths,
}


def access_growth(baseline: PluginManifest, new: PluginManifest) -> AccessGrowth:
    """The growth of `new` over `baseline`, by every rule of `GROWTH_RULES`."""
    return AccessGrowth(**{name: rule(baseline, new) for name, rule in GROWTH_RULES.items()})


@dataclass(frozen=True)
class UpgradeReview:
    """The changes a new version brings that need no acknowledgement, and what the upgrade
    will do: whether the plugin goes offline, the backup, and who waits."""

    baseline_package_id: int
    from_version: str
    replaces_version: str | None
    trust_change: str
    maintenance: bool
    backend: str
    database: str
    migrations_added: list[str]
    hooks_added: list[str]
    hooks_removed: list[str]
    has_upgrade_hook: bool
    user_permissions: dict[str, list[str]]
    settings_added: list[str]
    settings_removed: list[str]
    settings_needed: list[NeededSetting]
    limits_changed: list[str]
    backup_required: bool
    database_size_bytes: int | None
    database_name: str | None
    organizations_going_offline: int
    cancellable: bool


@dataclass(frozen=True)
class PackageUpgradeReview:
    growth: AccessGrowth
    review: UpgradeReview


def review_upgrade(package: PluginPackage) -> PackageUpgradeReview | None:
    """The upgrade review of a pending package; None for a first install or a decided package.

    `package` comes with its plugin and the plugin's current package. A handful of queries:
    the open upgrade, the database record, the stored settings and the active grants.
    """
    plugin = package.plugin
    if package.review_state != ReviewState.PENDING or plugin.current_package_id is None:
        return None
    current = plugin.current_package
    upgrade = open_upgrade_of(plugin)
    baseline = latest_approved_package(plugin, upgrade)
    new = package.parsed_manifest
    baseline_manifest = baseline.parsed_manifest
    database = PluginDatabase.objects.filter(plugin=plugin).first()
    current_manifest = current.parsed_manifest
    maintenance = current_manifest.backend is not None
    hooks_before, hooks_after = _hooks(baseline_manifest), _hooks(new)
    review = UpgradeReview(
        baseline_package_id=baseline.pk,
        from_version=current.version,
        replaces_version=upgrade.to_version if upgrade is not None and upgrade.failed else None,
        trust_change=_trust_change(baseline, package),
        maintenance=maintenance,
        backend="added" if current_manifest.backend is None and new.backend else "unchanged",
        database=_database_change(current_manifest, new),
        migrations_added=_migrations_added(package, baseline, database),
        hooks_added=[kind for kind in HOOK_KINDS if hooks_after[kind] and not hooks_before[kind]],
        hooks_removed=[kind for kind in HOOK_KINDS if hooks_before[kind] and not hooks_after[kind]],
        has_upgrade_hook=new.backend is not None and new.hooks.upgrade,
        user_permissions=_user_permission_changes(baseline_manifest, new),
        settings_added=sorted(_keys(new) - _keys(baseline_manifest)),
        settings_removed=sorted(_keys(baseline_manifest) - _keys(new)),
        settings_needed=settings_needed(new, plugin.setting_values.all()),
        limits_changed=_limits_changed(baseline_manifest, new),
        backup_required=_backup_required(upgrade, database),
        database_size_bytes=database.size_bytes if database is not None else None,
        database_name=database.database_name if database is not None else None,
        organizations_going_offline=(
            PluginGrant.objects.filter(plugin=plugin, state=GrantState.ACTIVE).count()
            if maintenance
            else 0
        ),
        cancellable=not (current_manifest.backend is None and new.backend is not None),
    )
    return PackageUpgradeReview(growth=access_growth(baseline_manifest, new), review=review)


def _trust_change(baseline: PluginPackage, new: PluginPackage) -> str:
    if baseline.trust == Trust.TRUSTED and new.trust == Trust.TRUSTED:
        return "signer_changed" if baseline.signer_public_key != new.signer_public_key else "none"
    if baseline.trust == Trust.TRUSTED:
        return "became_untrusted"
    if new.trust == Trust.TRUSTED:
        return "became_trusted"
    return "none"


def _database_change(current: PluginManifest, new: PluginManifest) -> str:
    if new.database is None:
        return "none"
    return "unchanged" if current.database is not None else "added"


def _migrations_added(
    package: PluginPackage, baseline: PluginPackage, database: PluginDatabase | None
) -> list[str]:
    """The new version's files the database has not applied: against the reported ledger,
    or the baseline's files while the node has reported none."""
    if database is not None and database.ready_at is not None:
        applied = {entry["name"] for entry in database.ledger}
    else:
        applied = {file["name"] for file in baseline.migration_files}
    return [file["name"] for file in package.migration_files if file["name"] not in applied]


def _hooks(manifest: PluginManifest) -> dict[str, bool]:
    declared = manifest.backend is not None
    return {kind: declared and getattr(manifest.hooks, kind) for kind in HOOK_KINDS}


def _user_permission_changes(baseline: PluginManifest, new: PluginManifest) -> dict[str, list[str]]:
    before = {permission.action: permission.defaults for permission in baseline.user_permissions}
    after = {permission.action: permission.defaults for permission in new.user_permissions}
    return {
        "added": [action for action in after if action not in before],
        "removed": [action for action in before if action not in after],
        "defaults_changed": [
            action for action in after if action in before and after[action] != before[action]
        ],
    }


def _keys(manifest: PluginManifest) -> set[str]:
    return {setting.key for setting in manifest.settings}


def _limits_changed(baseline: PluginManifest, new: PluginManifest) -> list[str]:
    before = baseline.limits.model_dump() if baseline.limits else {}
    after = new.limits.model_dump() if new.limits else {}
    return [name for name in LIMIT_NAMES if before.get(name) != after.get(name)]


def _backup_required(upgrade: PluginUpgrade | None, database: PluginDatabase | None) -> bool:
    """Whether the upgrade will back the database up: it existed before the upgrade, and the
    open upgrade a new version replaces has not taken its backup yet."""
    if upgrade is not None:
        return upgrade.backup_required and upgrade.backup_id is None
    return database is not None and database.ready_at is not None
