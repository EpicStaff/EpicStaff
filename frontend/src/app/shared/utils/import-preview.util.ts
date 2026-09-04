import { EntityTypeResult, ImportResult, ImportResultItem } from '../../core/models/import-result.model';

export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };
export type JsonObject = { [key: string]: JsonValue };

export interface ImportFileEntity {
    id?: number | string;
    name?: string;
    role?: string;
    custom_name?: string;
    [field: string]: JsonValue | undefined;
}

export type ImportFileData = Record<string, ImportFileEntity[]>;

const ENTITY_NAME_KEY: Record<string, string> = {
    Agent: 'role',
    LLMConfig: 'custom_name',
    RealtimeConfig: 'custom_name',
};

const ENTITY_FILE_FIELDS: Record<string, string[]> = {
    Flow: ['description', 'time_to_live', 'persistent_variables'],
    Project: ['description', 'process', 'memory', 'max_rpm', 'planning'],
    Agent: ['goal', 'backstory', 'max_iter', 'memory', 'allow_delegation', 'allow_code_execution'],
    LLMModel: ['provider_name', 'predefined', 'is_custom', 'description'],
    LLMConfig: ['custom_name', 'temperature', 'max_tokens', 'timeout'],
    PythonCodeTool: ['description'],
    MCPTool: ['description', 'transport'],
    RealtimeModel: ['provider_name', 'is_custom'],
    RealtimeConfig: ['custom_name'],
};

const SKIPPED_KEYS = new Set(['main_entity', 'version']);

export function buildPreviewImportResult(fileData: ImportFileData): ImportResult {
    const result: ImportResult = {};

    for (const [entityType, entities] of Object.entries(fileData)) {
        if (SKIPPED_KEYS.has(entityType) || !Array.isArray(entities)) continue;

        const nameKey = ENTITY_NAME_KEY[entityType] ?? 'name';
        const extraFields = ENTITY_FILE_FIELDS[entityType] ?? [];

        const items: ImportResultItem[] = entities.map((entity, index) => {
            const extra: JsonObject = {};
            for (const field of extraFields) {
                const val = entity[field];
                if (val !== undefined) extra[field] = val;
            }
            return {
                id: entity.id ?? index,
                name: String(entity[nameKey] ?? entity['name'] ?? 'Untitled'),
                ...extra,
            };
        });

        result[entityType] = {
            total: items.length,
            created: { count: items.length, items },
            reused: { count: 0, items: [] },
        };
    }

    return result;
}

export function enrichImportResult(result: ImportResult, fileData: ImportFileData): ImportResult {
    const enriched: ImportResult = {};

    for (const [entityType, entityResult] of Object.entries(result) as [string, EntityTypeResult][]) {
        const fields = ENTITY_FILE_FIELDS[entityType];
        const fileEntities: ImportFileEntity[] | undefined = fileData[entityType];

        if (!fields || !fileEntities) {
            enriched[entityType] = entityResult;
            continue;
        }

        const nameKey = ENTITY_NAME_KEY[entityType] ?? 'name';
        const lookupById = new Map<number | string, ImportFileEntity>();
        for (const e of fileEntities) {
            if (e.id !== undefined) lookupById.set(e.id, e);
        }
        const lookupByName = new Map<string, ImportFileEntity>(fileEntities.map((e) => [String(e[nameKey] ?? ''), e]));

        const enrichItems = (items: ImportResultItem[]) =>
            items.map((item) => {
                const baseName = item.name.replace(/\s*\(\d+\)$/, '').trim();
                const source = lookupById.get(item.id) ?? lookupByName.get(baseName);
                if (!source) return item;
                const extra: JsonObject = {};
                for (const field of fields) {
                    const val = source[field];
                    if (val !== undefined) extra[field] = val;
                }
                return { ...item, ...extra };
            });

        enriched[entityType] = {
            ...entityResult,
            created: { ...entityResult.created, items: enrichItems(entityResult.created.items) },
            reused: { ...entityResult.reused, items: enrichItems(entityResult.reused.items) },
        };
    }

    return enriched;
}
