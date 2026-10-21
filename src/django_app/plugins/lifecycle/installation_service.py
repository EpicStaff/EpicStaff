import hashlib
import tempfile
import zipfile
from typing import BinaryIO

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from epicstaff_plugin.contracts.manifest import PluginManifest
from epicstaff_plugin.package_layout import PackageArchive
from epicstaff_plugin.problems import MANIFEST_LOC, Problem
from epicstaff_plugin.signing import SignatureVerdict
from utils.logger import logger

from plugins.access.declared_access import declared_access_problems
from plugins.activity.recorder import ActivityRecorder
from plugins.audit import PackageFacts, log_package_action
from plugins.configuration.limits import PlatformMaximums, manifest_limit_problems
from plugins.databases.database_records import PluginDatabaseRecords
from plugins.exceptions import (
    InvalidPluginError,
    PackageFileMismatchError,
    PackageNotPendingError,
    PackageTooLargeError,
    PluginPackageNotFoundError,
    PluginUpgradeUnavailableError,
    UntrustedNotAcknowledgedError,
)
from plugins.lifecycle.plugin_actions import assert_plugin_in_service
from plugins.models import Plugin, PluginPackage, PluginState, ReviewState, Trust
from plugins.nodes.placement_service import PlacementService
from plugins.packages.package_reader import read_uploaded_package
from plugins.packages.package_store import (
    PackageFileMissingError,
    PluginPackageStore,
    get_package_store,
    package_storage_key,
)
from plugins.packages.signature_verifier import (
    trusted_signer_public_key,
    verify_package_signature,
)
from plugins.packages.spa_publisher import SpaPublisher

_HASH_CHUNK_BYTES = 1024 * 1024


def max_package_bytes() -> int:
    return settings.PLUGINS_MAX_PACKAGE_MB * 1024 * 1024


