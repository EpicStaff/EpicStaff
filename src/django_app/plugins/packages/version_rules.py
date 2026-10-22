"""What a new version of an installed plugin must be, and what it may not change.

Checked at upload, before anything is stored, and again at the approval that starts the
upgrade, against the state at that moment. The version must be newer than the latest approved
version (the open upgrade's target, else the current package's), by SemVer precedence with
build metadata ignored (`epicstaff_plugin.contracts.versions`). Then each of `UPGRADE_RULES`
looks for changes an upgrade cannot carry, against both the running package and the latest
approved one.

Adding a rule: a function of `UPGRADE_RULES` returning problems located under `manifest.` or
`package.`, then its row in `reference/compatibility-and-versioning.md`.
"""

from collections.abc import Callable
from dataclasses import dataclass

from epicstaff_plugin.contracts.manifest import PluginManifest
from epicstaff_plugin.contracts.versions import is_newer
from epicstaff_plugin.problems import Problem

from plugins.exceptions import PluginUpgradeUnavailableError, PluginVersionNotNewerError
from plugins.lifecycle.open_upgrades import latest_approved_package, open_upgrade_of
from plugins.models import Plugin, PluginDatabase, PluginPackage, PluginUpgrade


@dataclass(frozen=True)
class UpgradeCandidate:
    """A package offered as a new version: its manifest and its migration files."""

    manifest: PluginManifest
    migration_files: list[dict[str, str]]


@dataclass(frozen=True)
class InstalledVersion:
    """What a new version is checked against.

    `current` is the package the plugin runs, `latest` the latest approved one (the open
    upgrade's target when there is one), and `ledger` the migrations the plugin's database
    reported as applied, each `{name, sha256}`.
    """

    current: PluginPackage
    latest: PluginPackage
    ledger: list[dict[str, str]]


def installed_version_of(plugin: Plugin) -> InstalledVersion:
    """What a new version of the installed `plugin` is checked against, read now."""
    return installed_version_with(plugin, open_upgrade_of(plugin))


def installed_version_with(plugin: Plugin, upgrade: PluginUpgrade | None) -> InstalledVersion:
    """`installed_version_of`, for a caller that has read (or locked) the open upgrade."""
    database = PluginDatabase.objects.filter(plugin=plugin).only("pk", "ledger").first()
    return InstalledVersion(
        current=plugin.current_package,
        latest=latest_approved_package(plugin, upgrade),
        ledger=list(database.ledger) if database is not None else [],
    )


def _installed_manifests(installed: InstalledVersion):
    """The manifests a new version must keep the sections of: the running package's, and the
    latest approved one's (a failed upgrade's target may add a backend or a database the
    running version lacks, and its migrations may have run)."""
    return (installed.current.parsed_manifest, installed.latest.parsed_manifest)


def _keeps_the_backend(candidate: UpgradeCandidate, installed: InstalledVersion) -> list[Problem]:
    if candidate.manifest.backend is None and any(
        manifest.backend is not None for manifest in _installed_manifests(installed)
    ):
        return [Problem("manifest.backend", "a new version cannot drop the backend")]
    return []


def _keeps_the_database(candidate: UpgradeCandidate, installed: InstalledVersion) -> list[Problem]:
    if candidate.manifest.database is None and any(
        manifest.database is not None for manifest in _installed_manifests(installed)
    ):
        return [Problem("manifest.database", "a new version cannot drop the database")]
    return []


def _keeps_applied_migrations(
    candidate: UpgradeCandidate, installed: InstalledVersion
) -> list[Problem]:
    """A file named like one of the latest approved package or of the ledger must be the same
    file. A file the new version leaves out is allowed: the node ignores ledger entries it has
    no file for."""
    known: dict[str, set[str]] = {}
    for file in [*installed.latest.migration_files, *installed.ledger]:
        known.setdefault(file["name"], set()).add(file["sha256"])
    return [
        Problem(
            f"package.database/migrations/{file['name']}",
            f"{file['name']} is already applied; a new version must keep it unchanged",
        )
        for file in candidate.migration_files
        if file["name"] in known and known[file["name"]] != {file["sha256"]}
    ]


UPGRADE_RULES: tuple[Callable[[UpgradeCandidate, InstalledVersion], list[Problem]], ...] = (
    _keeps_the_backend,
    _keeps_the_database,
    _keeps_applied_migrations,
)


def assert_upgrade_allowed(candidate: UpgradeCandidate, installed: InstalledVersion) -> None:
    """Refuse a new version that is not newer, or that makes a change an upgrade cannot carry.

    Raises:
        PluginVersionNotNewerError: The version is the latest approved one, an older one, or
            differs from it only in build metadata.
        PluginUpgradeUnavailableError: A rule of `UPGRADE_RULES` found problems; each says why.
    """
    version = candidate.manifest.version
    if not is_newer(version, installed.latest.version):
        raise PluginVersionNotNewerError(
            version,
            installed_version=installed.current.version,
            latest_version=installed.latest.version,
        )
    problems = [problem for rule in UPGRADE_RULES for problem in rule(candidate, installed)]
    if problems:
        raise PluginUpgradeUnavailableError(problems)
