import { ValidatorFn } from '@angular/forms';

export interface TableSelectOption {
    label: string;
    value: unknown;
}

export interface TableColumnDef {
    key: string; // field key in row data
    header: string; // column header label
    type: 'input' | 'select' | 'checkbox';
    width?: string; // optional CSS width (e.g. '160px')
    placeholder?: string; // for input/select cells
    options?: TableSelectOption[]; // only for type='select'
    defaultValue?: unknown; // value used when a new row is added
    required?: boolean; // shows an asterisk in the header
    unique?: boolean; // values must be unique across rows in this table
    uniqueErrorMessage?: string; // human message used when a duplicate is detected
    validators?: ValidatorFn[];
    errorMessages?: Record<string, string>; // key -> human message override
}

export interface TableRow {
    _id: string;
    data: Record<string, unknown>;
}
