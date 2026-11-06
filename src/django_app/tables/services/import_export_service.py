import json
from typing import BinaryIO

from django.conf import settings as django_settings
from rbac.access.resolver import PermissionResolver
from rest_framework.exceptions import ValidationError
from tables.import_export.archive import (
    ImportArchive,
    detect_file_kind,
    invalid_archive,
    temporary_archive,
)
from tables.import_export.constants import ARCHIVE_IMPORT_VERSION, MAIN_ENTITY_KEY
from tables.import_export.export_format_strategies import JsonExportFormatStrategy
from tables.import_export.permissions import ExportAccessPolicy
from tables.import_export.registry import entity_registry
from tables.import_export.services.export_service import ExportService
from tables.import_export.services.import_service import ImportService, ImportSettings
from tables.import_export.services.inspect_service import InspectService
from tables.import_export.version_conversions.base import VersionConverter
from tables.import_export.version_conversions.exceptions import UnsupportedImportVersionError
from tables.services.trigger_nodes import TriggerNodeInspector, trigger_node_access

_ZIP_HEAD_SIZE = 4
_COPY_CHUNK_SIZE = 1024 * 1024


def _file_version(envelope: dict) -> int:
    # Files from before the version field default to 1, as the converter treats them.
    return envelope.get("version", 1)


def ensure_job_import_version(envelope: dict) -> None:
    """Refuse a file older than archives in an import job.

    A plain JSON export of any version is imported synchronously; a version-6
    JSON that carries a knowledge collection is refused there with
    `archive_required`, because only an archive holds the collection's files.

    Raises:
        ValidationError: {"code": "use_sync_import"} for a version before archives.
    """
    if _file_version(envelope) < ARCHIVE_IMPORT_VERSION:
        raise ValidationError(
            {
                "code": "use_sync_import",
                "detail": "This export is older than archives; import it directly.",
            }
        )


