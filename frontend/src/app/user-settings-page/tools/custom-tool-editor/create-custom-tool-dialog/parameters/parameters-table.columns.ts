import { Validators } from '@angular/forms';

import { TableColumnDef } from '../../../../../shared/components/dynamic-table/dynamic-table.models';
import {
    DESCRIPTION_MAX_LENGTH,
    NAME_MAX_LENGTH,
    PYTHON_IDENTIFIER_PATTERN,
    VariableSectionConfig,
} from './tool-variable.model';

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

const INDEX_COLUMN: TableColumnDef = {
    key: 'name',
    header: '#',
    type: 'input',
    width: '64px',
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

export function arrayItemColumnDefs(base: readonly TableColumnDef[]): TableColumnDef[] {
    return base.filter((col) => col.key !== 'required');
}

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
