/**
 * Puts `text` over the `start`..`end` selection of `value`. Drops the text's leading space at the start of the
 * query or after a space, and its trailing space before a space, so operators never leave double spaces.
 */
export function insertQueryText(
    value: string,
    start: number,
    end: number,
    text: string,
    caretFromEnd = 0
): { query: string; caret: number } {
    const before = value.slice(0, start);
    const after = value.slice(end);
    let inserted = text;
    if (inserted.startsWith(' ') && (before === '' || before.endsWith(' '))) inserted = inserted.slice(1);
    if (inserted.endsWith(' ') && after.startsWith(' ')) inserted = inserted.slice(0, -1);
    return { query: before + inserted + after, caret: start + inserted.length - caretFromEnd };
}
