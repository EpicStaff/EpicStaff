import { JSONSchema7 } from 'json-schema';

import { ToolVariableType, VariableInputType } from '../parameters';

const TYPE_VALUES: ToolVariableType[] = ['string', 'number', 'integer', 'boolean', 'object', 'array', 'any'];
const INPUT_TYPE_VALUES: VariableInputType[] = ['user_input', 'agent_input', 'mixed'];
const NAME_PATTERN = '^[a-zA-Z]\\w*$';
const NAME_MAX_LENGTH = 64;
const DESCRIPTION_MAX_LENGTH = 8046;

const property: JSONSchema7 = {
    type: 'object',
    additionalProperties: false,
    required: ['type'],
    properties: {
        type: { enum: TYPE_VALUES },
        description: { type: 'string', maxLength: DESCRIPTION_MAX_LENGTH },
        default_value: {},
        properties: {
            type: 'object',
            additionalProperties: { $ref: '#/definitions/property' },
        },
        required_properties: { type: 'array', items: { type: 'string' } },
        item: { $ref: '#/definitions/property' },
    },
};

const variable: JSONSchema7 = {
    type: 'object',
    additionalProperties: false,
    required: ['name', 'type', 'input_type'],
    properties: {
        name: { type: 'string', pattern: NAME_PATTERN, maxLength: NAME_MAX_LENGTH },
        type: { enum: TYPE_VALUES },
        description: { type: 'string', maxLength: DESCRIPTION_MAX_LENGTH },
        input_type: { enum: INPUT_TYPE_VALUES },
        required: { type: 'boolean' },
        default_value: {},
        properties: {
            type: 'object',
            additionalProperties: { $ref: '#/definitions/property' },
        },
        required_properties: { type: 'array', items: { type: 'string' } },
        item: { $ref: '#/definitions/property' },
    },
};

export const TOOL_VARIABLES_JSON_SCHEMA: JSONSchema7 = {
    type: 'array',
    items: { $ref: '#/definitions/variable' },
    definitions: { variable, property },
};

const TOP_LEVEL_KEYS = new Set(Object.keys(variable.properties ?? {}));
const PROPERTY_KEYS = new Set(Object.keys(property.properties ?? {}));
const VARIABLE_REQUIRED = variable.required ?? [];
const PROPERTY_REQUIRED = property.required ?? [];
const TYPE_ENUM = new Set<unknown>(TYPE_VALUES);
const INPUT_TYPE_ENUM = new Set<unknown>(INPUT_TYPE_VALUES);
const NAME_REGEX = new RegExp(NAME_PATTERN);