class PluginInstallationService:
    """Upload of plugin packages and the review decisions on them.

    In this version a plugin has at most one approved package (no upgrades). Approving
    publishes the SPA; a plugin without a backend runs at once, one with a backend is placed
    on the plugin node and is `provisioning` until the node reports its process running. A
    package with a database also gets the record of the plugin's own database, which the
    node creates before it first starts the backend.
    """

    def __init__(
        self,
        store: PluginPackageStore | None = None,
        publisher: SpaPublisher | None = None,
        placements: PlacementService | None = None,
    ):
        self._store = store or get_package_store()
        self._publisher = publisher or SpaPublisher()
        self._placements = placements or PlacementService()

    def upload(self, file: BinaryIO, size: int, uploaded_by) -> PluginPackage:
        """Check an uploaded package and keep it as the plugin's package pending review.

        A new identifier creates its plugin in state `uploaded`. A pending package of the same
        plugin is replaced, row and file.

        Raises:
            PackageTooLargeError: Larger than PLUGINS_MAX_PACKAGE_MB.
            InvalidPluginError: The package breaks a format or manifest rule, declares access
                this EpicStaff's catalog does not have, asks for more than the platform
                maximums, or holds nothing to install.
            InvalidSignatureError: The package's signature does not belong to it.
            PluginUninstallingError: The plugin is uninstalled or being deleted.
            PluginUpgradeUnavailableError: The plugin already has an approved package.
        """
        if size > max_package_bytes():
            raise PackageTooLargeError()
        package = read_uploaded_package(file)
        manifest = package.manifest
        if problems := declared_access_problems(manifest):
            raise InvalidPluginError(problems)
        verdict = verify_package_signature(package)
        _assert_installable(manifest)
        _assert_within_platform_maximums(manifest)
        existing = Plugin.objects.filter(identifier=manifest.id).first()
        if existing is not None:
            assert_plugin_in_service(existing)
            if existing.current_package_id is not None:
                raise PluginUpgradeUnavailableError()

        sha256 = _sha256(file)
        storage_key = package_storage_key(manifest.id, manifest.version, sha256)
        file.seek(0)
        self._store.save(storage_key, file)
        try:
            with transaction.atomic():
                pending, replaced = self._register_pending_package(
                    package,
                    sha256=sha256,
                    size=size,
                    storage_key=storage_key,
                    verdict=verdict,
                    uploaded_by=uploaded_by,
                )
        except BaseException:
            self._discard_stored_files([storage_key])
            raise
        for old in replaced:
            log_package_action("replace_pending", uploaded_by, old, replaced_by=pending.pk)
        log_package_action(
            "upload",
            uploaded_by,
            PackageFacts.of(pending),
            size=size,
            trust=pending.trust,
            signer=pending.signer_key_name or pending.signer_key_id or "none",
        )
        return pending

    def _register_pending_package(
        self, package: PackageArchive, *, sha256, size, storage_key, verdict, uploaded_by
    ) -> tuple[PluginPackage, list[PackageFacts]]:
        manifest = package.manifest
        plugin, _ = Plugin.objects.select_for_update().get_or_create(
            identifier=manifest.id,
            defaults={"name": manifest.name, "description": manifest.description},
        )
        assert_plugin_in_service(plugin)
        if plugin.current_package_id is not None:
            raise PluginUpgradeUnavailableError()
        replaced = list(
            plugin.packages.select_for_update().filter(review_state=ReviewState.PENDING)
        )
        replaced_keys = [old.storage_key for old in replaced if old.storage_key != storage_key]
        # Taken before the rows go, for the log written once this upload has committed.
        replaced_facts = [PackageFacts.of(old) for old in replaced]
        for old in replaced:
            old.delete()
        plugin.name = manifest.name
        plugin.description = manifest.description
        plugin.save(update_fields=["name", "description", "updated_at"])
        pending = PluginPackage.objects.create(
            plugin=plugin,
            version=manifest.version,
            sha256=sha256,
            size=size,
            storage_key=storage_key,
            manifest=manifest.model_dump(mode="json"),
            trust=verdict.trust,
            signature_status=verdict.signature,
            signer_key_id=verdict.key_id,
            signer_key_name=verdict.key_name,
            signer_public_key=trusted_signer_public_key(verdict),
            icon_bytes=package.icon,
            icon_media_type=package.icon_media_type,
            spa_file_count=package.summary.spa_file_count,
            spa_bytes=package.summary.spa_bytes,
            wheel_count=package.summary.wheel_count,
            migration_count=package.summary.migration_count,
            uploaded_by=uploaded_by,
        )
        if replaced_keys:
            self._after_commit_robustly(self._delete_unreferenced, replaced_keys)
        return pending, replaced_facts

    def approve(self, package_id: int, approved_by, *, untrusted_acknowledged: bool) -> Plugin:
        """Approve a pending package: make it the plugin's running package and publish its SPA.

        The stored file is checked again first: it must still be the reviewed file, and its
        signature is judged with the trusted keys as they are now, so a key the operator has
        removed since the upload no longer makes the package Trusted. A changed verdict is
        saved even when the approval is then refused, so the review shows it.

        The SPA's files are written before the approval commits and served (`current`
        switched) only once it has; a failed approval leaves nothing served. A package with
        a backend gets its placement (port and Unix user id on the plugin node) and leaves
        the plugin `provisioning`, and one with a database gets its database record, in the
        same transaction; the platform maximums are checked again, as they are now.

        Raises:
            PluginPackageNotFoundError: No package with this id.
            PackageNotPendingError: The package was already decided.
            PackageFileMismatchError: The stored file is missing or not the reviewed one.
            InvalidPluginError: The stored package breaks a package rule or asks for more than
                today's platform maximums.
            InvalidSignatureError: Its signature does not verify with today's trusted keys.
            UntrustedNotAcknowledgedError: The package is untrusted now and the SuperAdmin did
                not acknowledge it.
            NoPluginNodeError: The package has a backend and no plugin node is registered.
            PluginNodeFullError: The plugin node has no free port or user id left.
            NoPluginDatabaseServerError: The package has a database and no plugin database
                server is registered.
            PluginUninstallingError: The plugin is uninstalled or being deleted.
        """
        with tempfile.TemporaryFile() as local_copy:
            pending = self._pending_package(package_id)
            assert_plugin_in_service(pending.plugin)
            archive = self._reviewed_archive(pending, local_copy)
            _assert_within_platform_maximums(archive.manifest)
            package = self._record_verdict(package_id, verify_package_signature(archive))
            if package.trust == Trust.UNTRUSTED and not untrusted_acknowledged:
                raise UntrustedNotAcknowledgedError()
            plugin = self._approve_checked(package_id, approved_by, archive, local_copy)
        approved = plugin.current_package
        log_package_action(
            "approve",
            approved_by,
            PackageFacts(approved.pk, plugin.identifier, approved.version, approved.sha256),
            trust=approved.trust,
            signer=approved.signer_key_name or "none",
            untrusted_acknowledged=untrusted_acknowledged,
        )
        return plugin

    def _approve_checked(
        self, package_id: int, approved_by, archive: PackageArchive, local_copy: BinaryIO
    ) -> Plugin:
        manifest = archive.manifest
        version_written = False
        committed = False

        def serve_published_version() -> None:
            nonlocal committed
            committed = True
            self._publisher.switch_current(manifest.id, manifest.version)

        try:
            with transaction.atomic():
                package = self._pending_package(package_id, lock=True)
                assert_plugin_in_service(package.plugin)
                if manifest.spa is not None:
                    local_copy.seek(0)
                    with zipfile.ZipFile(local_copy) as zip_file:
                        self._publisher.write_version(
                            manifest.id,
                            manifest.version,
                            zip_file,
                            [file.path for file in archive.spa_files],
                        )
                    version_written = True
                    transaction.on_commit(serve_published_version)
                package.review_state = ReviewState.APPROVED
                package.approved_by = approved_by
                package.approved_at = timezone.now()
                package.save(update_fields=["review_state", "approved_by", "approved_at"])
                plugin = package.plugin
                if manifest.backend is not None:
                    self._placements.ensure_placement(plugin)
                if manifest.database is not None:
                    PluginDatabaseRecords().ensure_for(plugin)
                plugin.current_package = package
                plugin.state = (
                    PluginState.RUNNING if manifest.backend is None else PluginState.PROVISIONING
                )
                plugin.name = manifest.name
                plugin.description = manifest.description
                plugin.save(
                    update_fields=["current_package", "state", "name", "description", "updated_at"]
                )
                ActivityRecorder().package_approved(
                    approved_by,
                    identifier=plugin.identifier,
                    version=package.version,
                    trust=package.trust,
                )
        except BaseException:
            if version_written and not committed:
                self._discard_written_version(manifest)
            raise
        return Plugin.objects.with_summary().get(pk=plugin.pk)

    def reject(self, package_id: int, rejected_by) -> None:
        """Reject a pending package: delete its row and file, and its plugin if never approved.

        A plugin deleted this way also loses its published files, once the deletion commits.

        Raises:
            PluginPackageNotFoundError: No package with this id.
            PackageNotPendingError: The package was already decided.
        """
        with transaction.atomic():
            package = self._pending_package(package_id, lock=True)
            facts = PackageFacts.of(package)
            plugin = package.plugin
            package.delete()
            plugin_removed = plugin.current_package_id is None
            if plugin_removed:
                plugin.delete()
                self._after_commit_robustly(self._publisher.remove_plugin, plugin.identifier)
            self._after_commit_robustly(self._delete_unreferenced, [package.storage_key])
        log_package_action("reject", rejected_by, facts, plugin_removed=plugin_removed)

    @staticmethod
    def _after_commit_robustly(cleanup, *args) -> None:
        """Run `cleanup(*args)` once the transaction commits; a failure is logged and never
        undoes or fails what committed."""

        # A named function, not a `partial`: Django logs a failed robust callback by its
        # `__qualname__`, which a `partial` lacks, and would raise from the handler.
        def run_cleanup() -> None:
            cleanup(*args)

        transaction.on_commit(run_cleanup, robust=True)

    @staticmethod
    def _pending_package(package_id: int, *, lock: bool = False) -> PluginPackage:
        packages = PluginPackage.objects.select_related("plugin")
        if lock:
            packages = packages.select_for_update()
        package = packages.filter(pk=package_id).first()
        if package is None:
            raise PluginPackageNotFoundError()
        if package.review_state != ReviewState.PENDING:
            raise PackageNotPendingError()
        return package

    def _reviewed_archive(self, package: PluginPackage, local_copy: BinaryIO) -> PackageArchive:
        """Download the package into `local_copy`, check it is the reviewed file, and read it."""
        try:
            self._store.download(package.storage_key, local_copy)
        except PackageFileMissingError:
            _log_file_mismatch(package, found=None)
            raise PackageFileMismatchError() from None
        found = _sha256(local_copy)
        if found != package.sha256:
            _log_file_mismatch(package, found=found)
            raise PackageFileMismatchError()
        return read_uploaded_package(local_copy)

    def _record_verdict(self, package_id: int, verdict: SignatureVerdict) -> PluginPackage:
        verdict_fields = {
            "trust": verdict.trust,
            "signature_status": verdict.signature,
            "signer_key_id": verdict.key_id,
            "signer_key_name": verdict.key_name,
            "signer_public_key": trusted_signer_public_key(verdict),
        }
        with transaction.atomic():
            package = self._pending_package(package_id, lock=True)
            changed = [
                name for name, value in verdict_fields.items() if getattr(package, name) != value
            ]
            for name in changed:
                setattr(package, name, verdict_fields[name])
            if changed:
                package.save(update_fields=changed)
                logger.info(
                    "Plugin package {package_id} judged {trust} at approval ({signature}); "
                    "it was judged otherwise at upload",
                    package_id=package_id,
                    trust=verdict.trust,
                    signature=verdict.signature,
                )
        return package

    def _discard_written_version(self, manifest: PluginManifest) -> None:
        # Cleanup after a failed approval: the files are not served, so a failure here only
        # leaves them for the next approval of this version to replace.
        try:
            self._publisher.discard_version(manifest.id, manifest.version)
        except OSError:
            logger.exception(
                "Could not remove the unpublished files of {identifier} {version}",
                identifier=manifest.id,
                version=manifest.version,
            )

    def _discard_stored_files(self, storage_keys: list[str]) -> None:
        # Cleanup after a failed upload must not hide why the upload failed.
        try:
            self._delete_unreferenced(storage_keys)
        except Exception:
            logger.exception(
                "Could not delete {storage_keys} from the plugin package bucket after a failed "
                "upload; delete them by hand",
                storage_keys=storage_keys,
            )

    def _delete_unreferenced(self, storage_keys: list[str]) -> None:
        # A re-upload of identical bytes reuses the key of the package it replaced.
        referenced = set(
            PluginPackage.objects.filter(storage_key__in=storage_keys).values_list(
                "storage_key", flat=True
            )
        )
        for key in storage_keys:
            if key not in referenced:
                self._store.delete(key)


def _assert_installable(manifest: PluginManifest) -> None:
    if manifest.spa is None and manifest.backend is None:
        raise InvalidPluginError(
            [
                Problem(
                    MANIFEST_LOC,
                    "declares neither an spa nor a backend section, so there is nothing to install",
                )
            ]
        )


def _assert_within_platform_maximums(manifest: PluginManifest) -> None:
    if problems := manifest_limit_problems(manifest, PlatformMaximums.from_settings()):
        raise InvalidPluginError(problems)


def _log_file_mismatch(package: PluginPackage, *, found: str | None) -> None:
    logger.error(
        "Plugin package {package_id}: the stored file {storage_key} is {problem}; "
        "expected sha256 {expected}, found {found}",
        package_id=package.pk,
        storage_key=package.storage_key,
        problem="missing" if found is None else "not the reviewed file",
        expected=package.sha256,
        found=found or "nothing",
    )


def _sha256(file: BinaryIO) -> str:
    file.seek(0)
    digest = hashlib.sha256()
    while chunk := file.read(_HASH_CHUNK_BYTES):
        digest.update(chunk)
    file.seek(0)
    return digest.hexdigest()
