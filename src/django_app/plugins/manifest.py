"""The plugin file format: plugin.json, and the rules a whole bundle must satisfy.

`load_package` is the only entry point. It turns an unpacked bundle into a
`PluginPackage` or raises `InvalidPluginError` listing every problem it found.
"""

import base64
import json
import posixpath
from copy import deepcopy
from dataclasses import dataclass
from typing import Annotated, Literal

from django.core.exceptions import ValidationError as DjangoValidationError
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from pydantic import ValidationError as PydanticValidationError
from tables.constants.key_value_constants import MAX_TABLE_NAME_LENGTH
from tables.constants.knowledge_constants import ALLOWED_FILE_TYPES
from tables.import_export.constants import MAIN_ENTITY_KEY
from tables.import_export.enums import EntityType, NodeType
from tables.import_export.version_conversions.base import VersionConverter
from tables.services.secrets.parse_code import parse_secret_names
from tables.services.storage_service.path_utils import (
    MAX_PATH_CHARS,
    check_new_name,
    sanitize_storage_path,
)

from plugins.exceptions import InvalidPluginError
from plugins.resource_types import CATALOG_TYPES, PLUGIN_OWNED_TYPES
from plugins.services.bundle_reader import PluginBundle

SUPPORTED_FORMAT_VERSIONS = frozenset({1})
SUPPORTED_BRIDGE_VERSIONS = frozenset({1, 2})

MANIFEST_PATH = "plugin.json"
RESOURCES_PATH = "resources.json"
KNOWLEDGE_FOLDER = "knowledge/"
FILES_FOLDER = "files/"
UI_FOLDER = "ui/"

# Sized for a production build of a full framework app: lazy chunks, fonts, images.
MAX_UI_ASSETS = 300
MAX_UI_ASSET_BYTES = 20 * 1024 * 1024
MAX_ICON_BYTES = 64 * 1024

# The only files a page may ship, and the type each is served with. Frameworks emit
# .mjs chunks, .map source maps, web fonts and a licence .txt next to the bundle.
UI_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".map": "application/json",
    ".txt": "text/plain; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".otf": "font/otf",
}
ICON_CONTENT_TYPES = {".svg": "image/svg+xml", ".png": "image/png"}
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# What a page may do with each kind of resource an `access[]` entry names.
ACCESS_ACTIONS_BY_TYPE: dict[str, tuple[str, ...]] = {
    "flow": ("run", "sessions.read", "sessions.stop"),
    "key_value_table": ("read",),
}
# The resources.json entity an entry's `ref` points at.
ACCESS_ENTITY_TYPES: dict[str, EntityType] = {
    "flow": EntityType.GRAPH,
    "key_value_table": EntityType.KEY_VALUE_TABLE,
}
# The first bridge version whose methods can use each access type. A v1 page has no
# method that reads a table, so granting it one would be a grant nothing can use.
ACCESS_MIN_BRIDGE_VERSION: dict[str, int] = {
    "flow": 1,
    "key_value_table": 2,
}
AccessType = Literal["flow", "key_value_table"]
AccessAction = Literal["run", "sessions.read", "sessions.stop", "read"]

# The (entity, field) pairs a secret slot may be bound to. Each is an FK to Secret,
# so binding never depends on a secret's name.
SECRET_BINDING_FIELDS = {
    EntityType.LLM_CONFIG: "api_key_secret",
    EntityType.EMBEDDING_CONFIG: "api_key_secret",
    EntityType.MCP_TOOL: "auth_secret",
}

_PYTHON_CODE_KEYS = ("python_code", "pre_python_code", "post_python_code")

