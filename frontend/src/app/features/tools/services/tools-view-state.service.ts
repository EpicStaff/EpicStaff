import { computed, Injectable, signal } from '@angular/core';
import { IncludeExcludeTab } from '@shared/components';
import { Subject } from 'rxjs';

import { EMPTY_TOOLS_FILTER, ToolsFilterState, USAGE_DEPENDENT_SORTS } from '../models/tool-filter.model';

export type ToolsBulkActionKind =
    | 'select-all'
    | 'delete-unused'
    | 'favorite'
    | 'duplicate'
    | 'delete-selected'
    | 'add-labels'
    | 'open-include-exclude'
    | 'export-selected'
    | 'open-import';

export interface ToolsBulkActionEvent {
    kind: ToolsBulkActionKind;
    labelIds?: number[];
    initialTab?: IncludeExcludeTab;
}

/**
 * Shared UI state for the tools list page:
 *  - selection set (shared across Custom / MCP tabs, cleared on tab switch),
 *  - the "Show usage & unused" toggle,
 *  - the filter menu / include-exclude / custom-filter state,
 *  - a bulk-action bus so the currently mounted list component executes the
 *    action against its own data + service.
 */
@Injectable({ providedIn: 'root' })
export class ToolsViewStateService {
    private readonly _selectedIds = signal<Set<number>>(new Set());

    public readonly selectedIds = this._selectedIds.asReadonly();
    public readonly selectedCount = computed(() => this._selectedIds().size);
    public readonly hasSelection = computed(() => this._selectedIds().size > 0);

    public readonly showUsageAndUnused = signal<boolean>(false);

    private readonly _filter = signal<ToolsFilterState>({ ...EMPTY_TOOLS_FILTER });
    public readonly filter = this._filter.asReadonly();
    public readonly hasActiveFilter = computed(() => {
        const f = this._filter();
        return (
            f.showFavoriteOnly ||
            f.sortOrder !== 'default' ||
            f.includedToolIds !== null ||
            f.includedLabelIds !== null ||
            f.customFilter !== null
        );
    });
    /** True when the current sort order requires usage counts to render. */
    public readonly needsUsageData = computed(
        () => this.showUsageAndUnused() || USAGE_DEPENDENT_SORTS.includes(this._filter().sortOrder)
    );

    public readonly action$ = new Subject<ToolsBulkActionEvent>();

    public isSelected(id: number): boolean {
        return this._selectedIds().has(id);
    }

    public setSelected(id: number, on: boolean): void {
        const next = new Set(this._selectedIds());
        if (on) next.add(id);
        else next.delete(id);
        this._selectedIds.set(next);
    }

    public selectMany(ids: number[]): void {
        const next = new Set(this._selectedIds());
        for (const id of ids) next.add(id);
        this._selectedIds.set(next);
    }

    public clear(): void {
        if (this._selectedIds().size === 0) return;
        this._selectedIds.set(new Set());
    }

    public dispatch(event: ToolsBulkActionEvent): void {
        this.action$.next(event);
    }

    public patchFilter(patch: Partial<ToolsFilterState>): void {
        this._filter.update((current) => ({ ...current, ...patch }));
    }

    public resetFilter(): void {
        this._filter.set({ ...EMPTY_TOOLS_FILTER });
    }
}
