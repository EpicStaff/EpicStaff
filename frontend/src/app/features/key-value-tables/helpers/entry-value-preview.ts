import { KeyValueTableEntryListItem } from '../models/key-value-table.model';

// Value cell text: the server's preview, with an ellipsis when the value goes on past it.
export function previewText(entry: KeyValueTableEntryListItem): string {
    return entry.value_truncated ? `${entry.value_preview}…` : entry.value_preview;
}

// Editor text for a value: JSON indented by two spaces; parsed back with JSON.parse on commit.
export function editableValue(value: unknown): string {
    return JSON.stringify(value, null, 2) ?? 'null';
}

// Clipboard text for a value: a string as its raw text (no JSON quotes), anything else as JSON indented like the editor.
export function copyableValue(value: unknown): string {
    return typeof value === 'string' ? value : editableValue(value);
}
