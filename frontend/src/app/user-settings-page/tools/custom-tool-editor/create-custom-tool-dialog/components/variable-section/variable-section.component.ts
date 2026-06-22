import { CdkDragDrop, DragDropModule } from '@angular/cdk/drag-drop';
import { ChangeDetectionStrategy, Component, computed, effect, input, output, signal, viewChild } from '@angular/core';

import { AppSvgIconComponent } from '../../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { DynamicTableComponent } from '../../../../../../shared/components/dynamic-table/dynamic-table.component';
import { TableColumnDef, TableRow } from '../../../../../../shared/components/dynamic-table/dynamic-table.models';
import {
    createCellExtraValidators,
    VALUE_EDITOR_COLUMN_DEFS,
    VariableInputType,
    VariableSectionConfig,
} from '../parameters-table.config';

export type VariableSectionMode = 'rows' | 'array-values';

@Component({
    selector: 'app-variable-section',
    imports: [AppSvgIconComponent, DynamicTableComponent, DragDropModule],
    templateUrl: './variable-section.component.html',
    styleUrls: ['./variable-section.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class VariableSectionComponent {
    config = input.required<VariableSectionConfig>();
    initialRows = input<Record<string, unknown>[]>([]);
    externalDuplicates = input<Map<string, Set<string>> | null>(null);

    /** Cross-table row drag: stable tbody `cdkDropList` id; null disables connecting to other parameter tables. */
    rowDropListId = input<string | null>(null);
    rowDropListConnectedTo = input<string[]>([]);
    rowSyncRevision = input<number>(0);

    mode = input<VariableSectionMode>('rows');

    rowsChange = output<Record<string, unknown>[]>();
    navigateRow = output<{ row: TableRow; rowIndex: number; sectionType: VariableInputType }>();
    crossListDrop = output<CdkDragDrop<unknown[]>>();

    private tableRef = viewChild<DynamicTableComponent>('table');
    readonly rows = signal<Record<string, unknown>[]>([]);

    readonly cellExtraValidators = computed(() => createCellExtraValidators(this.config().inputType));

    readonly isArrayValuesMode = computed(() => this.mode() === 'array-values');

    private readonly indexRevision = signal(0);
    readonly effectiveRowSyncRevision = computed(() => this.rowSyncRevision() + this.indexRevision());

    readonly effectiveColumnDefs = computed<TableColumnDef[]>(() => {
        const base = this.config().columnDefs;
        return this.isArrayValuesMode() ? [...VALUE_EDITOR_COLUMN_DEFS] : [...base];
    });

    readonly isNavigableRow = (row: TableRow): boolean => {
        const t = row.data['type'];
        return t === 'object' || t === 'array';
    };

    readonly isCellDisabled = (row: TableRow, colKey: string): boolean => {
        if (this.isArrayValuesMode() && colKey === 'name') {
            return true;
        }
        if (colKey === 'default_value') {
            const t = row.data['type'];
            return t === 'object' || t === 'array';
        }
        return false;
    };

    constructor() {
        effect(() => {
            const nextRows = this.initialRows();
            this.rows.set([...nextRows]);
        });
    }

    addRow(): void {
        this.tableRef()?.addRow();
    }

    onCrossListDrop(event: CdkDragDrop<unknown[]>): void {
        this.crossListDrop.emit(event);
    }

    onEmptySectionDropEnter(): void {
        this.tableRef()?.onEmptyDropEnter();
    }

    onEmptySectionDropExit(): void {
        this.tableRef()?.onEmptyDropExit();
    }

    onRowsChange(rows: Record<string, unknown>[]): void {
        if (this.isArrayValuesMode()) {
            const structuralChange = rows.some((r, i) => String(r['name'] ?? '') !== String(i));
            const reindexed = structuralChange ? rows.map((r, i) => ({ ...r, name: String(i) })) : rows;
            this.rows.set(reindexed);
            if (structuralChange) {
                this.indexRevision.update((n) => n + 1);
            }
            this.rowsChange.emit(reindexed);
            return;
        }
        this.rows.set(rows);
        this.rowsChange.emit(rows);
    }

    validate(): void {
        this.tableRef()?.touchAll();
    }

    isValid(): boolean {
        const table = this.tableRef();
        return table ? table.isValid() : true;
    }

    onNavigate(event: { row: TableRow; rowIndex: number }): void {
        this.navigateRow.emit({ ...event, sectionType: this.config().inputType });
    }
}
