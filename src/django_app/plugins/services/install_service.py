import hashlib
import posixpath
from collections import defaultdict
from functools import partial

from agents.models import Surface, SurfaceStorageItem
from agents.models.surface_models import StorageAccess
from agents.services.surface_content_service import CATALOG_SURFACE_CONTENT, SurfaceContentService
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from rbac.access.resolver import PermissionResolver
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.registry import entity_registry
from tables.import_export.schemas import ImportSettings
from tables.import_export.services.import_service import ImportService
from tables.models import GraphStorageFile, StorageFile
from tables.services.knowledge_services.collection_management_service import (
    CollectionManagementService,
)
from tables.services.knowledge_services.document_management_service import (
    DocumentManagementService,
)
from tables.services.knowledge_services.naive_rag_service import NaiveRagService
from tables.services.secrets.secret_service import secret_service
from tables.services.storage_service import get_storage_backend
from tables.services.storage_service.path_utils import storage_key
from tables.services.storage_service.quota import record_files_within_quota

from plugins.exceptions import (
    PluginAlreadyInstalledError,
    PluginInstallForbiddenError,
    PluginResourceConflictError,
)
from plugins.manifest import PluginPackage, load_package
from plugins.models import Plugin, PluginAsset, PluginResource
from plugins.resource_types import (
    CREATED_CATALOG_ENTITIES,
    IMPORTED_ENTITIES,
    PLUGIN_OWNED_TYPES,
    RESOURCE_MODELS,
    PluginResourceType,
)
from plugins.services import knowledge_service
from plugins.services.bundle_reader import read_bundle
from plugins.services.install_checks import (
    check_secret_values,
    find_conflicts,
    missing_permissions,
    reject_if_installed,
)
from plugins.services.preview import build_preview


class PluginInstallService:
    """Preview and install plugin files into one organization."""

    def inspect(self, uploaded_file, *, user, org_id: int) -> dict:
        """Validate a plugin file and describe what installing it would do. Writes nothing.

        Raises:
            InvalidPluginError: the file breaks the plugin format.
            PluginAlreadyInstalledError: the org already has a plugin with this id.
        """
        package = load_package(read_bundle(uploaded_file))
        reject_if_installed(package, org_id)
        effective = PermissionResolver().resolve(user=user, org_id=org_id)
        return build_preview(
            package,
            missing_permissions=missing_permissions(package, effective),
            conflicts=find_conflicts(package, org_id),
        )

    def install(self, uploaded_file, *, secrets: dict, user, org_id: int) -> Plugin:
        """Install a plugin file with every resource it bundles, all or nothing.

        Every row is written in one transaction. Storage objects cannot roll back,
        so the ones already written are deleted if anything fails.

        Args:
            secrets: Slot name -> value, one entry for every declared secret slot.

        Raises:
            InvalidPluginError: the file breaks the plugin format.
            InvalidPluginSecretsError: `secrets` does not match the declared slots.
            PluginAlreadyInstalledError: the org already has a plugin with this id.
            PluginInstallForbiddenError: the installer cannot create a bundled type.
            PluginResourceConflictError: a secret name or storage path is taken.
        """
        package = load_package(read_bundle(uploaded_file))
        reject_if_installed(package, org_id)
        check_secret_values(
            [slot.name for slot in package.manifest.secret_slots],
            secrets,
            require_every_slot=True,
        )
        effective = PermissionResolver().resolve(user=user, org_id=org_id)
        if missing := missing_permissions(package, effective):
            raise PluginInstallForbiddenError(missing)
        if conflicts := find_conflicts(package, org_id):
            raise PluginResourceConflictError(conflicts)
        return _PluginInstallation(package, secrets, user, org_id, effective).run()


