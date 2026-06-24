export function computeUniqueName(base: string, existingNames: string[]): string {
    const nameSet = new Set(existingNames);
    const root = base.replace(/ \(\d+\)$/, '');
    if (!nameSet.has(root)) return root;
    let n = 2;
    while (nameSet.has(`${root} (${n})`)) n++;
    return `${root} (${n})`;
}
