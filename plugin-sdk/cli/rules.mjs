// @ts-check
/**
 * The plugin package rules the CLI checks, mirrored from EpicStaff's server
 * (`src/django_app/plugins/manifest.py`, `services/bundle_reader.py`) and the plugin-apps contract.
 * The server stays authoritative: a bundle that passes here can still be refused there, and a
 * newer EpicStaff may accept more.
 */

export const MANIFEST_PATH = 'plugin.json';
export const RESOURCES_PATH = 'resources.json';
export const KNOWLEDGE_FOLDER = 'knowledge/';
export const FILES_FOLDER = 'files/';
export const UI_FOLDER = 'ui/';

export const SUPPORTED_FORMAT_VERSIONS = [1];
export const SUPPORTED_BRIDGE_VERSIONS = [1, 2];
/** The newest `resources.json` import format this EpicStaff reads. */
export const IMPORT_VERSION = 3;
/** The oldest one it can still convert (an absent `version` means 1). */
export const OLDEST_IMPORT_VERSION = 1;

export const LIMITS = {
    zipBytes: 30 * 1024 * 1024,
    zipEntries: 400,
    unpackedBytes: 60 * 1024 * 1024,
    uiFiles: 300,
    uiBytes: 20 * 1024 * 1024,
    iconBytes: 64 * 1024,
    pathChars: 255,
    /** A key-value table name, after the plugin prefix (`MAX_TABLE_NAME_LENGTH` on the server). */
    tableNameChars: 255,
};

/**
 * UI file types the asset server serves, with the content type it sends.
 * @type {Readonly<Record<string, string>>}
 */
export const UI_CONTENT_TYPES = {
    '.html': 'text/html; charset=utf-8',
    '.js': 'text/javascript; charset=utf-8',
    '.mjs': 'text/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.json': 'application/json',
    '.map': 'application/json',
    '.txt': 'text/plain; charset=utf-8',
    '.svg': 'image/svg+xml',
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.gif': 'image/gif',
    '.webp': 'image/webp',
    '.ico': 'image/x-icon',
    '.woff': 'font/woff',
    '.woff2': 'font/woff2',
    '.ttf': 'font/ttf',
    '.otf': 'font/otf',
};

export const ICON_EXTENSIONS = ['.png', '.svg'];

/** Document types a knowledge collection accepts. */
export const KNOWLEDGE_FILE_TYPES = ['pdf', 'csv', 'docx', 'txt', 'json', 'html', 'md'];

/** Executable and archive extensions EpicStaff refuses anywhere in an upload. */
export const BLOCKED_EXTENSIONS = [
    '.exe',
    '.msi',
    '.com',
    '.scr',
    '.pif',
    '.bat',
    '.cmd',
    '.vbs',
    '.vbe',
    '.wsh',
    '.wsf',
    '.ps1',
    '.psm1',
    '.psd1',
    '.sh',
    '.bash',
    '.csh',
    '.ksh',
    '.zsh',
    '.app',
    '.command',
    '.elf',
    '.jar',
    '.war',
    '.ear',
    '.dll',
    '.so',
    '.dylib',
];
export const BLOCKED_ARCHIVE_EXTENSIONS = [
    '.rar',
    '.7z',
    '.cab',
    '.iso',
    '.arj',
    '.lzh',
    '.ace',
    '.arc',
    '.lz',
    '.lzma',
    '.zst',
];

/** Junk an OS adds when zipping a folder; EpicStaff drops it, the CLI never packs it. */
export const IGNORED_NAMES = ['.DS_Store', '__MACOSX', 'Thumbs.db'];

export const PLUGIN_ID_PATTERN = /^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$/;
export const SLOT_NAME_PATTERN = /^[A-Z][A-Z0-9_]{0,59}$/;
export const ALIAS_PATTERN = /^[a-z][a-z0-9_-]{0,63}$/;
export const VERSION_PATTERN = /^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$/;

export const MANIFEST_KEYS = [
    'format_version',
    'bridge',
    'id',
    'version',
    'name',
    'description',
    'icon',
    'ui',
    'secret_slots',
    'secret_bindings',
    'knowledge',
    'storage_files',
    'access',
];
export const REQUIRED_MANIFEST_KEYS = ['format_version', 'bridge', 'id', 'version', 'name'];

/**
 * Each binding entity and the one field its secret goes into.
 * @type {Readonly<Record<string, string>>}
 */
export const SECRET_BINDING_FIELDS = {
    LLMConfig: 'api_key_secret',
    EmbeddingConfig: 'api_key_secret',
    MCPTool: 'auth_secret',
};

export const STORAGE_ACCESS_VALUES = ['allow', 'unset', 'deny'];

/**
 * Access types: the actions each allows, the `resources.json` entity its `ref` names, the bridge it needs.
 * @type {Readonly<Record<string, { actions: readonly string[], entity: string, minBridge: number }>>}
 */
export const ACCESS_TYPES = {
    flow: { actions: ['run', 'sessions.read', 'sessions.stop'], entity: 'Flow', minBridge: 1 },
    key_value_table: { actions: ['read'], entity: 'KeyValueTable', minBridge: 2 },
};

/** `resources.json` entity lists a plugin may contain (plugin-owned plus shared catalog rows). */
export const ALLOWED_RESOURCE_TYPES = [
    'Flow',
    'AgentDefinition',
    'Surface',
    'LLMConfig',
    'EmbeddingConfig',
    'PythonCodeTool',
    'MCPTool',
    'WebhookTrigger',
    'KeyValueTable',
    'LLMModel',
    'EmbeddingModel',
    'LLMModelTag',
    'LLMConfigTag',
    'EmbeddingModelTag',
    'GraphTag',
    'Label',
];

export const PYTHON_CODE_KEYS = ['python_code', 'pre_python_code', 'post_python_code'];

/**
 * The installed name of a shipped key-value table: `chat-admin` + `conversations` → `chat_admin__conversations`.
 * @param {string} pluginId
 * @param {string} tableName
 * @returns {string}
 */
export function installedTableName(pluginId, tableName) {
    return `${String(pluginId).replaceAll('-', '_')}__${tableName}`;
}