PluginId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")]
SlotName = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{0,59}$")]
Alias = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]
Version = Annotated[
    str,
    StringConstraints(pattern=r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$", max_length=64),
]
BundlePath = Annotated[str, StringConstraints(min_length=1, max_length=255)]
StorageAccessValue = Literal["allow", "unset", "deny"]


class _ManifestModel(BaseModel):
    # A field the format does not define is an error, so a secret slot that tries
    # to carry a `value` is rejected instead of silently dropped.
    model_config = ConfigDict(extra="forbid")


class SecretSlot(_ManifestModel):
    name: SlotName
    description: str = Field(default="", max_length=500)


class SecretBinding(_ManifestModel):
    entity: Literal["LLMConfig", "EmbeddingConfig", "MCPTool"]
    ref: int
    field: Literal["api_key_secret", "auth_secret"]
    slot: SlotName

    @model_validator(mode="after")
    def _field_belongs_to_entity(self):
        expected = SECRET_BINDING_FIELDS[EntityType(self.entity)]
        if self.field != expected:
            raise ValueError(f"{self.entity} secrets bind through '{expected}', not '{self.field}'")
        return self


class KnowledgeEntry(_ManifestModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=2000)
    embedder: int
    documents: list[BundlePath] = Field(min_length=1)
    attach_to_surfaces: list[int] = Field(default_factory=list)


class SurfaceStorageGrant(_ManifestModel):
    surface: int
    can_list: StorageAccessValue = "unset"
    can_view: StorageAccessValue = "unset"
    can_edit: StorageAccessValue = "unset"
    can_delete: StorageAccessValue = "unset"


class StorageFileEntry(_ManifestModel):
    path: BundlePath
    surfaces: list[SurfaceStorageGrant] = Field(default_factory=list)
    attach_to_flows: list[int] = Field(default_factory=list)


class AccessEntry(_ManifestModel):
    alias: Alias
    type: AccessType
    ref: int
    actions: list[AccessAction] = Field(min_length=1)

    @model_validator(mode="after")
    def _valid_actions(self):
        if len(set(self.actions)) != len(self.actions):
            raise ValueError("actions must not repeat")
        allowed = ACCESS_ACTIONS_BY_TYPE[self.type]
        for action in self.actions:
            if action not in allowed:
                raise ValueError(
                    f"action '{action}' does not apply to a {self.type} "
                    f"(allowed: {', '.join(allowed)})"
                )
        return self


class UiSpec(_ManifestModel):
    entry: BundlePath


class PluginManifest(_ManifestModel):
    format_version: int
    bridge: int
    id: PluginId
    version: Version
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=2000)
    icon: BundlePath | None = None
    ui: UiSpec | None = None
    secret_slots: list[SecretSlot] = Field(default_factory=list)
    secret_bindings: list[SecretBinding] = Field(default_factory=list)
    knowledge: list[KnowledgeEntry] = Field(default_factory=list)
    storage_files: list[StorageFileEntry] = Field(default_factory=list)
    access: list[AccessEntry] = Field(default_factory=list)

    @model_validator(mode="after")
    def _consistent(self):
        if self.format_version not in SUPPORTED_FORMAT_VERSIONS:
            raise ValueError(
                f"format_version {self.format_version} is not supported "
                f"(supported: {sorted(SUPPORTED_FORMAT_VERSIONS)})"
            )
        if self.bridge not in SUPPORTED_BRIDGE_VERSIONS:
            raise ValueError(
                f"bridge {self.bridge} is not supported "
                f"(supported: {sorted(SUPPORTED_BRIDGE_VERSIONS)})"
            )
        _require_unique("secret slot name", [slot.name for slot in self.secret_slots])
        _require_unique("access alias", [entry.alias for entry in self.access])
        _require_unique("knowledge name", [entry.name for entry in self.knowledge])
        _require_unique("storage file path", [entry.path for entry in self.storage_files])
        _require_unique(
            "secret binding",
            [(binding.entity, binding.ref, binding.field) for binding in self.secret_bindings],
        )
        declared = {slot.name for slot in self.secret_slots}
        for binding in self.secret_bindings:
            if binding.slot not in declared:
                raise ValueError(f"secret binding uses undeclared slot '{binding.slot}'")
        for entry in self.access:
            needed = ACCESS_MIN_BRIDGE_VERSION[entry.type]
            if self.bridge < needed:
                raise ValueError(
                    f"access '{entry.alias}' is a {entry.type}, which needs bridge {needed} "
                    f"or later (this plugin declares bridge {self.bridge})"
                )
        return self


def _require_unique(what: str, values: list) -> None:
    seen = set()
    for value in values:
        if value in seen:
            raise ValueError(f"duplicate {what}: {value!r}")
        seen.add(value)


def slot_secret_name(plugin_id: str, slot: str) -> str:
    """Name of the org secret holding a plugin's slot value: `<SLUG>__<SLOT>`."""
    return f"{plugin_id.upper().replace('-', '_')}__{slot}"


def key_value_table_name(plugin_id: str, name: str) -> str:
    """Name a bundled key-value table is installed under: `<slug>__<name>`.

    The prefix keeps a plugin's table apart from the org's own tables, whose names
    are unique per org regardless of case.
    """
    return f"{plugin_id.replace('-', '_')}__{name}"


@dataclass(frozen=True)
class UiAsset:
    # Relative to the bundle's ui/ folder.
    path: str
    content_type: str
    content: bytes


