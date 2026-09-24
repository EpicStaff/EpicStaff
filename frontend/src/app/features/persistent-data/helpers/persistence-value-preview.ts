export function previewValue(value: unknown, maxLength = 120): string {
    const text = JSON.stringify(value) ?? 'null';
    return text.length > maxLength ? `${text.slice(0, maxLength - 1)}…` : text;
}
