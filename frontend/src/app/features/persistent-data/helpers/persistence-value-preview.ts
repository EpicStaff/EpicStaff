export function previewValue(value: unknown, maxLength = 120): string {
    const text = JSON.stringify(value) ?? 'null';
    return text.length > maxLength ? `${text.slice(0, maxLength - 1)}…` : text;
}

// Clipboard text for a value: a string as its raw text (no JSON quotes), anything else as JSON indented like the editor.
export function copyableValue(value: unknown): string {
    return typeof value === 'string' ? value : (JSON.stringify(value, null, 2) ?? 'null');
}
