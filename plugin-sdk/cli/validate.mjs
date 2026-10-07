// @ts-check
import { readFileSync } from 'node:fs';
import path from 'node:path';

import { collectBundleFiles } from './bundle-files.mjs';
import { lintHtml } from './html-lint.mjs';
import {
    ACCESS_TYPES,
    ALIAS_PATTERN,
    ALLOWED_RESOURCE_TYPES,
    BLOCKED_ARCHIVE_EXTENSIONS,
    BLOCKED_EXTENSIONS,
    FILES_FOLDER,
    ICON_EXTENSIONS,
    IMPORT_VERSION,
    installedTableName,
    KNOWLEDGE_FILE_TYPES,
    KNOWLEDGE_FOLDER,
    LIMITS,
    MANIFEST_KEYS,
    MANIFEST_PATH,
    OLDEST_IMPORT_VERSION,
    PLUGIN_ID_PATTERN,
    PYTHON_CODE_KEYS,
    REQUIRED_MANIFEST_KEYS,
    RESOURCES_PATH,
    SECRET_BINDING_FIELDS,
    SLOT_NAME_PATTERN,
    STORAGE_ACCESS_VALUES,
    SUPPORTED_BRIDGE_VERSIONS,
    SUPPORTED_FORMAT_VERSIONS,
    UI_CONTENT_TYPES,
    UI_FOLDER,
    VERSION_PATTERN,
} from './rules.mjs';

/**
 * @typedef {import('./bundle-files.mjs').Problem} Problem
 * @typedef {import('./bundle-files.mjs').BundleFile} BundleFile
 * @typedef {Record<string, unknown>} JsonObject
 *
 * @typedef {object} ValidationResult
 * @property {Problem[]} problems  every problem found, in a stable order
 * @property {Map<string, BundleFile>} files  what `pack` would put into the zip, sorted by path
 * @property {number} errorCount
 * @property {number} warningCount
 */

const PNG_SIGNATURE = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

/**
 * Checks a plugin folder (plus an optional UI build that goes under `ui/`) against the package
 * format: layout and limits, `plugin.json`, `resources.json`, refs between them, knowledge and
 * storage files, UI file types and limits, and the sandbox rules for every HTML file.
 *
 * @param {{ dir: string, uiDir?: string | null, exclude?: readonly string[] }} options
 * @returns {ValidationResult}
 */
export function validatePlugin({ dir, uiDir = null, exclude = [] }) {
    const { files, problems } = collectBundleFiles(dir, uiDir, exclude);
    const context = new Checker(files, problems);
    context.run();
    const errorCount = problems.filter((problem) => problem.level === 'error').length;
    return { problems, files, errorCount, warningCount: problems.length - errorCount };
}

class Checker {
    /**
     * @param {Map<string, BundleFile>} files
     * @param {Problem[]} problems
     */
    constructor(files, problems) {
        this.files = files;
        this.problems = problems;
        /** @type {Map<string, Buffer>} */
        this.contents = new Map();
    }

    run() {
        this.checkBundle();
        const manifest = this.readJson(MANIFEST_PATH);
        const resources = this.readJson(RESOURCES_PATH);
        if (manifest) this.checkManifest(manifest);
        if (resources) this.checkResources(resources, manifest);
        if (manifest && resources) this.checkRefs(manifest, resources);
        if (manifest) {
            this.checkKnowledge(manifest);
            this.checkStorageFiles(manifest);
            this.checkIcon(manifest);
        }
        this.checkUi(manifest);
    }

    // --- bundle -----------------------------------------------------------------------------------