class ViewSetImportExportService:
    def __init__(self, entity_type, export_prefix, filename_attr, format_strategies=None):
        self.entity_type = entity_type
        self.export_prefix = export_prefix
        self.filename_attr = filename_attr
        self.export_service = ExportService(entity_registry)
        self.import_service = ImportService(entity_registry)
        self.format_strategies = format_strategies or {"json": JsonExportFormatStrategy()}

    def export_entity(self, instance, fmt: str = "json", org_id: int | None = None, *, user):
        result = self.export_service.export_entities(
            self.entity_type,
            [instance.pk],
            org_id=org_id,
            policy=ExportAccessPolicy.for_user(user, org_id),
        )
        if fmt not in self.format_strategies:
            raise ValidationError(
                f"Unsupported export format: '{fmt}'. Supported: {list(self.format_strategies)}"
            )
        strategy = self.format_strategies[fmt]
        base_name = str(getattr(instance, self.filename_attr, "object"))
        return strategy.render(
            result.data, self.entity_type, self.export_prefix, base_name, excluded=result.excluded
        )

    def bulk_export(self, entity_ids, fmt: str = "json", org_id: int | None = None, *, user):
        result = self.export_service.export_entities(
            self.entity_type,
            entity_ids,
            org_id=org_id,
            policy=ExportAccessPolicy.for_user(user, org_id),
        )
        if fmt not in self.format_strategies:
            raise ValidationError(
                f"Unsupported export format: '{fmt}'. Supported: {list(self.format_strategies)}"
            )
        strategy = self.format_strategies[fmt]
        base_name = f"bulk_{len(entity_ids)}"
        return strategy.render(
            result.data, self.entity_type, self.export_prefix, base_name, excluded=result.excluded
        )

    def _parse_and_validate(self, file) -> dict:
        try:
            data = json.load(file)
        except json.JSONDecodeError as e:
            raise ValidationError("Invalid JSON file") from e
        return self._validate_envelope(data, self.entity_type)

    @staticmethod
    def _validate_envelope(data, main_entity) -> dict:
        """Check the file's main entity and bring it to the current version."""
        if not isinstance(data, dict):
            raise ValidationError("Invalid import file: expected a JSON object")

        if data.get(MAIN_ENTITY_KEY) is None:
            raise ValidationError(f"Missing '{MAIN_ENTITY_KEY}' in import file")

        file_main_entity = data[MAIN_ENTITY_KEY]
        if file_main_entity != main_entity:
            raise ValidationError(
                f"Provided wrong entity. Got: {file_main_entity}. Expected: {main_entity.value}"
            )

        try:
            return VersionConverter.convert(data)
        except UnsupportedImportVersionError as e:
            raise ValidationError(str(e)) from e

    def import_entity(self, file, user, settings: ImportSettings = None, org_id: int | None = None):
        data = self._parse_and_validate(file)

        effective_permissions = PermissionResolver().resolve(user=user, org_id=org_id)
        id_mapper, registry = self.import_service.import_data(
            data,
            self.entity_type,
            settings=settings,
            org_id=org_id,
            user=user,
            effective_permissions=effective_permissions,
        )
        summary = id_mapper.get_detailed_summary(registry)

        return summary

    def import_archive(
        self,
        path: str,
        *,
        org_id: int | None,
        user,
        settings: ImportSettings,
        main_entity,
    ) -> dict:
        """Import the export archive at `path`; returns the import summary.

        Used by the import job, which owns the file and deletes it afterwards.

        Raises:
            ValidationError: The archive is unsafe or unreadable, its main entity is
                not `main_entity`, or it is older than archives.
        """
        with ImportArchive.open(path) as archive:
            data = _read_job_envelope(archive, main_entity)
            effective_permissions = PermissionResolver().resolve(user=user, org_id=org_id)
            id_mapper, registry = self.import_service.import_data(
                data,
                main_entity,
                settings=settings,
                org_id=org_id,
                user=user,
                effective_permissions=effective_permissions,
                archive=archive,
            )
        return id_mapper.get_detailed_summary(registry)

    def inspect_entity(self, file, org_id: int | None = None) -> dict:
        """Review a `.json` export or the `export.json` of a `.zip` one.

        Only the envelope is read; the files an archive carries are not.

        Raises:
            InvalidArchiveError: The archive is larger than `MAX_KNOWLEDGE_ARCHIVE_SIZE`
                (checked before it is copied to disk), or `ImportArchive` refuses it.
        """
        head = file.read(_ZIP_HEAD_SIZE)
        file.seek(0)
        if detect_file_kind(head) == "zip":
            data = self._validate_envelope(self._read_archive_envelope(file), self.entity_type)
        else:
            data = self._parse_and_validate(file)
        return InspectService().inspect(data, org_id=org_id)

    @staticmethod
    def _read_archive_envelope(file) -> dict:
        max_size = django_settings.MAX_KNOWLEDGE_ARCHIVE_SIZE
        size = getattr(file, "size", None)
        if size is not None and size > max_size:
            raise invalid_archive(f"the archive is larger than {max_size} bytes")
        # ImportArchive checks a file on disk; an upload may only be in memory.
        with (
            temporary_archive(lambda copy: _copy_at_most(file, copy, max_size)) as path,
            ImportArchive.open(path) as archive,
        ):
            return archive.envelope()


def check_job_archive(path: str, *, main_entity, user, org_id: int) -> None:
    """Refuse an archive an import job would refuse up front, before the job is created.

    Applies every archive cap, the version and main-entity checks, and the flows:USE
    check for trigger nodes, so a caller learns of these at once instead of from a
    failed job. The import job runs them all again on the stored archive.

    Raises:
        InvalidArchiveError: The archive is unsafe or unreadable.
        ValidationError: Its main entity is not `main_entity`, or it is older than
            archives (`use_sync_import`).
        FlowWithTriggerNodesRequiresUsePermissionError: It holds a trigger node and
            `user` lacks USE on flows in `org_id`.
    """
    with ImportArchive.open(path) as archive:
        data = _read_job_envelope(archive, main_entity)
    # The same check ImportService.import_data runs before it writes anything.
    if TriggerNodeInspector.has_any_in_export(data):
        trigger_node_access.assert_user_may_recreate(user, org_id)


def _read_job_envelope(archive: ImportArchive, main_entity) -> dict:
    """Return the archive's envelope at the current version, checked for `main_entity`."""
    envelope = archive.envelope()
    if isinstance(envelope, dict):
        ensure_job_import_version(envelope)
    return ViewSetImportExportService._validate_envelope(envelope, main_entity)


def _copy_at_most(source: BinaryIO, target: BinaryIO, max_size: int) -> None:
    # Covers a source that reports no size, or a wrong one: copying stops at the cap.
    copied = 0
    while chunk := source.read(_COPY_CHUNK_SIZE):
        copied += len(chunk)
        if copied > max_size:
            raise invalid_archive(f"the archive is larger than {max_size} bytes")
        target.write(chunk)
