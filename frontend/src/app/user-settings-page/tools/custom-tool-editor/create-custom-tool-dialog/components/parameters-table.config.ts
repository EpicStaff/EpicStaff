import { ValidatorFn, Validators } from '@angular/forms';

import { TableColumnDef, TableRow } from '../../../../../shared/components/dynamic-table/dynamic-table.models';

export type VariableInputType = 'user_input' | 'agent_input' | 'mixed';

export type ToolVariableType = 'string' | 'number' | 'integer' | 'boolean' | 'any' | 'object' | 'array';

export interface VariableSectionConfig {
    inputType: VariableInputType;
    label: string;
    icon: string;
    columnDefs: TableColumnDef[];
}

const NAME_MAX_LENGTH = 64;
const DESCRIPTION_MAX_LENGTH = 8046;
const PYTHON_IDENTIFIER_PATTERN = /^[a-zA-Z]\w*$/;

const NAME_VALIDATORS = [
    Validators.required,
    Validators.maxLength(NAME_MAX_LENGTH),
    Validators.pattern(PYTHON_IDENTIFIER_PATTERN),
];
const NAME_ERROR_MESSAGES = {
    required: 'Name is required.',
    maxlength: `Name must be ${NAME_MAX_LENGTH} characters or fewer.`,
    pattern: 'Name must start with a letter and contain only letters, digits, or underscores.',
};

const DESCRIPTION_VALIDATORS = [Validators.maxLength(DESCRIPTION_MAX_LENGTH)];
const DESCRIPTION_ERROR_MESSAGES = {
    maxlength: `Description must be ${DESCRIPTION_MAX_LENGTH} characters or fewer.`,
};

const TYPE_OPTIONS = [
    { label: 'string', value: 'string' },
    { label: 'integer', value: 'integer' },
    { label: 'number', value: 'number' },
    { label: 'boolean', value: 'boolean' },
    { label: 'object', value: 'object' },
    { label: 'array', value: 'array' },
];

const TYPE_ALIASES: Record<string, ToolVariableType> = {
    string: 'string',
    number: 'number',
    integer: 'integer',
    int: 'integer',
    boolean: 'boolean',
    bool: 'boolean',
    object: 'object',
    obj: 'object',
    array: 'array',
    list: 'array',
    any: 'any',
};

function normalizeType(raw: unknown): ToolVariableType {
    if (Array.isArray(raw)) return 'any';
    if (typeof raw !== 'string') return 'any';
    return TYPE_ALIASES[raw.toLowerCase()] ?? 'any';
}

const integerValueValidator: ValidatorFn = (control) => {
    const v = control.value;
    if (v === '' || v == null) return null;
    if (typeof v === 'number') return Number.isInteger(v) ? null : { invalidInteger: true };
    const s = String(v).trim();
    if (s === '') return null;
    return /^-?\d+$/.test(s) ? null : { invalidInteger: true };
};

const numberValueValidator: ValidatorFn = (control) => {
    const v = control.value;
    if (v === '' || v == null) return null;
    if (typeof v === 'number') return Number.isFinite(v) ? null : { invalidNumber: true };
    const s = String(v).trim();
    if (s === '') return null;
    return /^-?(\d+(\.\d+)?|\.\d+)$/.test(s) ? null : { invalidNumber: true };
};

const booleanValueValidator: ValidatorFn = (control) => {
    const v = control.value;
    if (v === '' || v == null) return null;
    if (typeof v === 'boolean') return null;
    const s = String(v).trim().toLowerCase();
    if (s === '') return null;
    return s === 'true' || s === 'false' ? null : { invalidBoolean: true };
};

const DEFAULT_VALUE_ERROR_MESSAGES = {
    invalidNumber: 'Default value must be a valid number.',
    invalidInteger: 'Default value must be a whole number.',
    invalidBoolean: 'Default value must be "true" or "false".',
};

const USER_INPUT_VALUE_ERROR_MESSAGES = {
    ...DEFAULT_VALUE_ERROR_MESSAGES,
    required: 'Value is required.',
    objectChildrenRequired: 'Object must have at least one valid nested field.',
};

const objectChildrenRequiredValidator: ValidatorFn = () => ({ objectChildrenRequired: true });

