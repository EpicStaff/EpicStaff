export function computeUniqueName(base: string, existingNames: string[]): string {
    const nameSet = new Set(existingNames);
    const root = base.replace(/ \(\d+\)$/, '');
    if (!nameSet.has(root)) return root;
    let n = 2;
    while (nameSet.has(`${root} (${n})`)) n++;
    return `${root} (${n})`;
}

/** `{base} copy`, then `{base} copy(1)`, `{base} copy(2)`, … */
export function computeUniqueCopyName(base: string, existingNames: readonly string[]): string {
    const nameSet = new Set(existingNames);
    const first = `${base} copy`;
    if (!nameSet.has(first)) return first;
    let n = 1;
    while (nameSet.has(`${base} copy(${n})`)) n++;
    return `${base} copy(${n})`;
}