@dataclass(frozen=True)
class PluginPackage:
    """A bundle that passed every rule, ready to preview or install."""

    manifest: PluginManifest
    # resources.json, converted to the current import format version, with every
    # key-value table already renamed to its installed `<slug>__<name>`.
    resources: dict
    bundle: PluginBundle
    icon_data_url: str
    ui_entry: str
    ui_assets: list[UiAsset]

    def secret_name(self, slot: str) -> str:
        """Name of the org secret created for `slot`: `<SLUG>__<SLOT>`."""
        return slot_secret_name(self.manifest.id, slot)

    def storage_path(self, bundle_path: str) -> str:
        """Org-relative storage path a bundled `files/...` file is written to."""
        return f"plugins/{self.manifest.id}/{bundle_path.removeprefix(FILES_FOLDER)}"

    def entities(self, entity_type: str) -> list[dict]:
        return self.resources.get(entity_type) or []

    @property
    def has_knowledge(self) -> bool:
        return bool(self.manifest.knowledge)


def load_package(bundle: PluginBundle) -> PluginPackage:
    """Validate a whole bundle against the format and return it as a package.

    Raises:
        InvalidPluginError: lists every problem, so an author can fix them in one go.
    """
    manifest = _load_manifest(bundle)
    resources = _load_resources(bundle)

    errors: list[dict] = []
    errors += _check_layout(bundle)
    errors += _check_resource_types(resources)
    errors += _check_refs(manifest, resources)
    errors += _check_flows(resources)
    errors += _check_key_value_tables(manifest, resources)
    errors += _check_key_value_nodes(resources)
    errors += _check_name_bound_secrets(resources)
    errors += _check_knowledge(manifest, bundle)
    errors += _check_storage_files(manifest, bundle)
    ui_entry, ui_assets, ui_errors = _load_ui(manifest, bundle)
    errors += ui_errors
    icon_data_url, icon_errors = _load_icon(manifest, bundle)
    errors += icon_errors
    if errors:
        raise InvalidPluginError(errors)

    return PluginPackage(
        manifest=manifest,
        resources=_with_installed_table_names(manifest.id, resources),
        bundle=bundle,
        icon_data_url=icon_data_url,
        ui_entry=ui_entry,
        ui_assets=ui_assets,
    )


