export type AuditPresetSelectionState = 'none' | 'some' | 'all';

export function selectionState(selected: ReadonlySet<number>, listedIds: readonly number[]): AuditPresetSelectionState {
    const selectedCount = listedIds.filter((id) => selected.has(id)).length;
    if (selectedCount === 0) {
        return 'none';
    }
    return selectedCount === listedIds.length ? 'all' : 'some';
}

// Select-all acts on the listed presets only; a selection hidden by the search is left as it is.
export function toggleAll(selected: ReadonlySet<number>, listedIds: readonly number[]): ReadonlySet<number> {
    const next = new Set(selected);
    const select = selectionState(selected, listedIds) !== 'all';
    listedIds.forEach((id) => (select ? next.add(id) : next.delete(id)));
    return next;
}

export function toggleOne(selected: ReadonlySet<number>, id: number): ReadonlySet<number> {
    const next = new Set(selected);
    if (!next.delete(id)) {
        next.add(id);
    }
    return next;
}