class _PluginInstallation:
    """One install run: holds what it created so later steps and cleanup can reach it."""

    def __init__(self, package: PluginPackage, secrets: dict, user, org_id: int, effective):
        self.package = package
        self.manifest = package.manifest
        self.secret_values = secrets
        self.user = user
        self.org_id = org_id
        self.effective = effective
        self.plugin: Plugin | None = None
        self.secrets_by_slot = {}
        # (entity type, id inside resources.json) -> id of the row the import created.
        self.created_ids: dict[tuple[str, int], int] = {}
        self.written_keys: list[str] = []
        self.storage_backend = None

    def run(self) -> Plugin:
        try:
            with transaction.atomic():
                self._create_plugin()
                self._create_secrets()
                self._register_imported(self._import_resources())
                self._bind_secrets()
                self._create_knowledge()
                self._create_storage_files()
                self._create_assets()
                if self.package.has_knowledge:
                    transaction.on_commit(partial(knowledge_service.start_indexing, self.plugin.pk))
        except BaseException:
            if self.written_keys:
                self.storage_backend.discard_keys(self.written_keys)
            raise
        return self.plugin

    def _create_plugin(self) -> None:
        state = Plugin.State.PREPARING if self.package.has_knowledge else Plugin.State.READY
        try:
            # A savepoint, so a concurrent install of the same id surfaces as 409.
            with transaction.atomic():
                self.plugin = Plugin.objects.create(
                    org_id=self.org_id,
                    created_by=self.user,
                    plugin_id=self.manifest.id,
                    version=self.manifest.version,
                    format_version=self.manifest.format_version,
                    bridge_version=self.manifest.bridge,
                    name=self.manifest.name,
                    description=self.manifest.description,
                    icon_data_url=self.package.icon_data_url,
                    ui_entry=self.package.ui_entry,
                    state=state,
                    access=[entry.model_dump() for entry in self.manifest.access],
                    secret_slots=[slot.model_dump() for slot in self.manifest.secret_slots],
                    manifest=self.manifest.model_dump(mode="json"),
                )
        except IntegrityError as exc:
            raise PluginAlreadyInstalledError(self.manifest.id, self.manifest.version) from exc

    def _register(self, resource_type: PluginResourceType, object_id: int, ref: str) -> None:
        PluginResource.objects.create(
            plugin=self.plugin,
            resource_type=resource_type,
            object_id=object_id,
            manifest_ref=ref,
        )

    def _create_secrets(self) -> None:
        for slot in self.manifest.secret_slots:
            secret = secret_service.create(
                text=self.secret_values[slot.name],
                name=self.package.secret_name(slot.name),
                org_id=self.org_id,
                created_by=self.user,
            )
            self.secrets_by_slot[slot.name] = secret
            self._register(PluginResourceType.SECRET, secret.pk, slot.name)

    def _import_resources(self) -> IDMapper:
        id_mapper, _ = ImportService(entity_registry).import_data(
            self.package.resources,
            EntityType.GRAPH,
            settings=ImportSettings(force_create_types=PLUGIN_OWNED_TYPES),
            org_id=self.org_id,
            user=self.user,
            effective_permissions=self.effective,
        )
        return id_mapper

    def _register_imported(self, id_mapper: IDMapper) -> None:
        """Link only the rows this import created; a reused row belongs to the org."""
        for entity_type, imported in IMPORTED_ENTITIES.items():
            created = set(id_mapper.get_created_ids(entity_type))
            refs_by_new_id = {}
            for entity in self.package.entities(entity_type):
                new_id = id_mapper.get_or_none(entity_type, entity["id"])
                if new_id in created:
                    self.created_ids[(entity_type, entity["id"])] = new_id
                    refs_by_new_id[new_id] = str(entity["id"])
            for new_id in sorted(created):
                self._register(imported.resource_type, new_id, refs_by_new_id.get(new_id, ""))
        self._register_created_catalog_models(id_mapper)

    def _register_created_catalog_models(self, id_mapper: IDMapper) -> None:
        """Link the custom models the import created because the org's catalog had no match.

        A reused catalog row is shared, so it is never linked; neither is a created
        row that is not owned by this org.
        """
        for entity_type, resource_type in CREATED_CATALOG_ENTITIES.items():
            created = id_mapper.get_created_ids(entity_type)
            if not created:
                continue
            refs_by_new_id = {
                id_mapper.get_or_none(entity_type, entity["id"]): str(entity["id"])
                for entity in self.package.entities(entity_type)
            }
            owned_ids = (
                RESOURCE_MODELS[resource_type]
                .model.objects.filter(pk__in=created, org_id=self.org_id)
                .values_list("pk", flat=True)
            )
            for new_id in sorted(owned_ids):
                self._register(resource_type, new_id, refs_by_new_id.get(new_id, ""))

    def _created(self, entity_type: str, ref: int) -> int:
        return self.created_ids[(entity_type, ref)]

    def _bind_secrets(self) -> None:
        for binding in self.manifest.secret_bindings:
            resource_type = IMPORTED_ENTITIES[EntityType(binding.entity)].resource_type
            instance = RESOURCE_MODELS[resource_type].model.objects.get(
                pk=self._created(binding.entity, binding.ref)
            )
            setattr(instance, binding.field, self.secrets_by_slot[binding.slot])
            instance.save(update_fields=[binding.field])

    def _create_knowledge(self) -> None:
        knowledge_by_surface: dict[int, list[dict]] = defaultdict(list)
        for entry in self.manifest.knowledge:
            collection = CollectionManagementService.create_collection(
                collection_name=entry.name,
                description=entry.description,
                org_id=self.org_id,
            )
            DocumentManagementService.upload_files_batch(
                collection.collection_id,
                [
                    SimpleUploadedFile(posixpath.basename(path), self.package.bundle.read(path))
                    for path in entry.documents
                ],
            )
            naive_rag = NaiveRagService.create_or_update_naive_rag(
                collection.collection_id,
                embedder_id=self._created(EntityType.EMBEDDING_CONFIG, entry.embedder),
            )
            NaiveRagService.init_document_configs(naive_rag.naive_rag_id)
            self._register(
                PluginResourceType.SOURCE_COLLECTION, collection.collection_id, entry.name
            )
            for surface_ref in entry.attach_to_surfaces:
                knowledge_by_surface[self._created(EntityType.SURFACE, surface_ref)].append(
                    {"collection": collection, "naive_search_config": {}}
                )
        # replace_knowledge rewrites a surface's whole knowledge list, so one call per surface.
        for surface in Surface.objects.filter(pk__in=knowledge_by_surface):
            SurfaceContentService.replace_knowledge(
                surface, knowledge_by_surface[surface.pk], CATALOG_SURFACE_CONTENT
            )

    def _create_storage_files(self) -> None:
        entries = self.manifest.storage_files
        if not entries:
            return
        self.storage_backend = get_storage_backend(organization_prefix="")
        files = []
        for entry in entries:
            path = self.package.storage_path(entry.path)
            content = self.package.bundle.read(entry.path)
            key = storage_key(self.org_id, path)
            # Recorded before the write, so a write that fails halfway is cleaned up too.
            self.written_keys.append(key)
            self.storage_backend.put_bytes(key, content)
            files.append((path, len(content)))
        record_files_within_quota(self.org_id, files)

        rows = {
            row.path: row
            for row in StorageFile.objects.filter(
                org_id=self.org_id, path__in=[path for path, _ in files]
            )
        }
        surface_items = []
        flow_links = []
        for entry in entries:
            storage_file = rows[self.package.storage_path(entry.path)]
            self._register(PluginResourceType.STORAGE_FILE, storage_file.pk, entry.path)
            for grant in entry.surfaces:
                surface_items.append(
                    SurfaceStorageItem(
                        surface_id=self._created(EntityType.SURFACE, grant.surface),
                        storage_file=storage_file,
                        can_list=StorageAccess(grant.can_list),
                        can_view=StorageAccess(grant.can_view),
                        can_edit=StorageAccess(grant.can_edit),
                        can_delete=StorageAccess(grant.can_delete),
                    )
                )
            # An agent only sees a file that is also attached to the flow it runs in.
            for flow_ref in entry.attach_to_flows:
                flow_links.append(
                    GraphStorageFile(
                        graph_id=self._created(EntityType.GRAPH, flow_ref),
                        storage_file=storage_file,
                    )
                )
        SurfaceStorageItem.objects.bulk_create(surface_items)
        GraphStorageFile.objects.bulk_create(flow_links)

    def _create_assets(self) -> None:
        PluginAsset.objects.bulk_create(
            [
                PluginAsset(
                    plugin=self.plugin,
                    path=asset.path,
                    content_type=asset.content_type,
                    content=asset.content,
                    sha256=hashlib.sha256(asset.content).hexdigest(),
                )
                for asset in self.package.ui_assets
            ]
        )