def _load_json(bundle: PluginBundle, path: str):
    if not bundle.has(path):
        raise InvalidPluginError([{"loc": path, "message": f"The zip has no {path} at its root."}])
    try:
        data = json.loads(bundle.read(path).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidPluginError(
            [{"loc": path, "message": f"{path} is not valid JSON: {exc}"}]
        ) from exc
    if not isinstance(data, dict):
        raise InvalidPluginError([{"loc": path, "message": f"{path} must hold a JSON object."}])
    return data


def _load_manifest(bundle: PluginBundle) -> PluginManifest:
    data = _load_json(bundle, MANIFEST_PATH)
    try:
        return PluginManifest.model_validate(data)
    except PydanticValidationError as exc:
        raise InvalidPluginError(
            [
                {
                    "loc": ".".join([MANIFEST_PATH, *(str(part) for part in error["loc"])]),
                    "message": error["msg"],
                }
                for error in exc.errors()
            ]
        ) from exc


def _load_resources(bundle: PluginBundle) -> dict:
    data = _load_json(bundle, RESOURCES_PATH)
    if data.get(MAIN_ENTITY_KEY) != EntityType.GRAPH:
        raise InvalidPluginError(
            [
                {
                    "loc": f"{RESOURCES_PATH}.{MAIN_ENTITY_KEY}",
                    "message": f'resources.json must be a Flow export (main_entity "{EntityType.GRAPH}").',
                }
            ]
        )
    try:
        return VersionConverter.convert(deepcopy(data))
    except (DjangoValidationError, TypeError) as exc:
        message = exc.messages[0] if isinstance(exc, DjangoValidationError) else str(exc)
        raise InvalidPluginError(
            [{"loc": f"{RESOURCES_PATH}.version", "message": message}]
        ) from exc


def _check_layout(bundle: PluginBundle) -> list[dict]:
    allowed_roots = (KNOWLEDGE_FOLDER, FILES_FOLDER, UI_FOLDER)
    return [
        {
            "loc": path,
            "message": "Only plugin.json, resources.json, knowledge/, files/ and ui/ may be in a plugin.",
        }
        for path in sorted(bundle.files)
        if path not in (MANIFEST_PATH, RESOURCES_PATH) and not path.startswith(allowed_roots)
    ]


def _check_resource_types(resources: dict) -> list[dict]:
    errors = []
    allowed = PLUGIN_OWNED_TYPES | CATALOG_TYPES
    for key, entities in resources.items():
        if key in (MAIN_ENTITY_KEY, "version"):
            continue
        if key not in allowed:
            errors.append(
                {
                    "loc": f"{RESOURCES_PATH}.{key}",
                    "message": f"A plugin cannot contain {key} entities.",
                }
            )
            continue
        if not isinstance(entities, list) or not all(
            isinstance(entity, dict) and "id" in entity for entity in entities
        ):
            errors.append(
                {
                    "loc": f"{RESOURCES_PATH}.{key}",
                    "message": "must be a list of objects with an 'id'.",
                }
            )
    if not resources.get(EntityType.GRAPH):
        errors.append(
            {
                "loc": f"{RESOURCES_PATH}.{EntityType.GRAPH}",
                "message": "resources.json holds no flow.",
            }
        )
    return errors


def _ids(resources: dict, entity_type: str) -> set:
    entities = resources.get(entity_type)
    if not isinstance(entities, list):
        return set()
    return {entity.get("id") for entity in entities if isinstance(entity, dict)}


def _check_refs(manifest: PluginManifest, resources: dict) -> list[dict]:
    """Every ref in plugin.json must name an entity inside resources.json."""
    references: list[tuple[str, str, int]] = []
    for index, binding in enumerate(manifest.secret_bindings):
        references.append((f"secret_bindings.{index}.ref", binding.entity, binding.ref))
    for index, entry in enumerate(manifest.knowledge):
        references.append(
            (f"knowledge.{index}.embedder", EntityType.EMBEDDING_CONFIG, entry.embedder)
        )
        for position, surface in enumerate(entry.attach_to_surfaces):
            references.append(
                (f"knowledge.{index}.attach_to_surfaces.{position}", EntityType.SURFACE, surface)
            )
    for index, entry in enumerate(manifest.storage_files):
        for position, grant in enumerate(entry.surfaces):
            references.append(
                (
                    f"storage_files.{index}.surfaces.{position}.surface",
                    EntityType.SURFACE,
                    grant.surface,
                )
            )
        for position, flow in enumerate(entry.attach_to_flows):
            references.append(
                (f"storage_files.{index}.attach_to_flows.{position}", EntityType.GRAPH, flow)
            )
    for index, entry in enumerate(manifest.access):
        references.append((f"access.{index}.ref", ACCESS_ENTITY_TYPES[entry.type], entry.ref))

    return [
        {
            "loc": f"{MANIFEST_PATH}.{loc}",
            "message": f"resources.json has no {entity_type} with id {ref}.",
        }
        for loc, entity_type, ref in references
        if ref not in _ids(resources, entity_type)
    ]


def _check_flows(resources: dict) -> list[dict]:
    """Knowledge nodes would point at a collection id from the author's server."""
    errors = []
    for flow in resources.get(EntityType.GRAPH) or []:
        for node in flow.get("nodes") or []:
            if node.get("node_type") == NodeType.KNOWLEDGE_NODE and node.get("source_collection"):
                errors.append(
                    {
                        "loc": f"{RESOURCES_PATH}.Flow.{flow.get('id')}.{node.get('node_name') or node.get('id')}",
                        "message": "Knowledge nodes bound to a collection are not supported in plugins yet; "
                        "attach knowledge to an agent surface instead.",
                    }
                )
    return errors


def _check_key_value_tables(manifest: PluginManifest, resources: dict) -> list[dict]:
    """Every bundled table needs a name that is still valid, and unique, once prefixed."""
    tables = resources.get(EntityType.KEY_VALUE_TABLE)
    if not isinstance(tables, list):
        # _check_resource_types already reports a malformed entity list.
        return []
    errors = []
    seen: set[str] = set()
    for table in tables:
        if not isinstance(table, dict):
            continue
        loc = f"{RESOURCES_PATH}.{EntityType.KEY_VALUE_TABLE}.{table.get('id')}"
        name = table.get("name")
        if not isinstance(name, str) or not name.strip():
            errors.append({"loc": loc, "message": "A key-value table needs a name."})
            continue
        installed_name = key_value_table_name(manifest.id, name)
        if len(installed_name) > MAX_TABLE_NAME_LENGTH:
            errors.append(
                {
                    "loc": loc,
                    "message": f"The key-value table name '{installed_name}' is longer than "
                    f"{MAX_TABLE_NAME_LENGTH} characters.",
                }
            )
        elif name.lower() in seen:
            errors.append({"loc": loc, "message": f"Two key-value tables are named '{name}'."})
        seen.add(name.lower())
    return errors


def _check_key_value_nodes(resources: dict) -> list[dict]:
    """A Key-Value node may use only a table the plugin ships.

    The importer re-binds a node to a table by name inside the installing org, so a
    node naming a table the bundle does not ship would read or write the org's own
    table of that name and could hand its rows to the plugin.
    """
    shipped = _ids(resources, EntityType.KEY_VALUE_TABLE)
    errors = []
    for flow in resources.get(EntityType.GRAPH) or []:
        for node in flow.get("nodes") or []:
            if node.get("node_type") != NodeType.KEY_VALUE_NODE:
                continue
            table_id = node.get("key_value_table")
            if table_id is None and not node.get("key_value_table_name"):
                continue
            if not isinstance(table_id, int) or table_id not in shipped:
                errors.append(
                    {
                        "loc": f"{RESOURCES_PATH}.Flow.{flow.get('id')}.{node.get('node_name') or node.get('id')}",
                        "message": "A Key-Value node may only use a key-value table the plugin "
                        "ships in resources.json.",
                    }
                )
    return errors


def _with_installed_table_names(plugin_id: str, resources: dict) -> dict:
    """Rename the bundled tables, and the Key-Value nodes' references to them, to their installed names.

    Done once here, so preview, conflict checks and the install all see the same name.
    `resources` is the package's own converted copy, so it is changed in place.
    """
    names_by_id = {}
    for table in resources.get(EntityType.KEY_VALUE_TABLE) or []:
        table["name"] = key_value_table_name(plugin_id, table["name"])
        names_by_id[table["id"]] = table["name"]
    if not names_by_id:
        return resources
    for flow in resources.get(EntityType.GRAPH) or []:
        for node in flow.get("nodes") or []:
            if (
                node.get("node_type") == NodeType.KEY_VALUE_NODE
                and node.get("key_value_table") in names_by_id
            ):
                node["key_value_table_name"] = names_by_id[node["key_value_table"]]
    return resources


def _check_name_bound_secrets(resources: dict) -> list[dict]:
    """Code that reads a secret by name would collide with the org's own secret names."""
    errors = []
    for tool in resources.get(EntityType.PYTHON_CODE_TOOL) or []:
        errors += _name_bound_errors(f"{RESOURCES_PATH}.PythonCodeTool.{tool.get('id')}", tool)
    for flow in resources.get(EntityType.GRAPH) or []:
        for node in flow.get("nodes") or []:
            errors += _name_bound_errors(
                f"{RESOURCES_PATH}.Flow.{flow.get('id')}.{node.get('node_name') or node.get('id')}",
                node,
            )
        for edge in flow.get("conditional_edge_list") or []:
            errors += _name_bound_errors(
                f"{RESOURCES_PATH}.Flow.{flow.get('id')}.conditional_edge", edge
            )
    return errors


def _name_bound_errors(loc: str, holder: dict) -> list[dict]:
    names = set()
    for key in _PYTHON_CODE_KEYS:
        code = holder.get(key)
        if isinstance(code, dict) and isinstance(code.get("code"), str):
            names |= parse_secret_names(code=code["code"])
    if not names:
        return []
    calls = ", ".join(f'get_secret("{name}")' for name in sorted(names))
    return [
        {
            "loc": loc,
            "message": f"Python code that reads secrets by name ({calls}) is not supported in plugins yet.",
        }
    ]


def _extension(path: str) -> str:
    return posixpath.splitext(path)[1].lower()


def _check_knowledge(manifest: PluginManifest, bundle: PluginBundle) -> list[dict]:
    errors = []
    for index, entry in enumerate(manifest.knowledge):
        for position, document in enumerate(entry.documents):
            loc = f"{MANIFEST_PATH}.knowledge.{index}.documents.{position}"
            if not document.startswith(KNOWLEDGE_FOLDER):
                errors.append({"loc": loc, "message": f"'{document}' must be inside knowledge/."})
            elif not bundle.has(document):
                errors.append({"loc": loc, "message": f"The zip has no '{document}'."})
            elif _extension(document).lstrip(".") not in ALLOWED_FILE_TYPES:
                errors.append(
                    {"loc": loc, "message": f"'{document}' is not a supported document type."}
                )
        _require_unique_documents(errors, index, entry)
    return errors


def _require_unique_documents(errors: list[dict], index: int, entry: KnowledgeEntry) -> None:
    if len(set(entry.documents)) != len(entry.documents):
        errors.append(
            {
                "loc": f"{MANIFEST_PATH}.knowledge.{index}.documents",
                "message": "documents must not repeat.",
            }
        )


def _check_storage_files(manifest: PluginManifest, bundle: PluginBundle) -> list[dict]:
    errors = []
    for index, entry in enumerate(manifest.storage_files):
        loc = f"{MANIFEST_PATH}.storage_files.{index}.path"
        if not entry.path.startswith(FILES_FOLDER) or entry.path == FILES_FOLDER:
            errors.append({"loc": loc, "message": f"'{entry.path}' must be a file inside files/."})
            continue
        if not bundle.has(entry.path):
            errors.append({"loc": loc, "message": f"The zip has no '{entry.path}'."})
            continue
        destination = f"plugins/{manifest.id}/{entry.path.removeprefix(FILES_FOLDER)}"
        try:
            check_new_name(sanitize_storage_path(destination, allow_empty=False))
        except ValueError as exc:
            errors.append({"loc": loc, "message": str(exc)})
            continue
        if len(destination) > MAX_PATH_CHARS:
            errors.append(
                {"loc": loc, "message": f"'{entry.path}' makes a storage path that is too long."}
            )
    return errors


def _load_ui(
    manifest: PluginManifest, bundle: PluginBundle
) -> tuple[str, list[UiAsset], list[dict]]:
    errors = []
    paths = bundle.paths_under(UI_FOLDER)
    for path in paths:
        if _extension(path) not in UI_CONTENT_TYPES:
            errors.append(
                {
                    "loc": path,
                    "message": f"UI files must be one of {', '.join(sorted(UI_CONTENT_TYPES))}.",
                }
            )
    if len(paths) > MAX_UI_ASSETS:
        errors.append({"loc": UI_FOLDER, "message": f"ui/ holds more than {MAX_UI_ASSETS} files."})
    if sum(len(bundle.read(path)) for path in paths) > MAX_UI_ASSET_BYTES:
        errors.append(
            {
                "loc": UI_FOLDER,
                "message": f"ui/ is larger than {MAX_UI_ASSET_BYTES // (1024 * 1024)} MB.",
            }
        )

    ui_entry = ""
    if manifest.ui is not None:
        entry = manifest.ui.entry
        loc = f"{MANIFEST_PATH}.ui.entry"
        if not entry.startswith(UI_FOLDER) or _extension(entry) != ".html":
            errors.append({"loc": loc, "message": "ui.entry must be an .html file inside ui/."})
        elif not bundle.has(entry):
            errors.append({"loc": loc, "message": f"The zip has no '{entry}'."})
        else:
            ui_entry = entry.removeprefix(UI_FOLDER)

    assets = [
        UiAsset(
            path=path.removeprefix(UI_FOLDER),
            content_type=UI_CONTENT_TYPES.get(_extension(path), "application/octet-stream"),
            content=bundle.read(path),
        )
        for path in paths
    ]
    return ui_entry, assets, errors


def _load_icon(manifest: PluginManifest, bundle: PluginBundle) -> tuple[str, list[dict]]:
    if manifest.icon is None:
        return "", []
    loc = f"{MANIFEST_PATH}.icon"
    path = manifest.icon
    content_type = ICON_CONTENT_TYPES.get(_extension(path))
    if content_type is None:
        return "", [{"loc": loc, "message": "The icon must be a .png or .svg file."}]
    if not bundle.has(path):
        return "", [{"loc": loc, "message": f"The zip has no '{path}'."}]
    content = bundle.read(path)
    if len(content) > MAX_ICON_BYTES:
        return "", [
            {"loc": loc, "message": f"The icon is larger than {MAX_ICON_BYTES // 1024} KB."}
        ]
    if not _looks_like(content_type, content):
        return "", [
            {
                "loc": loc,
                "message": f"'{path}' is not a valid {_extension(path)[1:].upper()} image.",
            }
        ]
    return f"data:{content_type};base64,{base64.b64encode(content).decode('ascii')}", []


def _looks_like(content_type: str, content: bytes) -> bool:
    if content_type == "image/png":
        return content.startswith(_PNG_SIGNATURE)
    try:
        return "<svg" in content.decode("utf-8")
    except UnicodeDecodeError:
        return False