function isPlainObject(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isValidShape(node: unknown, allowedKeys: Set<string>, required: string[], isTopLevel: boolean): boolean {
    if (!isPlainObject(node)) return false;

    for (const key of Object.keys(node)) {
        if (!allowedKeys.has(key)) return false;
    }
    for (const key of required) {
        if (!(key in node)) return false;
    }

    if (!TYPE_ENUM.has(node['type'])) return false;

    if (isTopLevel) {
        const name = node['name'];
        if (typeof name !== 'string' || name.length > NAME_MAX_LENGTH || !NAME_REGEX.test(name)) return false;
        if (!INPUT_TYPE_ENUM.has(node['input_type'])) return false;
        if ('required' in node && typeof node['required'] !== 'boolean') return false;
    }

    if ('description' in node) {
        const description = node['description'];
        if (typeof description !== 'string' || description.length > DESCRIPTION_MAX_LENGTH) return false;
    }

    if ('required_properties' in node) {
        const requiredProperties = node['required_properties'];
        if (!Array.isArray(requiredProperties) || !requiredProperties.every((x) => typeof x === 'string')) {
            return false;
        }
    }

    if ('properties' in node) {
        const properties = node['properties'];
        if (!isPlainObject(properties)) return false;
        for (const child of Object.values(properties)) {
            if (!isValidShape(child, PROPERTY_KEYS, PROPERTY_REQUIRED, false)) return false;
        }
    }

    if ('item' in node && !isValidShape(node['item'], PROPERTY_KEYS, PROPERTY_REQUIRED, false)) {
        return false;
    }

    if (node['type'] === 'object' && isPlainObject(node['default_value'])) {
        const props = isPlainObject(node['properties']) ? node['properties'] : {};
        for (const key of Object.keys(node['default_value'])) {
            if (!(key in props)) return false;
        }
    }

    return true;
}

export function isToolJsonSchemaValid(json: string): boolean {
    let parsed: unknown;
    try {
        parsed = JSON.parse(json);
    } catch {
        return false;
    }
    if (!Array.isArray(parsed)) return false;
    return parsed.every((item) => isValidShape(item, TOP_LEVEL_KEYS, VARIABLE_REQUIRED, true));
}

export interface JsonRangeMarker {
    message: string;
    startOffset: number;
    endOffset: number;
}

function collectOrphanDefaultKeys(node: unknown): string[] {
    if (!isPlainObject(node)) return [];
    const orphans: string[] = [];

    if (node['type'] === 'object' && isPlainObject(node['default_value'])) {
        const props = isPlainObject(node['properties']) ? node['properties'] : {};
        for (const key of Object.keys(node['default_value'])) {
            if (!(key in props)) orphans.push(key);
        }
    }

    if (isPlainObject(node['properties'])) {
        for (const child of Object.values(node['properties'])) {
            orphans.push(...collectOrphanDefaultKeys(child));
        }
    }
    if ('item' in node) {
        orphans.push(...collectOrphanDefaultKeys(node['item']));
    }

    return orphans;
}

function scanTopLevelItemSpans(raw: string): { start: number; end: number }[] {
    const spans: { start: number; end: number }[] = [];
    let i = 0;
    while (i < raw.length && raw[i] !== '[') i++;
    if (i >= raw.length) return spans;
    i++;

    let depth = 0;
    let inString = false;
    let escaped = false;
    let itemStart = -1;

    for (; i < raw.length; i++) {
        const c = raw[i];
        if (inString) {
            if (escaped) escaped = false;
            else if (c === '\\') escaped = true;
            else if (c === '"') inString = false;
            continue;
        }
        if (c === '"') {
            if (depth === 0 && itemStart === -1) itemStart = i;
            inString = true;
            continue;
        }
        if (c === '{' || c === '[') {
            if (depth === 0 && itemStart === -1) itemStart = i;
            depth++;
            continue;
        }
        if (c === '}' || c === ']') {
            if (depth === 0) {
                if (itemStart !== -1) spans.push({ start: itemStart, end: i });
                break;
            }
            depth--;
            if (depth === 0) {
                spans.push({ start: itemStart, end: i + 1 });
                itemStart = -1;
            }
            continue;
        }
        if (depth === 0) {
            if (c === ',') {
                if (itemStart !== -1) {
                    spans.push({ start: itemStart, end: i });
                    itemStart = -1;
                }
            } else if (!/\s/.test(c) && itemStart === -1) {
                itemStart = i;
            }
        }
    }

    return spans;
}

export function objectDefaultDataMarkers(json: string): JsonRangeMarker[] {
    let parsed: unknown;
    try {
        parsed = JSON.parse(json);
    } catch {
        return [];
    }
    if (!Array.isArray(parsed)) return [];

    const spans = scanTopLevelItemSpans(json);
    const markers: JsonRangeMarker[] = [];

    parsed.forEach((item, index) => {
        const orphans = collectOrphanDefaultKeys(item);
        const span = spans[index];
        if (orphans.length && span) {
            const keys = orphans.map((k) => `"${k}"`).join(', ');
            markers.push({
                message: `default_value has key(s) not declared in properties: ${keys}. These are lost when switching to table mode.`,
                startOffset: span.start,
                endOffset: span.end,
            });
        }
    });

    return markers;
}
