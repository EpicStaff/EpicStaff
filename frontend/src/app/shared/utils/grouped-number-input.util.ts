const GROUP_SEPARATOR = ' ';
const NUMBER_CHAR = /[\d.-]/;

export function formatGroupedNumber(text: string): string {
    return text.replace(/^-?\d+/, (integer) => integer.replace(/\B(?=(\d{3})+$)/g, GROUP_SEPARATOR));
}

export function formatGroupedValue(value: number | null | undefined): string {
    return value === null || value === undefined ? '' : formatGroupedNumber(String(value));
}

export function parseGroupedNumber(text: string): number | null {
    const plain = text.replace(/\s/g, '');
    if (['', '-', '.', '-.'].includes(plain)) return null;
    const parsed = Number(plain);
    return Number.isNaN(parsed) ? null : parsed;
}

export function setGroupedInputText(input: HTMLInputElement, text: string): void {
    if (input.value === text) return;
    const caret = input.selectionStart ?? input.value.length;
    const charsBefore = [...input.value.slice(0, caret)].filter((char) => NUMBER_CHAR.test(char)).length;
    input.value = text;
    if (input.ownerDocument.activeElement !== input) return;

    let position = 0;
    for (let kept = 0; position < text.length && kept < charsBefore; position++) {
        if (NUMBER_CHAR.test(text[position])) kept++;
    }
    input.setSelectionRange(position, position);
}

export function skipGroupSeparator(event: KeyboardEvent): void {
    const input = event.target as HTMLInputElement;
    const start = input.selectionStart;
    if (start === null || start !== input.selectionEnd) return;
    if (event.key === 'Backspace' && /\s/.test(input.value[start - 1] ?? '')) {
        input.setSelectionRange(start - 1, start - 1);
    }
    if (event.key === 'Delete' && /\s/.test(input.value[start] ?? '')) {
        input.setSelectionRange(start + 1, start + 1);
    }
}