    checkBundle() {
        let unpacked = 0;
        for (const file of this.files.values()) {
            unpacked += file.size;
            const extension = path.posix.extname(file.path).toLowerCase();
            if (BLOCKED_ARCHIVE_EXTENSIONS.includes(extension)) {
                this.error(file.path, `'${extension}' archives are not supported in a plugin.`);
            } else if (BLOCKED_EXTENSIONS.includes(extension)) {
                this.error(file.path, 'has a blocked executable extension.');
            }
            if (file.path.length > LIMITS.pathChars)
                this.error(file.path, `is longer than ${LIMITS.pathChars} characters.`);
            if (/[\\\u0000-\u001f]/.test(file.path))
                this.error(file.path, 'has a backslash or a control character in its name.');
            const atRoot = file.path === MANIFEST_PATH || file.path === RESOURCES_PATH;
            const inFolder = [KNOWLEDGE_FOLDER, FILES_FOLDER, UI_FOLDER].some((folder) => file.path.startsWith(folder));
            if (!atRoot && !inFolder) {
                this.error(
                    file.path,
                    'Only plugin.json, resources.json, knowledge/, files/ and ui/ may be in a plugin.'
                );
            }
        }
        if (this.files.size > LIMITS.zipEntries) {
            this.error('bundle', `holds ${this.files.size} files; a plugin may hold at most ${LIMITS.zipEntries}.`);
        }
        if (unpacked > LIMITS.unpackedBytes) {
            this.error(
                'bundle',
                `is ${formatBytes(unpacked)} unpacked; the limit is ${formatBytes(LIMITS.unpackedBytes)}.`
            );
        }
    }

    // --- plugin.json ------------------------------------------------------------------------------