function hasValidChild(children: ToolVariable[]): boolean {
    return children.some((c) => {
        if (!isVariableShallowValid(c)) return false;
        if (c.type === 'object') return hasValidChild(c.children ?? []);
        return true;
    });
}

export function createCellExtraValidators(
    inputType: VariableInputType
): (row: TableRow, colKey: string) => ValidatorFn[] {
    return (row: TableRow, colKey: string): ValidatorFn[] => {
        if (colKey !== 'default_value') return [];
        const type = row.data['type'];

        if (inputType === 'user_input') {
            if (type === 'object') {
                const children = (row.data['children'] as ToolVariable[]) ?? [];
                return hasValidChild(children) ? [] : [objectChildrenRequiredValidator];
            }
            switch (type) {
                case 'integer':
                    return [Validators.required, integerValueValidator];
                case 'number':
                    return [Validators.required, numberValueValidator];
                case 'boolean':
                    return [Validators.required, booleanValueValidator];
                default:
                    return [Validators.required];
            }
        }

        switch (type) {
            case 'integer':
                return [integerValueValidator];
            case 'number':
                return [numberValueValidator];
            case 'boolean':
                return [booleanValueValidator];
            default:
                return [];
        }
    };
}

const NAME_COLUMN: TableColumnDef = {
    key: 'name',
    header: 'Name',
    type: 'input',
    width: '140px',
    placeholder: 'variable_name',
    required: true,
    unique: true,
    uniqueErrorMessage: 'Variable names must be unique.',
    validators: NAME_VALIDATORS,
    errorMessages: NAME_ERROR_MESSAGES,
};

const TYPE_COLUMN: TableColumnDef = {
    key: 'type',
    header: 'Type',
    type: 'select',
    width: '120px',
    options: TYPE_OPTIONS,
    defaultValue: 'string',
};

const DESCRIPTION_COLUMN: TableColumnDef = {
    key: 'description',
    header: 'Description',
    type: 'input',
    width: '380px',
    placeholder: 'What this variable is for',
    validators: DESCRIPTION_VALIDATORS,
    errorMessages: DESCRIPTION_ERROR_MESSAGES,
};

export const USER_INPUT_COLUMN_DEFS = [
    NAME_COLUMN,
    TYPE_COLUMN,
    {
        key: 'default_value',
        header: 'Value',
        type: 'input',
        width: '260px',
        placeholder: '',
        required: true,
        errorMessages: USER_INPUT_VALUE_ERROR_MESSAGES,
    },
    DESCRIPTION_COLUMN,
] satisfies TableColumnDef[];

export const AGENT_INPUT_COLUMN_DEFS = [
    NAME_COLUMN,
    TYPE_COLUMN,
    {
        key: 'default_value',
        header: 'Default Value',
        type: 'input',
        width: '260px',
        placeholder: '',
        errorMessages: DEFAULT_VALUE_ERROR_MESSAGES,
    },
    DESCRIPTION_COLUMN,
    { key: 'required', header: 'Required', type: 'checkbox', width: '80px' },
] satisfies TableColumnDef[];

export const MIXED_COLUMN_DEFS = [
    NAME_COLUMN,
    TYPE_COLUMN,
    {
        key: 'default_value',
        header: 'Default Value',
        type: 'input',
        width: '260px',
        placeholder: '',
        errorMessages: DEFAULT_VALUE_ERROR_MESSAGES,
    },
    DESCRIPTION_COLUMN,
] satisfies TableColumnDef[];

export const VARIABLE_SECTIONS = [
    { inputType: 'user_input', label: 'User Input', icon: 'user', columnDefs: USER_INPUT_COLUMN_DEFS },
    { inputType: 'agent_input', label: 'Agent Input', icon: 'agent', columnDefs: AGENT_INPUT_COLUMN_DEFS },
    {
        inputType: 'mixed',
        label: 'User Input otherwise Input by Agent',
        icon: 'mixed-input',
        columnDefs: MIXED_COLUMN_DEFS,
    },
] as const satisfies readonly VariableSectionConfig[];

// Strip the `required` column for the single-row "array items" sub-view —
// an item schema has no required flag at the backend.
export function arrayItemColumnDefs(base: readonly TableColumnDef[]): TableColumnDef[] {
    return base.filter((col) => col.key !== 'required');
}

