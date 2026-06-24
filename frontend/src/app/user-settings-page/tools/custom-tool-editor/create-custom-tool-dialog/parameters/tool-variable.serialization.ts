import {
    ARRAY_ITEM_SCHEMA,
    BackendToolVariable,
    isObjectRecord,
    isValidInputType,
    ItemsSchema,
    normalizeType,
    PropertySchema,
    ToolVariable,
    ToolVariableType,
    VariableInputType,
} from './tool-variable.model';

export function variableToRowData(v: ToolVariable): Record<string, unknown> {
    return {
        name: v.name,
        type: v.type,
        description: v.description,
        default_value:
            v.type === 'object' || v.default_value === null || v.default_value === undefined
                ? ''
                : String(v.default_value),
        required: v.required,
        children: Array.isArray(v.children) ? v.children : [],
        items: v.items,
    };
}

function parseDefaultValue(raw: unknown, type: ToolVariableType): unknown {
    if (raw === '' || raw == null) return null;

    if (type === 'integer') {
        const s = typeof raw === 'string' ? raw.trim() : String(raw);
        if (s === '') return null;
        if (!/^-?\d+$/.test(s)) return null;
        const n = Number(s);
        return Number.isFinite(n) ? n : null;
    }
    if (type === 'number') {
        const n = typeof raw === 'number' ? raw : Number(String(raw).trim());
        return Number.isFinite(n) ? n : null;
    }
    if (type === 'boolean') {
        if (typeof raw === 'boolean') return raw;
        const s = String(raw).trim().toLowerCase();
        if (s === 'true') return true;
        if (s === 'false') return false;
        return null;
    }
    if (type === 'object' || type === 'array') return null;
    if (type === 'any') return raw;
    return String(raw);
}

export function rowDataToVariable(data: Record<string, unknown>, inputType: VariableInputType): ToolVariable {
    const type = normalizeType(data['type']);

    const rawChildren = data['children'];
    const children = Array.isArray(rawChildren) ? (rawChildren as ToolVariable[]) : [];

    const result: ToolVariable = {
        name: String(data['name'] ?? ''),
        type,
        description: String(data['description'] ?? ''),
        input_type: inputType,
        required: Boolean(data['required']),
        default_value: parseDefaultValue(data['default_value'], type),
    };

    if (type === 'object' || type === 'array') result.children = children;

    return result;
}

function inferValueType(value: unknown): ToolVariableType {
    if (typeof value === 'boolean') return 'boolean';
    if (typeof value === 'number') return 'number';
    if (typeof value === 'string') return 'string';
    if (Array.isArray(value)) return 'array';
    if (value !== null && typeof value === 'object') return 'object';
    return 'any';
}

function valueToVariable(name: string, value: unknown, inputType: VariableInputType): ToolVariable {
    const type = inferValueType(value);
    const variable: ToolVariable = {
        name,
        type,
        description: '',
        input_type: inputType,
        required: false,
        default_value: type === 'object' || type === 'array' ? null : value,
    };
    if (type === 'object') {
        variable.children = Object.entries(value as Record<string, unknown>).map(([k, v]) =>
            valueToVariable(k, v, inputType)
        );
    }
    if (type === 'array') {
        variable.children = (value as unknown[]).map((v, i) => valueToVariable(String(i), v, inputType));
    }
    return variable;
}

export function arrayDefaultToVariables(value: unknown, inputType: VariableInputType): ToolVariable[] {
    if (!Array.isArray(value)) return [];
    return value.map((el, i) => valueToVariable(String(i), el, inputType));
}

function buildValue(variable: ToolVariable): unknown {
    if (variable.type === 'object') {
        const obj: Record<string, unknown> = {};
        for (const child of variable.children ?? []) {
            const name = child.name?.trim();
            if (!name) continue;
            obj[name] = buildValue(child);
        }
        return obj;
    }
    if (variable.type === 'array') {
        return (variable.children ?? []).map(buildValue);
    }
    return variable.default_value ?? null;
}