    /** @param {JsonObject} manifest */
    checkManifest(manifest) {
        const loc = MANIFEST_PATH;
        this.checkKeys(manifest, loc, MANIFEST_KEYS, REQUIRED_MANIFEST_KEYS);

        if (isInteger(manifest.format_version)) {
            if (!SUPPORTED_FORMAT_VERSIONS.includes(manifest.format_version)) {
                this.error(
                    `${loc}.format_version`,
                    `${manifest.format_version} is not supported (supported: ${SUPPORTED_FORMAT_VERSIONS.join(', ')}).`
                );
            }
        } else if ('format_version' in manifest) this.error(`${loc}.format_version`, 'must be an integer.');

        if (isInteger(manifest.bridge)) {
            if (!SUPPORTED_BRIDGE_VERSIONS.includes(manifest.bridge)) {
                this.error(
                    `${loc}.bridge`,
                    `${manifest.bridge} is not supported (supported: ${SUPPORTED_BRIDGE_VERSIONS.join(', ')}).`
                );
            }
        } else if ('bridge' in manifest) this.error(`${loc}.bridge`, 'must be an integer.');

        if ('id' in manifest)
            this.checkPattern(
                manifest.id,
                `${loc}.id`,
                PLUGIN_ID_PATTERN,
                'a lowercase id: letters, digits and dashes, at most 64 characters'
            );
        if ('version' in manifest) {
            this.checkPattern(manifest.version, `${loc}.version`, VERSION_PATTERN, 'a version such as 0.1.0');
            if (typeof manifest.version === 'string' && manifest.version.length > 64)
                this.error(`${loc}.version`, 'must have at most 64 characters.');
        }
        if ('name' in manifest) this.checkString(manifest.name, `${loc}.name`, 1, 255);
        if ('description' in manifest) this.checkString(manifest.description, `${loc}.description`, 0, 2000);
        if (manifest.icon !== undefined && manifest.icon !== null)
            this.checkString(manifest.icon, `${loc}.icon`, 1, 255);
        if (manifest.ui !== undefined && manifest.ui !== null) {
            if (this.checkObject(manifest.ui, `${loc}.ui`, ['entry'], ['entry'])) {
                this.checkString(/** @type {JsonObject} */ (manifest.ui).entry, `${loc}.ui.entry`, 1, 255);
            }
        }

        const slots = this.list(manifest, 'secret_slots', loc);
        slots.forEach((slot, index) => {
            const at = `${loc}.secret_slots.${index}`;
            if (!this.checkObject(slot, at, ['name', 'description'], ['name'])) return;
            this.checkPattern(slot.name, `${at}.name`, SLOT_NAME_PATTERN, 'UPPER_SNAKE_CASE, at most 60 characters');
            if ('description' in slot) this.checkString(slot.description, `${at}.description`, 0, 500);
        });
        this.requireUnique(
            slots.map((slot) => slot?.name),
            `${loc}.secret_slots`,
            'secret slot name'
        );
        const declaredSlots = new Set(slots.map((slot) => slot?.name));

        const bindings = this.list(manifest, 'secret_bindings', loc);
        bindings.forEach((binding, index) => {
            const at = `${loc}.secret_bindings.${index}`;
            if (!this.checkObject(binding, at, ['entity', 'ref', 'field', 'slot'], ['entity', 'ref', 'field', 'slot']))
                return;
            const entity = binding.entity;
            if (typeof entity !== 'string' || !Object.hasOwn(SECRET_BINDING_FIELDS, entity)) {
                this.error(`${at}.entity`, `must be one of ${Object.keys(SECRET_BINDING_FIELDS).join(', ')}.`);
            } else if (binding.field !== SECRET_BINDING_FIELDS[entity]) {
                this.error(
                    `${at}.field`,
                    `${entity} secrets bind through '${SECRET_BINDING_FIELDS[entity]}', not '${String(binding.field)}'.`
                );
            }
            if (!isInteger(binding.ref)) this.error(`${at}.ref`, 'must be an integer.');
            this.checkPattern(binding.slot, `${at}.slot`, SLOT_NAME_PATTERN, 'a declared secret slot name');
            if (typeof binding.slot === 'string' && !declaredSlots.has(binding.slot)) {
                this.error(`${at}.slot`, `uses undeclared slot '${binding.slot}'.`);
            }
        });
        this.requireUnique(
            bindings.map((binding) => (binding ? `${binding.entity}/${binding.ref}/${binding.field}` : undefined)),
            `${loc}.secret_bindings`,
            'secret binding'
        );

        const knowledge = this.list(manifest, 'knowledge', loc);
        knowledge.forEach((entry, index) => {
            const at = `${loc}.knowledge.${index}`;
            if (
                !this.checkObject(
                    entry,
                    at,
                    ['name', 'description', 'embedder', 'documents', 'attach_to_surfaces'],
                    ['name', 'embedder', 'documents']
                )
            )
                return;
            this.checkString(entry.name, `${at}.name`, 1, 255);
            if ('description' in entry) this.checkString(entry.description, `${at}.description`, 0, 2000);
            if (!isInteger(entry.embedder)) this.error(`${at}.embedder`, 'must be an integer ref.');
            if (!Array.isArray(entry.documents) || entry.documents.length === 0)
                this.error(`${at}.documents`, 'must be a non-empty list of paths.');
            this.checkIntegerList(entry.attach_to_surfaces, `${at}.attach_to_surfaces`);
        });
        this.requireUnique(
            knowledge.map((entry) => entry?.name),
            `${loc}.knowledge`,
            'knowledge name'
        );

        const storageFiles = this.list(manifest, 'storage_files', loc);
        storageFiles.forEach((entry, index) => {
            const at = `${loc}.storage_files.${index}`;
            if (!this.checkObject(entry, at, ['path', 'surfaces', 'attach_to_flows'], ['path'])) return;
            this.checkString(entry.path, `${at}.path`, 1, 255);
            this.checkIntegerList(entry.attach_to_flows, `${at}.attach_to_flows`);
            if (entry.surfaces === undefined) return;
            if (!Array.isArray(entry.surfaces)) {
                this.error(`${at}.surfaces`, 'must be a list.');
                return;
            }
            entry.surfaces.forEach((grant, position) => {
                const grantAt = `${at}.surfaces.${position}`;
                const keys = ['surface', 'can_list', 'can_view', 'can_edit', 'can_delete'];
                if (!this.checkObject(grant, grantAt, keys, ['surface'])) return;
                if (!isInteger(grant.surface)) this.error(`${grantAt}.surface`, 'must be an integer ref.');
                for (const key of keys.slice(1)) {
                    if (key in grant && !STORAGE_ACCESS_VALUES.includes(/** @type {string} */ (grant[key]))) {
                        this.error(`${grantAt}.${key}`, `must be one of ${STORAGE_ACCESS_VALUES.join(', ')}.`);
                    }
                }
            });
        });
        this.requireUnique(
            storageFiles.map((entry) => entry?.path),
            `${loc}.storage_files`,
            'storage file path'
        );

        const access = this.list(manifest, 'access', loc);
        access.forEach((entry, index) => {
            const at = `${loc}.access.${index}`;
            if (!this.checkObject(entry, at, ['alias', 'type', 'ref', 'actions'], ['alias', 'type', 'ref', 'actions']))
                return;
            this.checkPattern(
                entry.alias,
                `${at}.alias`,
                ALIAS_PATTERN,
                'lowercase letters, digits, "_" and "-", starting with a letter, at most 64 characters'
            );
            if (!isInteger(entry.ref)) this.error(`${at}.ref`, 'must be an integer ref.');
            const type = entry.type;
            if (typeof type !== 'string' || !Object.hasOwn(ACCESS_TYPES, type)) {
                this.error(`${at}.type`, `must be one of ${Object.keys(ACCESS_TYPES).join(', ')}.`);
                return;
            }
            const spec = ACCESS_TYPES[type];
            if (spec && isInteger(manifest.bridge) && manifest.bridge < spec.minBridge) {
                this.error(`${at}.type`, `${type} access needs "bridge": ${spec.minBridge} or newer.`);
            }
            if (!Array.isArray(entry.actions) || entry.actions.length === 0) {
                this.error(`${at}.actions`, 'must be a non-empty list.');
                return;
            }
            entry.actions.forEach((action, position) => {
                if (spec && !spec.actions.includes(action)) {
                    this.error(
                        `${at}.actions.${position}`,
                        `'${String(action)}' is not an action of ${type} (allowed: ${spec.actions.join(', ')}).`
                    );
                }
            });
            if (new Set(entry.actions).size !== entry.actions.length) this.error(`${at}.actions`, 'must not repeat.');
        });
        this.requireUnique(
            access.map((entry) => entry?.alias),
            `${loc}.access`,
            'access alias'
        );
    }

