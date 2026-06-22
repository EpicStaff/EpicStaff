import { ChangeDetectionStrategy, Component, computed, input, signal } from '@angular/core';

import { EfTable, EfTableColumn } from '../../models/flow-assistant.model';

@Component({
    selector: 'app-flow-assistant-table',
    standalone: true,
    imports: [],
    templateUrl: './flow-assistant-table.component.html',
    styleUrls: ['./flow-assistant-table.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FlowAssistantTableComponent {
    // TODO (v2): editing, row selection, `unions` option, and `processTables` action wiring are out of scope.

    readonly table = input.required<EfTable>();

    readonly sortField = signal<string | null>(null);
    readonly sortDir = signal<'asc' | 'desc'>('asc');

    readonly resolvedColumns = computed<EfTableColumn[]>(() => {
        const tableData = this.table();
        if (tableData.columns && tableData.columns.length > 0) {
            return tableData.columns.filter((c) => c.visible !== false);
        }
        // Auto-detect columns from first row keys.
        const firstRow = tableData.rows[0];
        if (!firstRow) return [];
        return Object.keys(firstRow).map((key) => ({ key }));
    });

    readonly displayedRows = computed<Record<string, unknown>[]>(() => {
        const tableData = this.table();
        const rows = [...tableData.rows];
        const field = this.sortField() ?? tableData.defaultSortField ?? null;
        const isSortable = tableData.isSortable !== false;

        if (!field || !isSortable) return rows;

        const dir = this.sortDir();
        return rows.sort((a, b) => {
            const aVal = a[field];
            const bVal = b[field];
            if (aVal === bVal) return 0;
            if (aVal == null) return 1;
            if (bVal == null) return -1;
            const cmp = String(aVal).localeCompare(String(bVal), undefined, { numeric: true, sensitivity: 'base' });
            return dir === 'asc' ? cmp : -cmp;
        });
    });

    toggleSort(key: string): void {
        if (this.table().isSortable === false) return;
        if (this.sortField() === key) {
            this.sortDir.update((d) => (d === 'asc' ? 'desc' : 'asc'));
        } else {
            this.sortField.set(key);
            this.sortDir.set('asc');
        }
    }

    formatCell(value: unknown, column: EfTableColumn): string {
        if (value == null) return '';
        switch (column.type) {
            case 'boolean':
                return value ? 'Yes' : 'No';
            case 'number':
                return Number(value).toLocaleString();
            case 'date':
                return new Date(String(value)).toLocaleDateString();
            default:
                return String(value);
        }
    }

    isSortActive(key: string): boolean {
        const field = this.sortField() ?? this.table().defaultSortField ?? null;
        return field === key;
    }

    isSortable(): boolean {
        return this.table().isSortable !== false;
    }
}