function childrenToProperties(children: ToolVariable[]): {
    properties: Record<string, PropertySchema>;
    required_properties: string[];
} {
    const properties: Record<string, PropertySchema> = {};
    const required_properties: string[] = [];

    for (const child of children) {
        const name = child.name?.trim();
        if (!name) continue;

        const schema: PropertySchema = { type: child.type };
        if (child.description) {
            schema.description = child.description;
        }
        if (child.type === 'object') {
            const nested = childrenToProperties(child.children ?? []);
            schema.properties = nested.properties;
            schema.required_properties = nested.required_properties;
            schema.default_value = buildValue(child);
        } else if (child.type === 'array') {
            schema.item = { ...ARRAY_ITEM_SCHEMA };
            schema.default_value = buildValue(child);
        } else if (child.default_value !== null && child.default_value !== undefined) {
            schema.default_value = child.default_value;
        }

        properties[name] = schema;
        if (child.required) {
            required_properties.push(name);
        }
    }

    return { properties, required_properties };
}

export function serializeVariables(vars: ToolVariable[]): BackendToolVariable[] {
    return vars.map((v) => {
        const out: BackendToolVariable = {
            name: v.name,
            type: v.type,
            description: v.description,
            input_type: v.input_type,
            required: v.required,
            default_value: v.default_value,
        };

        if (v.type === 'object') {
            out.default_value = buildValue(v);
            const nested = childrenToProperties(v.children ?? []);
            out.properties = nested.properties;
            out.required_properties = nested.required_properties;
        }
        if (v.type === 'array') {
            out.item = v.items ? (v.items as unknown as PropertySchema) : { ...ARRAY_ITEM_SCHEMA };
            out.default_value = buildValue(v);
        }

        return out;
    });
}

function propertiesToChildren(
    properties: unknown,
    requiredProperties: unknown,
    inputType: VariableInputType
): ToolVariable[] {
    if (!isObjectRecord(properties)) return [];
    const requiredSet = new Set(
        Array.isArray(requiredProperties) ? requiredProperties.filter((n) => typeof n === 'string') : []
    );

    const result: ToolVariable[] = [];
    for (const [name, raw] of Object.entries(properties)) {
        if (!isObjectRecord(raw)) continue;
        const type = normalizeType(raw['type']);

        const variable: ToolVariable = {
            name,
            type,
            description: typeof raw['description'] === 'string' ? raw['description'] : '',
            input_type: inputType,
            required: requiredSet.has(name),
            default_value: raw['default_value'] ?? null,
        };

        if (type === 'object') {
            variable.children = propertiesToChildren(raw['properties'], raw['required_properties'], inputType);
        }
        if (type === 'array') {
            variable.children = arrayDefaultToVariables(raw['default_value'], inputType);
            variable.default_value = null;
        }

        result.push(variable);
    }

    return result;
}

function isBackendVariable(value: unknown): value is BackendToolVariable {
    if (!isObjectRecord(value)) return false;
    if (
        typeof value['name'] !== 'string' ||
        typeof value['description'] !== 'string' ||
        typeof value['required'] !== 'boolean' ||
        !isValidInputType(value['input_type'])
    ) {
        return false;
    }
    return true;
}

export function deserializeVariables(data: unknown): ToolVariable[] {
    if (!Array.isArray(data)) return [];

    const result: ToolVariable[] = [];
    for (const item of data) {
        if (!isBackendVariable(item)) continue;

        const type = normalizeType((item as { type?: unknown }).type);

        const variable: ToolVariable = {
            name: item.name,
            type,
            description: item.description,
            input_type: item.input_type,
            required: item.required,
            default_value: item.default_value ?? null,
        };

        if (type === 'object') {
            variable.children = propertiesToChildren(item.properties, item.required_properties, item.input_type);
        }
        if (type === 'array') {
            variable.children = arrayDefaultToVariables(item.default_value, item.input_type);
            variable.default_value = null;
            if (isObjectRecord(item.item)) {
                variable.items = item.item as unknown as ItemsSchema;
            }
        }

        result.push(variable);
    }

    return result;
}

export function parseToolVariablesJson(json: string): { valid: boolean; variables: ToolVariable[] } {
    try {
        const parsed = JSON.parse(json);
        if (!Array.isArray(parsed)) {
            return { valid: false, variables: [] };
        }
        return { valid: true, variables: deserializeVariables(parsed) };
    } catch {
        return { valid: false, variables: [] };
    }
}