    // --- resources.json ---------------------------------------------------------------------------

    /**
     * @param {JsonObject} resources
     * @param {JsonObject | null} manifest
     */
    checkResources(resources, manifest) {
        const loc = RESOURCES_PATH;
        if (resources.main_entity !== 'Flow')
            this.error(`${loc}.main_entity`, 'resources.json must be a Flow export (main_entity "Flow").');
        this.checkImportVersion(resources);
        for (const [key, entities] of Object.entries(resources)) {
            if (key === 'main_entity' || key === 'version') continue;
            if (!ALLOWED_RESOURCE_TYPES.includes(key)) {
                this.error(`${loc}.${key}`, `A plugin cannot contain ${key} entities.`);
                continue;
            }
            if (!Array.isArray(entities) || !entities.every((entity) => isObject(entity) && 'id' in entity)) {
                this.error(`${loc}.${key}`, "must be a list of objects with an 'id'.");
            }
        }
        const flows = entityList(resources, 'Flow');
        if (flows.length === 0) this.error(`${loc}.Flow`, 'resources.json holds no flow.');

        const tables = entityList(resources, 'KeyValueTable');
        const tableIds = new Set(tables.map((table) => table.id));
        const pluginId = manifest && typeof manifest.id === 'string' ? manifest.id : null;
        this.checkKeyValueTables(tables, pluginId);

        for (const flow of flows) {
            const flowAt = `${loc}.Flow.${String(flow.id)}`;
            for (const node of objectList(flow.nodes)) {
                const nodeAt = `${flowAt}.${String(node.node_name || node.id)}`;
                if (node.node_type === 'KeyValueNode') {
                    const bound = node.key_value_table !== null && node.key_value_table !== undefined;
                    const named = typeof node.key_value_table_name === 'string' && node.key_value_table_name !== '';
                    if ((bound || named) && !tableIds.has(node.key_value_table)) {
                        this.error(
                            nodeAt,
                            'is a key-value node using a table that resources.json does not ship (KeyValueTable). ' +
                                "A plugin's flow may only use its own tables."
                        );
                    }
                }
                if (node.node_type === 'KnowledgeNode' && node.source_collection) {
                    this.error(
                        nodeAt,
                        'Knowledge nodes bound to a collection are not supported in plugins yet; attach knowledge to an agent surface instead.'
                    );
                }
                this.checkNameBoundSecrets(node, nodeAt);
            }
            for (const edge of objectList(flow.conditional_edge_list))
                this.checkNameBoundSecrets(edge, `${flowAt}.conditional_edge`);
        }
        for (const tool of entityList(resources, 'PythonCodeTool')) {
            this.checkNameBoundSecrets(tool, `${loc}.PythonCodeTool.${String(tool.id)}`);
        }
    }

