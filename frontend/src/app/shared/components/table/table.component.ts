import { NgTemplateOutlet } from '@angular/common';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    contentChildren,
    effect,
    input,
    output,
    signal,
    untracked,
} from '@angular/core';
import { MatTooltip } from '@angular/material/tooltip';

import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';
import { CheckboxComponent } from '../checkbox/checkbox.component';
import { MultiSelectComponent } from '../multi-select/multi-select.component';
import { MultiSelectTriggerDirective } from '../multi-select/multi-select-trigger.directive';
import { SelectComponent } from '../select/select.component';
import { SelectTriggerDirective } from '../select/select-trigger.directive';
import { AppTableActionVariant, AppTableColumnDef, AppTableRowAction, TableRow } from './table.model';
import { AppTableCellDirective } from './table-cell.directive';

@Component({
    selector: 'app-table',
    templateUrl: './table.component.html',
    styleUrls: ['./table.component.scss'],
    imports: [
        NgTemplateOutlet,
        CheckboxComponent,
        MultiSelectComponent,
        MultiSelectTriggerDirective,
        SelectComponent,
        SelectTriggerDirective,
        AppSvgIconComponent,
        MatTooltip,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AppTableComponent {
    columns = input.required<AppTableColumnDef[]>();
    data = input<TableRow[]>([]);
    /** Property name in data items to use as unique row ID */
    rowId = input<string>('id');
    /** Show checkbox column for multi-selection */
    selectable = input<boolean>(false);
    /** Row IDs to pre-select on init */
    initialSelectedIds = input<unknown[]>([]);
    /**
     * Tell the table that an external filter/search (managed by the consumer outside
     * the header) is currently active. Combined with the table's own header filters,
     * this decides whether an empty `data` should render as the "no results" state
     * (header preserved so the user can clear the filter) or the full-empty
     * `[tableEmpty]` slot (no data has ever existed).
     */
    hasExternalFilter = input<boolean>(false);

    selectionChange = output<TableRow[]>();
    filterChange = output<{ key: string; values: unknown[] }>();
    rowClick = output<TableRow>();

    readonly cellTemplates = contentChildren(AppTableCellDirective);

    private readonly selectedIds = signal<Set<unknown>>(new Set());
    private readonly activeFilters = signal<Record<string, unknown[]>>({});

    constructor() {
        effect(() => {
            const currentIds = this.selectedIds();
            if (!currentIds.size) return;
            const validIds = new Set(this.data().map((item) => this.getRowId(item)));
            const pruned = new Set([...currentIds].filter((id) => validIds.has(id)));
            if (pruned.size !== currentIds.size) {
                untracked(() => {
                    this.selectedIds.set(pruned);
                    this.selectionChange.emit(this.selectedItems());
                });
            }
        });

        effect(() => {
            const ids = this.initialSelectedIds();
            if (!ids.length) return;
            this.selectedIds.set(new Set(ids));
            untracked(() => this.selectionChange.emit(this.selectedItems()));
        });
    }

    /** True when any filter (header dropdown or external search) is currently applied. */
    readonly hasAnyFilter = computed<boolean>(() => {
        if (this.hasExternalFilter()) return true;
        return Object.values(this.activeFilters()).some((v) => v.length > 0);
    });

    readonly filteredData = computed<TableRow[]>(() => {
        const filters = this.activeFilters();
        const data = this.data();
        const serverSideKeys = new Set(
            this.columns()
                .filter((c) => c.filterServerSide)
                .map((c) => c.key)
        );
        const activeEntries = Object.entries(filters).filter(([key, v]) => v.length > 0 && !serverSideKeys.has(key));
        if (!activeEntries.length) return data;
        return data.filter((row) =>
            activeEntries.every(([key, values]) => {
                const rowVal = row[key];
                if (Array.isArray(rowVal)) {
                    return values.some((v) => (rowVal as unknown[]).includes(v));
                }
                return values.includes(rowVal);
            })
        );
    });

    readonly allSelected = computed(() => {
        const data = this.filteredData();
        if (!data.length) return false;
        const ids = this.selectedIds();
        return data.every((item) => ids.has(this.getRowId(item)));
    });

    readonly indeterminate = computed(() => {
        const ids = this.selectedIds();
        const data = this.filteredData();
        const count = data.filter((item) => ids.has(this.getRowId(item))).length;
        return count > 0 && count < data.length;
    });

    readonly selectedItems = computed<TableRow[]>(() => {
        const ids = this.selectedIds();
        return this.data().filter((item) => ids.has(this.getRowId(item)));
    });

    readonly gridTemplateColumns = computed<string>(() => {
        const cols: string[] = [];
        if (this.selectable()) cols.push('2rem');
        for (const col of this.columns()) {
            cols.push(col.width ?? '1fr');
        }
        return cols.join(' ');
    });

    getRowId(item: TableRow): unknown {
        return item[this.rowId()];
    }

    isSelected(item: TableRow): boolean {
        return this.selectedIds().has(this.getRowId(item));
    }

    toggleAll(): void {
        if (this.allSelected()) {
            this.selectedIds.set(new Set());
        } else {
            this.selectedIds.set(new Set(this.filteredData().map((item) => this.getRowId(item))));
        }
        this.selectionChange.emit(this.selectedItems());
    }

    toggleRow(item: TableRow): void {
        const ids = new Set(this.selectedIds());
        const id = this.getRowId(item);
        if (ids.has(id)) {
            ids.delete(id);
        } else {
            ids.add(id);
        }
        this.selectedIds.set(ids);
        this.selectionChange.emit(this.selectedItems());
    }

    getCellTemplate(key: string) {
        return this.cellTemplates().find((t) => t.appTableCell() === key)?.template ?? null;
    }

    onRowClick(item: TableRow): void {
        if (this.selectable()) {
            this.toggleRow(item);
        }

        this.rowClick.emit(item);
    }

    onFilterChange(key: string, values: unknown[]): void {
        this.activeFilters.update((f) => ({ ...f, [key]: values }));
        this.filterChange.emit({ key, values });
    }

    onSingleFilterChange(key: string, value: unknown): void {
        const values = value === null || value === undefined ? [] : [value];
        this.onFilterChange(key, values);
    }

    firstSingleFilterValue(key: string): unknown {
        const values = this.activeFilters()[key];
        return values && values.length > 0 ? values[0] : null;
    }

    resolveActionVariant(action: AppTableRowAction, row: TableRow): AppTableActionVariant {
        const variant = action.variant;
        if (typeof variant === 'function') return variant(row);
        return variant ?? 'default';
    }
}
