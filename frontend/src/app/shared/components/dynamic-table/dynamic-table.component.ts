import { CdkDragDrop, DragDropModule, moveItemInArray } from '@angular/cdk/drag-drop';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    effect,
    inject,
    input,
    OnInit,
    output,
    signal,
} from '@angular/core';
import { FormControl, FormsModule, ReactiveFormsModule, ValidatorFn } from '@angular/forms';

import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';
import { CheckboxComponent } from '../checkbox/checkbox.component';
import { TableColumnDef, TableRow } from './dynamic-table.models';

@Component({
    selector: 'app-dynamic-table',
    imports: [FormsModule, ReactiveFormsModule, DragDropModule, AppSvgIconComponent, CheckboxComponent],
    templateUrl: './dynamic-table.component.html',
    styleUrls: ['./dynamic-table.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DynamicTableComponent implements OnInit {
    private destroyRef = inject(DestroyRef);
    private lastAppliedRowSyncRevision = 0;

    // Header
    title = input.required<string>();
    icon = input<string | null>(null); // svg icon name, null means no icon

    // Column definitions
    columnDefs = input.required<TableColumnDef[]>();

    // Initial rows value (for external initial data)
    initialRows = input<Record<string, unknown>[]>([]);

    // Feature flags
    allowRowDrag = input<boolean>(true);
    allowColumnDrag = input<boolean>(true);
    allowRowRemove = input<boolean>(true);
    showHeader = input<boolean>(true);

    // Constraints
    maxHeight = input<string | null>(null); // e.g. '400px', null = no limit
    maxRows = input<number | null>(null); // null = unlimited

    // Navigate-into-row (e.g. for object-type rows)
    rowNavigable = input<((row: TableRow) => boolean) | null>(null);

    // When set, navigable rows show the navigate button inside this cell instead of the action column.
    navigateCellKey = input<string | null>(null);

    // Optionally disable a cell input based on row and column key
    isCellDisabled = input<((row: TableRow, colKey: string) => boolean) | null>(null);

    // Per-column set of values that are also considered duplicates (e.g. coming from sibling tables)
    externalDuplicates = input<Map<string, Set<string>> | null>(null);

    // Optional callback to provide extra row-aware validators for a cell. Useful when one column's
    // validators depend on another column's value (e.g. default_value validation depending on type).
    getCellExtraValidators = input<((row: TableRow, colKey: string) => ValidatorFn[]) | null>(null);

    /** Stable id for the row tbody `cdkDropList` (cross-list drag). Column header list uses a different id. */
    rowDropListId = input<string | null>(null);

    /** Other row drop list ids this list can exchange rows with. */
    rowDropListConnectedTo = input<string[]>([]);

    /**
     * Increment from parent after cross-table moves so rows reload from `initialRows`
     * (ToolVariable is source of truth).
     */
    rowSyncRevision = input<number>(0);

    // Outputs
    rowsChange = output<Record<string, unknown>[]>();
    navigateRow = output<{ row: TableRow; rowIndex: number }>();

    /** Emitted when a row is dropped onto another connected table; parent updates model and bumps `rowSyncRevision`. */
    crossListDrop = output<CdkDragDrop<TableRow[]>>();

    // Internal state
    columns = signal<TableColumnDef[]>([]);
    rows = signal<TableRow[]>([]);
    emptyDropPreview = signal(false);

    // FormControls map: key = `${rowId}_${colKey}`
    private cellControls = new Map<string, FormControl>();

    // Validation error bar
    validationErrors = signal<string[]>([]);
    showValidationBar = computed(() => this.validationErrors().length > 0);

    // Cells with a uniqueness violation: stored as `${rowId}_${colKey}`
    duplicateCells = signal<Set<string>>(new Set());

    canAddRow = computed(() => {
        const max = this.maxRows();
        return max === null || this.rows().length < max;
    });

    // Column resize
    colWidths = signal<Record<string, number>>({});
    actionColWidth = computed(() => {
        const hasNavigate = this.rowNavigable() !== null && !this.navigateCellKey();
        const hasRemove = this.allowRowRemove();
        if (hasNavigate && hasRemove) return 68;
        if (hasNavigate || hasRemove) return 36;
        return 8;
    });
    tableMinWidth = computed(() => {
        const spacers = (this.allowRowDrag() ? 36 : 0) + this.actionColWidth();
        return this.columns().reduce((sum, col) => sum + this.getColWidth(col.key), spacers);
    });
    totalColumnCount = computed(() => this.columns().length + (this.allowRowDrag() ? 1 : 0) + 1);
    canReceiveExternalRows = computed(
        () => this.allowRowDrag() && !!this.rowDropListId() && this.rowDropListConnectedTo().length > 0
    );
    private resizeMoveHandler: ((e: MouseEvent) => void) | null = null;
    private resizeUpHandler: (() => void) | null = null;

    /** Stable id for thead horizontal column drag list (never connect to row lists). */
    readonly columnDropListId = computed(() => {
        const id = this.rowDropListId();
        return id ? `${id}__cols` : null;
    });

    constructor() {
        effect(() => {
            this.columns.set([...this.columnDefs()]);
            this.initColWidths();
        });

        effect(() => {
            // re-validate when rows, columns, or external duplicates change
            this.rows();
            this.columnDefs();
            this.externalDuplicates();
            this.validateAll();
        });

        effect(() => {
            const rev = this.rowSyncRevision();
            if (rev > this.lastAppliedRowSyncRevision) {
                this.lastAppliedRowSyncRevision = rev;
                this.resetRowsFromInitial(this.initialRows());
            }
        });

        effect(() => {
            const initial = this.initialRows();
            if (this.rows().length === 0 && initial.length > 0 && this.rowSyncRevision() === 0) {
                this.resetRowsFromInitial(initial);
            }
        });
    }

    ngOnInit(): void {
        this.destroyRef.onDestroy(() => {
            if (this.resizeMoveHandler) document.removeEventListener('mousemove', this.resizeMoveHandler);
            if (this.resizeUpHandler) document.removeEventListener('mouseup', this.resizeUpHandler);
        });

        const initial = this.initialRows();
        if (initial.length > 0) {
            const rows = initial.map((data) => this.createRowFromData(data));
            this.rows.set(rows);
        }
    }

    // --- Row Operations ---

    addRow(): void {
        if (!this.canAddRow()) return;

        const newRow: TableRow = {
            _id: this.generateId(),
            data: {},
        };

        // Initialize default values
        for (const col of this.columnDefs()) {
            if (col.defaultValue !== undefined) {
                newRow.data[col.key] = col.defaultValue;
            } else if (col.type === 'checkbox') {
                newRow.data[col.key] = false;
            } else {
                newRow.data[col.key] = '';
            }
        }

        this.rows.update((rows) => [...rows, newRow]);
        // Create controls for new row
        this.initRowControls(newRow);
        this.emitChange();
    }

    removeRow(rowId: string): void {
        // Clean up controls
        const row = this.rows().find((r) => r._id === rowId);
        if (row) {
            for (const col of this.columns()) {
                this.cellControls.delete(`${rowId}_${col.key}`);
            }
        }

        this.rows.update((rows) => rows.filter((r) => r._id !== rowId));
        this.validateAll();
        this.emitChange();
    }

    onRowDrop(event: CdkDragDrop<TableRow[]>): void {
        if (!this.allowRowDrag()) return;
        this.emptyDropPreview.set(false);
        if (event.previousContainer === event.container) {
            const rows = [...this.rows()];
            moveItemInArray(rows, event.previousIndex, event.currentIndex);
            this.rows.set(rows);
            this.emitChange();
            return;
        }
        this.crossListDrop.emit(event);
    }

    onEmptyDropEnter(): void {
        this.emptyDropPreview.set(true);
    }

    onEmptyDropExit(): void {
        this.emptyDropPreview.set(false);
    }

    onColumnDrop(event: CdkDragDrop<TableColumnDef[]>): void {
        if (!this.allowColumnDrag()) return;
        const cols = [...this.columns()];
        moveItemInArray(cols, event.previousIndex, event.currentIndex);
        this.columns.set(cols);
    }

    // --- Cell Value Updates ---

    onCellChange(rowId: string, colKey: string, value: unknown): void {
        this.rows.update((rows) =>
            rows.map((r) => (r._id === rowId ? { ...r, data: { ...r.data, [colKey]: value } } : r))
        );

        const control = this.getOrCreateControl(rowId, colKey, value);
        control.markAsTouched();
        control.setValue(value);

        // Re-evaluate validators for every cell of this row, since one cell's value
        // may change another cell's validators (e.g. type → default_value).
        const updatedRow = this.rows().find((r) => r._id === rowId);
        if (updatedRow) {
            for (const col of this.columnDefs()) {
                const ctrl = this.cellControls.get(`${rowId}_${col.key}`);
                if (!ctrl) continue;
                const wasValid = ctrl.valid;
                ctrl.setValidators(this.computeValidators(updatedRow, col));
                ctrl.updateValueAndValidity({ emitEvent: false });
                // Surface dependent errors immediately if the cell flipped to invalid.
                const cellValue = ctrl.value;
                if (wasValid && ctrl.invalid && cellValue !== '' && cellValue != null) {
                    ctrl.markAsTouched();
                }
            }
        }

        this.validateAll();
        this.emitChange();
    }

    private computeValidators(row: TableRow, col: TableColumnDef): ValidatorFn[] {
        const colValidators = col.validators ?? [];
        const extra = this.getCellExtraValidators()?.(row, col.key) ?? [];
        return [...colValidators, ...extra];
    }

    private getOrCreateControl(rowId: string, colKey: string, value: unknown): FormControl {
        const key = `${rowId}_${colKey}`;
        let control = this.cellControls.get(key);
        if (!control) {
            const row = this.rows().find((r) => r._id === rowId);
            const col = this.columnDefs().find((c) => c.key === colKey);
            const validators = row && col ? this.computeValidators(row, col) : (col?.validators ?? []);
            control = new FormControl(value, validators);
            this.cellControls.set(key, control);
        }
        return control;
    }

    getCellValue(rowId: string, colKey: string): unknown {
        const row = this.rows().find((r) => r._id === rowId);
        return row?.data[colKey] ?? '';
    }

    getControl(rowId: string, colKey: string): FormControl {
        const key = `${rowId}_${colKey}`;
        if (!this.cellControls.has(key)) {
            const row = this.rows().find((r) => r._id === rowId);
            const col = this.columns().find((c) => c.key === colKey);
            const value = row?.data[colKey] ?? '';
            this.cellControls.set(key, new FormControl(value, col?.validators ?? []));
        }
        return this.cellControls.get(key)!;
    }

    isCellInvalid(rowId: string, colKey: string): boolean {
        const control = this.cellControls.get(`${rowId}_${colKey}`);
        if (control && control.invalid && control.touched) return true;
        return this.duplicateCells().has(`${rowId}_${colKey}`);
    }

    // --- Validation ---

    private validateAll(): void {
        const errors: string[] = [];
        const seenMessages = new Set<string>();
        const pushError = (msg: string) => {
            if (!seenMessages.has(msg)) {
                seenMessages.add(msg);
                errors.push(msg);
            }
        };

        const cols = this.columnDefs();

        // Per-cell validator errors (only if touched)
        for (const row of this.rows()) {
            for (const col of cols) {
                const control = this.cellControls.get(`${row._id}_${col.key}`);
                if (control && control.invalid && control.touched) {
                    pushError(this.getErrorMessage(col, control));
                }
            }
        }

        // Uniqueness errors (column-level + external duplicates)
        const duplicates = new Set<string>();
        const external = this.externalDuplicates();
        for (const col of cols) {
            if (!col.unique) continue;

            const valuesToRowIds = new Map<string, string[]>();
            for (const row of this.rows()) {
                const raw = row.data[col.key];
                if (raw == null) continue;
                const value = String(raw).trim();
                if (!value) continue;
                const arr = valuesToRowIds.get(value) ?? [];
                arr.push(row._id);
                valuesToRowIds.set(value, arr);
            }

            const externalSet = external?.get(col.key) ?? null;
            let columnHasDuplicate = false;
            for (const [value, rowIds] of valuesToRowIds) {
                const isDup = rowIds.length > 1 || (externalSet?.has(value) ?? false);
                if (isDup) {
                    columnHasDuplicate = true;
                    for (const rowId of rowIds) {
                        duplicates.add(`${rowId}_${col.key}`);
                    }
                }
            }

            if (columnHasDuplicate) {
                pushError(col.uniqueErrorMessage ?? `${col.header} must be unique.`);
            }
        }

        this.duplicateCells.set(duplicates);
        this.validationErrors.set(errors);
    }

    private getErrorMessage(col: TableColumnDef, control: FormControl): string {
        if (!control.errors) return '';
        const errorKey = Object.keys(control.errors)[0];
        if (col.errorMessages?.[errorKey]) {
            return col.errorMessages[errorKey];
        }
        // Default messages
        const defaults: Record<string, string> = {
            required: `Please provide a ${col.header.toLowerCase()}. This field cannot be empty.`,
            minlength: `${col.header} is too short.`,
            maxlength: `${col.header} is too long.`,
            min: `${col.header} value is too small.`,
            max: `${col.header} value is too large.`,
            pattern: `${col.header} format is invalid.`,
            email: `Please enter a valid email address.`,
        };
        return defaults[errorKey] ?? `${col.header} is invalid.`;
    }

    touchAll(): void {
        for (const control of this.cellControls.values()) {
            control.markAsTouched();
        }
        this.validateAll();
    }

    isValid(): boolean {
        return this.validationErrors().length === 0 && this.duplicateCells().size === 0;
    }

    dismissValidationError(): void {
        this.validationErrors.set([]);
    }

    // --- Helpers ---

    private createRowFromData(data: Record<string, unknown>): TableRow {
        const row: TableRow = { _id: this.generateId(), data: { ...data } };
        this.initRowControls(row);
        return row;
    }

    private initRowControls(row: TableRow): void {
        for (const col of this.columnDefs()) {
            const key = `${row._id}_${col.key}`;
            const value = row.data[col.key] ?? (col.type === 'checkbox' ? false : '');
            this.cellControls.set(key, new FormControl(value, this.computeValidators(row, col)));
        }
    }

    private emitChange(): void {
        this.rowsChange.emit(this.rows().map((r) => ({ ...r.data })));
    }

    private resetRowsFromInitial(initial: Record<string, unknown>[]): void {
        for (const row of this.rows()) {
            for (const col of this.columns()) {
                this.cellControls.delete(`${row._id}_${col.key}`);
            }
        }
        const newRows = initial.map((data) => this.createRowFromData(data));
        this.rows.set(newRows);
        this.validateAll();
    }

    private generateId(): string {
        return Math.random().toString(36).slice(2, 10) + Date.now().toString(36);
    }

    // --- Column Resize ---

    getColWidth(colKey: string): number {
        return this.colWidths()[colKey] ?? 120;
    }

    getDefaultColWidth(col: TableColumnDef): number {
        const parsed = col.width ? parseInt(col.width, 10) : 120;
        return isNaN(parsed) ? 120 : parsed;
    }

    onResizeStart(event: MouseEvent, colKey: string): void {
        event.preventDefault();
        event.stopPropagation();

        const startX = event.clientX;
        const startWidth = this.getColWidth(colKey);

        this.resizeMoveHandler = (e: MouseEvent) => {
            const newWidth = Math.max(40, startWidth + e.clientX - startX);
            this.colWidths.update((w) => ({ ...w, [colKey]: newWidth }));
        };

        this.resizeUpHandler = () => {
            document.removeEventListener('mousemove', this.resizeMoveHandler!);
            document.removeEventListener('mouseup', this.resizeUpHandler!);
            this.resizeMoveHandler = null;
            this.resizeUpHandler = null;
        };

        document.addEventListener('mousemove', this.resizeMoveHandler);
        document.addEventListener('mouseup', this.resizeUpHandler);
    }

    private initColWidths(): void {
        const widths: Record<string, number> = {};
        for (const col of this.columnDefs()) {
            const parsed = col.width ? parseInt(col.width, 10) : 120;
            widths[col.key] = isNaN(parsed) ? 120 : parsed;
        }
        this.colWidths.set(widths);
    }

    trackByRowId(_: number, row: TableRow): string {
        return row._id;
    }

    trackByColKey(_: number, col: TableColumnDef): string {
        return col.key;
    }
}
