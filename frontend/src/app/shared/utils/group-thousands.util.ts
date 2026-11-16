export function groupThousands(value: number | string | null): string | null {
    const text = String(value ?? '');
    if (!/^-?\d{4,}(\.\d+)?$/.test(text)) return null;
    return text.replace(/^-?\d+/, (integer) => integer.replace(/\B(?=(\d{3})+$)/g, '\u202F'));
}
