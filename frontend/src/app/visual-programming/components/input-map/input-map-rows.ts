/** One row of an Input List: an input name and the variable path it reads, such as `variables.topic|default`. */
export interface InputMapRow {
    key: string | null;
    value: string | null;
}

/**
 * Whether `value` holds no variable path: it is empty before any `|default`. The `variables.` a new row starts with is a
 * path: it maps all fields, the whole `variables` root.
 */
function hasNoVariablePath(value: string | null): boolean {
    return (value ?? '').split('|', 1)[0].trim() === '';
}

/** A named row with no variable path: the author has yet to choose the path, or to remove the row. */
export function isUnfinishedInputMapRow(row: InputMapRow): boolean {
    return !!row.key?.trim() && hasNoVariablePath(row.value);
}

/**
 * The input map an Input List's rows save as. A row without a name maps nothing and is left out. A named row is kept
 * as it is, also without a variable path: the author named the input on purpose, and the Input List asks for the path.
 */
export function inputMapFromRows(rows: readonly InputMapRow[]): Record<string, string> {
    const inputMap: Record<string, string> = {};
    for (const row of rows) {
        const key = row.key?.trim();
        if (key) inputMap[key] = row.value ?? '';
    }
    return inputMap;
}
