import { TableColumnDef } from '../../../../../shared/components/dynamic-table/dynamic-table.models';

export type VariableInputType = 'user_input' | 'agent_input' | 'mixed';

export type ToolVariableType = 'string' | 'number' | 'integer' | 'boolean' | 'any' | 'object' | 'array';

export interface VariableSectionConfig {
    inputType: VariableInputType;
    label: string;
    icon: string;
    columnDefs: TableColumnDef[];
}

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

// Backend payload schema (per EST-1529 spec): object/array variables carry their
// nested shape under `properties`/`required_properties` (object) or `item` (array).
export interface PropertySchema {
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

export const NAME_MAX_LENGTH = 64;
export const DESCRIPTION_MAX_LENGTH = 8046;
export const PYTHON_IDENTIFIER_PATTERN = /^[a-zA-Z]\w*$/;

export const VALID_INPUT_TYPES: VariableInputType[] = ['user_input', 'agent_input', 'mixed'];

export const TYPE_ALIASES: Record<string, ToolVariableType> = {
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

export const ARRAY_ITEM_SCHEMA: PropertySchema = { type: 'any' };

export function normalizeType(raw: unknown): ToolVariableType {
    if (Array.isArray(raw)) return 'any';
    if (typeof raw !== 'string') return 'any';
    return TYPE_ALIASES[raw.toLowerCase()] ?? 'any';
}

export function isObjectRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function isValidInputType(value: unknown): value is VariableInputType {
    return typeof value === 'string' && VALID_INPUT_TYPES.includes(value as VariableInputType);
}
