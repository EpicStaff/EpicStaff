import { ValidatorFn, Validators } from '@angular/forms';

import { TableRow } from '../../../../../shared/components/dynamic-table/dynamic-table.models';
import {
    DESCRIPTION_MAX_LENGTH,
    NAME_MAX_LENGTH,
    PYTHON_IDENTIFIER_PATTERN,
    ToolVariable,
    VariableInputType,
} from './tool-variable.model';

export const integerValueValidator: ValidatorFn = (control) => {
    const v = control.value;
    if (v === '' || v == null) return null;
    if (typeof v === 'number') return Number.isInteger(v) ? null : { invalidInteger: true };
    const s = String(v).trim();
    if (s === '') return null;
    return /^-?\d+$/.test(s) ? null : { invalidInteger: true };
};

export const numberValueValidator: ValidatorFn = (control) => {
    const v = control.value;
    if (v === '' || v == null) return null;
    if (typeof v === 'number') return Number.isFinite(v) ? null : { invalidNumber: true };
    const s = String(v).trim();
    if (s === '') return null;
    return /^-?(\d+(\.\d+)?|\.\d+)$/.test(s) ? null : { invalidNumber: true };
};

export const booleanValueValidator: ValidatorFn = (control) => {
    const v = control.value;
    if (v === '' || v == null) return null;
    if (typeof v === 'boolean') return null;
    const s = String(v).trim().toLowerCase();
    if (s === '') return null;
    return s === 'true' || s === 'false' ? null : { invalidBoolean: true };
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
