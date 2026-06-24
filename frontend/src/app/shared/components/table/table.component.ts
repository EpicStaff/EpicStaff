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

import { CheckboxComponent } from '../checkbox/checkbox.component';
import { MultiSelectComponent } from '../multi-select/multi-select.component';
import { AppTableColumnDef, TableRow } from './table.model';
import { AppTableCellDirective } from './table-cell.directive';

@Component({
    selector: 'app-table',
    templateUrl: './table.component.html',
    styleUrls: ['./table.component.scss'],
    imports: [NgTemplateOutlet, CheckboxComponent, MultiSelectComponent],
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

    selectionChange = output<TableRow[]>();
    filterChange = output<{ key: string; values: string[] }>();
    rowClick = output<TableRow>();

    readonly cellTemplates = contentChildren(AppTableCellDirective);

    private readonly selectedIds = signal<Set<unknown>>(new Set());
    private readonly activeFilters = signal<Record<string, unknown[]>>({});

    constructor() {
        effect(() => {
            const ids = this.initialSelectedIds();
            if (!ids.length) return;
            this.selectedIds.set(new Set(ids));
            untracked(() => this.selectionChange.emit(this.selectedItems()));
        });
    }

    readonly filteredData = computed<TableRow[]>(() => {
        const filters = this.activeFilters();
        const data = this.data();
        const activeEntries = Object.entries(filters).filter(([, v]) => v.length > 0);
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
        this.filterChange.emit({
            key,
            values: values.filter((v): v is string => typeof v === 'string'),
        });
    }
}