    /**
     * EpicStaff converts older import formats up to its own; a newer or non-integer `version` is refused.
     * @param {JsonObject} resources
     */
    checkImportVersion(resources) {
        if (!('version' in resources)) return;
        const loc = `${RESOURCES_PATH}.version`;
        const version = resources.version;
        if (!isInteger(version)) {
            this.error(
                loc,
                `must be an integer import format version (${OLDEST_IMPORT_VERSION} to ${IMPORT_VERSION}).`
            );
        } else if (version > IMPORT_VERSION) {
            this.error(loc, `File version ${version} is newer than supported ${IMPORT_VERSION}.`);
        } else if (version < OLDEST_IMPORT_VERSION) {
            this.error(loc, `No migration path from version ${version}.`);
        }
    }

    /**
     * Every shipped table needs a name that stays valid once prefixed, and names must differ
     * regardless of case (the server checks the same).
     * @param {JsonObject[]} tables
     * @param {string | null} pluginId
     */
    checkKeyValueTables(tables, pluginId) {
        const seen = new Set();
        for (const table of tables) {
            const at = `${RESOURCES_PATH}.KeyValueTable.${String(table.id)}.name`;
            const name = table.name;
            if (typeof name !== 'string' || name.trim() === '') {
                this.error(at, 'A key-value table needs a name.');
                continue;
            }
            const installed = pluginId === null ? null : installedTableName(pluginId, name);
            if (installed !== null && installed.length > LIMITS.tableNameChars) {
                this.error(
                    at,
                    `The key-value table name '${installed}' is longer than ${LIMITS.tableNameChars} characters.`
                );
            } else if (seen.has(name.toLowerCase())) {
                this.error(at, `Two key-value tables are named '${name}' (names are compared regardless of case).`);
            }
            seen.add(name.toLowerCase());
        }
    }