const INDEX_COLUMN: TableColumnDef = {
    key: 'name',
    header: '#',
    type: 'input',
    width: '64px',
};

export const VALUE_EDITOR_COLUMN_DEFS = [
    INDEX_COLUMN,
    TYPE_COLUMN,
    {
        key: 'default_value',
        header: 'Value',
        type: 'input',
        width: '320px',
        placeholder: '',
        errorMessages: DEFAULT_VALUE_ERROR_MESSAGES,
    },
] satisfies TableColumnDef[];

export interface ItemsSchema {
    type: ToolVariableType;
    description?: string;
    default_value?: unknown;
    children?: ToolVariable[];
    items?: ItemsSchema;
}

export interface ToolVariable {
    name: string;
    type: ToolVariableType;
    description: string;
    input_type: VariableInputType;
    required: boolean;
    default_value: unknown;
    children?: ToolVariable[];
    items?: ItemsSchema;
}

const VALID_INPUT_TYPES: VariableInputType[] = ['user_input', 'agent_input', 'mixed'];

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

function isObjectRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export const ARRAY_ITEM_SCHEMA: PropertySchema = { type: 'any' };

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

function isValidInputType(value: unknown): value is VariableInputType {
    return typeof value === 'string' && VALID_INPUT_TYPES.includes(value as VariableInputType);
}

// --- Backend payload schema (per EST-1529 spec) ---

interface PropertySchema {
    type: ToolVariableType;
    description?: string;
    default_value?: unknown;
    properties?: Record<string, PropertySchema>;
    required_properties?: string[];
    item?: PropertySchema;
}

export interface BackendToolVariable {
    name: string;
    type: ToolVariableType;
    description: string;
    input_type: VariableInputType;
    required: boolean;
    default_value: unknown;
    properties?: Record<string, PropertySchema>;
    required_properties?: string[];
    item?: PropertySchema;
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
            out.item = { ...ARRAY_ITEM_SCHEMA };
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

// Lenient: accept any object with valid identity fields. Unknown / malformed
// `type` values are coerced to 'any' by normalizeType — we never reject a row,
// otherwise the UI silently drops it and saving wipes the variables list.
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
        }

        result.push(variable);
    }

    return result;
}

function hasRequiredValue(v: ToolVariable): boolean {
    if (v.input_type === 'user_input' && v.type !== 'object' && v.type !== 'array') {
        if (v.default_value === null || v.default_value === undefined || v.default_value === '') {
            return false;
        }
    }
    return true;
}

function isVariableShallowValid(v: ToolVariable): boolean {
    const name = v.name?.trim();
    if (!name) return false;
    if (name.length > NAME_MAX_LENGTH) return false;
    if (!PYTHON_IDENTIFIER_PATTERN.test(name)) return false;

    if (typeof v.description === 'string' && v.description.length > DESCRIPTION_MAX_LENGTH) {
        return false;
    }

    return hasRequiredValue(v);
}

function isElementValid(v: ToolVariable): boolean {
    if (typeof v.description === 'string' && v.description.length > DESCRIPTION_MAX_LENGTH) {
        return false;
    }
    return hasRequiredValue(v);
}

// Walks the variable tree and validates each variable individually plus
// uniqueness of names within the same level (siblings). Used as the canonical
// pre-save check, since FormControls only exist for currently-visible cells.
export function validateVariablesTree(vars: ToolVariable[], asArrayElements = false): boolean {
    const names: string[] = [];
    for (const v of vars) {
        if (asArrayElements) {
            if (!isElementValid(v)) return false;
        } else {
            if (!isVariableShallowValid(v)) return false;
            names.push(v.name.trim());
            if (v.type === 'object' && v.input_type === 'user_input' && !hasValidChild(v.children ?? [])) {
                return false;
            }
        }
        if (v.type === 'object') {
            const children = Array.isArray(v.children) ? v.children : [];
            if (children.length > 0 && !validateVariablesTree(children)) return false;
        }
        if (v.type === 'array') {
            const children = Array.isArray(v.children) ? v.children : [];
            if (children.length > 0 && !validateVariablesTree(children, true)) return false;
        }
    }
    if (!asArrayElements && new Set(names).size !== names.length) return false;
    return true;
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