    /**
     * @param {JsonObject} holder
     * @param {string} loc
     */
    checkNameBoundSecrets(holder, loc) {
        const names = new Set();
        for (const key of PYTHON_CODE_KEYS) {
            const code = holder[key];
            if (!isObject(code) || typeof code.code !== 'string') continue;
            const withoutComments = code.code.replace(/^\s*#.*$/gm, '');
            for (const match of withoutComments.matchAll(/\bget_secret\s*\(\s*(?:"([^"\\\n]*)"|'([^'\\\n]*)')/g)) {
                names.add(match[1] ?? match[2]);
            }
        }
        if (names.size === 0) return;
        const calls = [...names]
            .sort()
            .map((name) => `get_secret("${name}")`)
            .join(', ');
        this.error(loc, `Python code that reads secrets by name (${calls}) is not supported in plugins yet.`);
    }

    // --- refs -------------------------------------------------------------------------------------

    /**
     * @param {JsonObject} manifest
     * @param {JsonObject} resources
     */
    checkRefs(manifest, resources) {
        /** @type {Array<[string, string, unknown]>} */
        const references = [];
        objectList(manifest.secret_bindings).forEach((binding, index) => {
            if (typeof binding.entity === 'string')
                references.push([`secret_bindings.${index}.ref`, binding.entity, binding.ref]);
        });
        objectList(manifest.knowledge).forEach((entry, index) => {
            references.push([`knowledge.${index}.embedder`, 'EmbeddingConfig', entry.embedder]);
            asArray(entry.attach_to_surfaces).forEach((surface, position) =>
                references.push([`knowledge.${index}.attach_to_surfaces.${position}`, 'Surface', surface])
            );
        });
        objectList(manifest.storage_files).forEach((entry, index) => {
            objectList(entry.surfaces).forEach((grant, position) =>
                references.push([`storage_files.${index}.surfaces.${position}.surface`, 'Surface', grant.surface])
            );
            asArray(entry.attach_to_flows).forEach((flow, position) =>
                references.push([`storage_files.${index}.attach_to_flows.${position}`, 'Flow', flow])
            );
        });
        objectList(manifest.access).forEach((entry, index) => {
            const spec =
                typeof entry.type === 'string' && Object.hasOwn(ACCESS_TYPES, entry.type)
                    ? ACCESS_TYPES[entry.type]
                    : undefined;
            if (spec) references.push([`access.${index}.ref`, spec.entity, entry.ref]);
        });
        for (const [loc, entityType, ref] of references) {
            if (!isInteger(ref)) continue;
            const ids = new Set(entityList(resources, entityType).map((entity) => entity.id));
            if (!ids.has(ref))
                this.error(`${MANIFEST_PATH}.${loc}`, `resources.json has no ${entityType} with id ${ref}.`);
        }
    }

    // --- knowledge/, files/, icon -----------------------------------------------------------------

    /** @param {JsonObject} manifest */
    checkKnowledge(manifest) {
        objectList(manifest.knowledge).forEach((entry, index) => {
            const documents = asArray(entry.documents);
            documents.forEach((document, position) => {
                const loc = `${MANIFEST_PATH}.knowledge.${index}.documents.${position}`;
                if (typeof document !== 'string') {
                    this.error(loc, 'must be a path.');
                } else if (!document.startsWith(KNOWLEDGE_FOLDER)) {
                    this.error(loc, `'${document}' must be inside knowledge/.`);
                } else if (!this.files.has(document)) {
                    this.error(loc, `The plugin has no '${document}'.`);
                } else if (!KNOWLEDGE_FILE_TYPES.includes(path.posix.extname(document).slice(1).toLowerCase())) {
                    this.error(
                        loc,
                        `'${document}' is not a supported document type (${KNOWLEDGE_FILE_TYPES.join(', ')}).`
                    );
                }
            });
            if (new Set(documents).size !== documents.length)
                this.error(`${MANIFEST_PATH}.knowledge.${index}.documents`, 'documents must not repeat.');
        });
    }

    /** @param {JsonObject} manifest */
    checkStorageFiles(manifest) {
        objectList(manifest.storage_files).forEach((entry, index) => {
            const loc = `${MANIFEST_PATH}.storage_files.${index}.path`;
            if (typeof entry.path !== 'string') return;
            if (!entry.path.startsWith(FILES_FOLDER) || entry.path === FILES_FOLDER) {
                this.error(loc, `'${entry.path}' must be a file inside files/.`);
            } else if (!this.files.has(entry.path)) {
                this.error(loc, `The plugin has no '${entry.path}'.`);
            }
        });
    }

    /** @param {JsonObject} manifest */
    checkIcon(manifest) {
        const icon = manifest.icon;
        if (typeof icon !== 'string') return;
        const loc = `${MANIFEST_PATH}.icon`;
        const extension = path.posix.extname(icon).toLowerCase();
        if (!ICON_EXTENSIONS.includes(extension)) {
            this.error(loc, 'The icon must be a .png or .svg file.');
            return;
        }
        if (!this.files.has(icon)) {
            this.error(loc, `The plugin has no '${icon}'.`);
            return;
        }
        const content = this.read(icon);
        if (content.length > LIMITS.iconBytes) {
            this.error(loc, `The icon is larger than ${LIMITS.iconBytes / 1024} KB.`);
        } else if (extension === '.png' && !content.subarray(0, PNG_SIGNATURE.length).equals(PNG_SIGNATURE)) {
            this.error(loc, `'${icon}' is not a valid PNG image.`);
        } else if (extension === '.svg') {
            const text = content.toString('utf8');
            if (!text.includes('<svg')) this.error(loc, `'${icon}' is not a valid SVG image.`);
            else if (/<script\b|\son[a-z]+\s*=/i.test(text))
                this.warning(loc, `'${icon}' contains script; icons are shown as images, so it never runs. Remove it.`);
        }
    }

    // --- ui/ --------------------------------------------------------------------------------------

    /** @param {JsonObject | null} manifest */
    checkUi(manifest) {
        const uiFiles = [...this.files.values()].filter((file) => file.path.startsWith(UI_FOLDER));
        let total = 0;
        for (const file of uiFiles) {
            total += file.size;
            const extension = path.posix.extname(file.path).toLowerCase();
            if (!Object.hasOwn(UI_CONTENT_TYPES, extension)) {
                this.error(file.path, `UI files must be one of ${Object.keys(UI_CONTENT_TYPES).sort().join(', ')}.`);
            }
            if (extension === '.html') {
                this.problems.push(...lintHtml(this.read(file.path).toString('utf8'), file.path));
            }
        }
        if (uiFiles.length > LIMITS.uiFiles)
            this.error(UI_FOLDER, `holds ${uiFiles.length} files; the limit is ${LIMITS.uiFiles}.`);
        if (total > LIMITS.uiBytes)
            this.error(UI_FOLDER, `is ${formatBytes(total)}; the limit is ${formatBytes(LIMITS.uiBytes)}.`);

        const ui = manifest && isObject(manifest.ui) ? manifest.ui : null;
        if (ui === null) {
            if (uiFiles.length > 0 && manifest)
                this.warning(
                    UI_FOLDER,
                    'holds files, but plugin.json has no "ui": {"entry": …}; the app will not open.'
                );
            return;
        }
        const entry = ui.entry;
        if (typeof entry !== 'string') return;
        const loc = `${MANIFEST_PATH}.ui.entry`;
        if (!entry.startsWith(UI_FOLDER) || path.posix.extname(entry).toLowerCase() !== '.html') {
            this.error(loc, 'ui.entry must be an .html file inside ui/.');
        } else if (!this.files.has(entry)) {
            this.error(loc, `The plugin has no '${entry}'.`);
        }
    }

    // --- helpers ----------------------------------------------------------------------------------

    /**
     * @param {string} zipPath
     * @returns {JsonObject | null}
     */
    readJson(zipPath) {
        if (!this.files.has(zipPath)) {
            this.error(zipPath, `The plugin has no ${zipPath} at its root.`);
            return null;
        }
        let data;
        try {
            data = JSON.parse(this.read(zipPath).toString('utf8'));
        } catch (error) {
            this.error(zipPath, `is not valid JSON: ${error instanceof Error ? error.message : String(error)}`);
            return null;
        }
        if (!isObject(data)) {
            this.error(zipPath, 'must hold a JSON object.');
            return null;
        }
        return data;
    }

    /**
     * @param {string} zipPath
     * @returns {Buffer}
     */
    read(zipPath) {
        let content = this.contents.get(zipPath);
        if (!content) {
            const file = this.files.get(zipPath);
            content = file ? readFileSync(file.source) : Buffer.alloc(0);
            this.contents.set(zipPath, content);
        }
        return content;
    }

    /**
     * Reports unknown and missing keys; true when `value` is an object (so its fields can be checked).
     * @param {unknown} value
     * @param {string} loc
     * @param {readonly string[]} allowed
     * @param {readonly string[]} required
     * @returns {value is JsonObject}
     */
    checkObject(value, loc, allowed, required) {
        if (!isObject(value)) {
            this.error(loc, 'must be an object.');
            return false;
        }
        this.checkKeys(value, loc, allowed, required);
        return true;
    }

    /**
     * @param {JsonObject} value
     * @param {string} loc
     * @param {readonly string[]} allowed
     * @param {readonly string[]} required
     */
    checkKeys(value, loc, allowed, required) {
        for (const key of Object.keys(value)) {
            if (!allowed.includes(key))
                this.error(`${loc}.${key}`, 'is not a known field (unknown fields are refused).');
        }
        for (const key of required) {
            if (!(key in value)) this.error(`${loc}.${key}`, 'is required.');
        }
    }

    /**
     * @param {JsonObject} holder
     * @param {string} key
     * @param {string} loc
     * @returns {Array<JsonObject>}  the object items (others are reported)
     */
    list(holder, key, loc) {
        const value = holder[key];
        if (value === undefined) return [];
        if (!Array.isArray(value)) {
            this.error(`${loc}.${key}`, 'must be a list.');
            return [];
        }
        return value.map((item, index) => {
            if (!isObject(item)) this.error(`${loc}.${key}.${index}`, 'must be an object.');
            return isObject(item) ? item : {};
        });
    }

    /**
     * @param {unknown} value
     * @param {string} loc
     * @param {number} min
     * @param {number} max
     */
    checkString(value, loc, min, max) {
        if (typeof value !== 'string') this.error(loc, 'must be a string.');
        else if (value.length < min)
            this.error(loc, min === 1 ? 'must not be empty.' : `must have at least ${min} characters.`);
        else if (value.length > max) this.error(loc, `must have at most ${max} characters.`);
    }

    /**
     * @param {unknown} value
     * @param {string} loc
     * @param {RegExp} pattern
     * @param {string} description
     */
    checkPattern(value, loc, pattern, description) {
        if (typeof value !== 'string' || !pattern.test(value)) this.error(loc, `must be ${description}.`);
    }

    /**
     * @param {unknown} value
     * @param {string} loc
     */
    checkIntegerList(value, loc) {
        if (value === undefined) return;
        if (!Array.isArray(value) || !value.every(isInteger)) this.error(loc, 'must be a list of integer refs.');
    }

    /**
     * @param {unknown[]} values
     * @param {string} loc
     * @param {string} what
     */
    requireUnique(values, loc, what) {
        const seen = new Set();
        for (const value of values) {
            if (value === undefined) continue;
            if (seen.has(value)) this.error(loc, `duplicate ${what}: ${JSON.stringify(value)}.`);
            seen.add(value);
        }
    }

    /**
     * @param {string} loc
     * @param {string} message
     */
    error(loc, message) {
        this.problems.push({ level: 'error', loc, message });
    }

    /**
     * @param {string} loc
     * @param {string} message
     */
    warning(loc, message) {
        this.problems.push({ level: 'warning', loc, message });
    }
}

/**
 * @param {unknown} value
 * @returns {value is JsonObject}
 */
function isObject(value) {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/**
 * @param {unknown} value
 * @returns {value is number}
 */
function isInteger(value) {
    return typeof value === 'number' && Number.isSafeInteger(value);
}

/**
 * @param {unknown} value
 * @returns {unknown[]}
 */
function asArray(value) {
    return Array.isArray(value) ? value : [];
}

/**
 * @param {unknown} value
 * @returns {JsonObject[]}
 */
function objectList(value) {
    return asArray(value).filter(isObject);
}

/**
 * @param {JsonObject} resources
 * @param {string} entityType
 * @returns {JsonObject[]}
 */
function entityList(resources, entityType) {
    return objectList(resources[entityType]);
}

/** @param {number} bytes */
export function formatBytes(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
