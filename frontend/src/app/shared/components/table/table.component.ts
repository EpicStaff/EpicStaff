import { NgTemplateOutlet } from '@angular/common';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    contentChildren,
    effect,
    ElementRef,
    input,
    linkedSignal,
    output,
    signal,
    untracked,
    viewChildren,
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
import {
    clampColumnWidth,
    MAX_COLUMN_WIDTH,
    MIN_COLUMN_WIDTH,
    readTableLayout,
    TableLayout,
    writeTableLayout,
} from './table-layout-storage';

const CHECKBOX_COLUMN_WIDTH = '2rem';
const RESIZE_KEYBOARD_STEP = 16;

interface HeaderGroupSpan {
    label: string;
    /** 1-based grid column line the group starts at. */
    start: number;
    span: number;
}

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
        MultiSelectTriggerDirective,
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
    rowSelectable = input<(row: TableRow) => boolean>(() => true);
    /**
     * Display-only filter (e.g. a consumer's search box): rows it rejects are hidden, but stay in
     * `data`, so their selection is kept and still emitted. "Select all" / "deselect all" act on
     * visible rows only. Pass a new function whenever the criteria change; `null` shows every row.
     * Unlike filtering `data` itself, hiding a row never prunes it from the selection.
     */
    rowVisible = input<((row: TableRow) => boolean) | null>(null);
    /** Row IDs to pre-select on init */
    initialSelectedIds = input<unknown[]>([]);
    /**
     * Tell the table that an external filter/search (managed by the consumer outside
     * the header) is currently active. Combined with the table's own header filters,
     * this decides whether an empty `data` should render as the "no results" state
     * (header preserved so the user can clear the filter) or the full-empty
     * `[tableEmpty]` slot (no data has ever existed). Not needed for a `rowVisible` filter
     * while `data` is non-empty.
     */
    hasExternalFilter = input<boolean>(false);
    /**
     * Opts in to user-customized columns: every column that isn't `pinned` can be hidden (through an
     * `<app-table-column-picker>`) and resized by dragging its header edge. The choices are kept in localStorage
     * under this key, so give each table its own. `null` (default) keeps the columns as defined.
     */
    layoutKey = input<string | null>(null);

    selectionChange = output<TableRow[]>();
    filterChange = output<{ key: string; values: unknown[] }>();
    rowClick = output<TableRow>();
    /** Emitted when a column's headerIcon is clicked, with the clicked element to anchor a popup to */
    headerIconClick = output<{ key: string; target: HTMLElement }>();

    readonly cellTemplates = contentChildren(AppTableCellDirective);
    /** Header cells of `displayedColumns()`, in the same order. */
    private readonly headerCells = viewChildren<ElementRef<HTMLElement>>('headerCell');

    protected readonly minColumnWidth = MIN_COLUMN_WIDTH;
    protected readonly maxColumnWidth = MAX_COLUMN_WIDTH;

    private readonly selectedIds = signal<Set<unknown>>(new Set());
    private readonly activeFilters = signal<Record<string, unknown[]>>({});
    /** Last `defaultValues` applied per column key — used to detect actual changes and avoid re-applying on unrelated column def updates. */
    private readonly lastAppliedDefaults = signal<Record<string, unknown[]>>({});
    /** Column visibility and widths; re-read from storage when the key changes. */
    private readonly layout = linkedSignal<TableLayout>(() => readTableLayout(this.layoutKey()));
    /** Rendered px width of each resizable column, kept current by a ResizeObserver. */
    private readonly renderedWidths = signal<Record<string, number>>({});
    private resizing: { key: string; startX: number; startWidth: number } | null = null;

    readonly customizable = computed(() => this.layoutKey() !== null);

    readonly displayedColumns = computed<AppTableColumnDef[]>(() => {
        const visibility = this.layout().visibility;
        const hiddenByDefaultApplies = this.customizable();
        return this.columns().filter(
            (col) => col.pinned || (visibility[col.key] ?? !(hiddenByDefaultApplies && col.hiddenByDefault))
        );
    });

    /** The columns a column picker lists: all but the pinned ones, and none unless the table is customizable. */
    readonly hideableColumns = computed<AppTableColumnDef[]>(() =>
        this.customizable() ? this.columns().filter((col) => !col.pinned) : []
    );

    readonly visibleHideableKeys = computed<string[]>(() =>
        this.displayedColumns()
            .filter((col) => !col.pinned)
            .map((col) => col.key)
    );

    readonly hasPinnedStart = computed(() => this.displayedColumns().some((col) => col.pinned === 'start'));

    readonly headerGroups = computed<HeaderGroupSpan[]>(() => {
        const firstColumnLine = this.selectable() ? 2 : 1;
        const spans: HeaderGroupSpan[] = [];
        this.displayedColumns().forEach((col, index) => {
            if (!col.headerGroup) return;
            const line = index + firstColumnLine;
            const previous = spans.at(-1);
            if (previous?.label === col.headerGroup && previous.start + previous.span === line) {
                previous.span++;
            } else {
                spans.push({ label: col.headerGroup, start: line, span: 1 });
            }
        });
        return spans;
    });

    /** CSS `left` / `right` of each pinned column: the summed widths of the pinned columns before it. */
    private readonly pinnedOffsets = computed<Map<string, string>>(() => {
        const offsets = new Map<string, string>();
        const columns = this.displayedColumns();
        const accumulate = (pinnedColumns: AppTableColumnDef[], widths: string[]) => {
            for (const col of pinnedColumns) {
                offsets.set(col.key, widths.length ? `calc(${widths.join(' + ')})` : '0px');
                widths.push(col.width ?? '0px');
            }
        };
        accumulate(
            columns.filter((col) => col.pinned === 'start'),
            this.selectable() ? [CHECKBOX_COLUMN_WIDTH] : []
        );
        accumulate(columns.filter((col) => col.pinned === 'end').reverse(), []);
        return offsets;
    });

    constructor() {
        effect((onCleanup) => {
            const cells = this.headerCells();
            const columns = this.displayedColumns();
            // jsdom has no ResizeObserver; without one the separators report a width only once resized.
            if (!this.customizable() || typeof ResizeObserver === 'undefined') return;
            const keyByCell = new Map<Element, string>();
            cells.forEach((cell, index) => {
                if (!columns[index]?.pinned) keyByCell.set(cell.nativeElement, columns[index].key);
            });
            const observer = new ResizeObserver((entries) =>
                this.renderedWidths.update((widths) => {
                    const next = { ...widths };
                    for (const entry of entries) {
                        const key = keyByCell.get(entry.target);
                        if (key) next[key] = Math.round(entry.borderBoxSize[0].inlineSize);
                    }
                    return next;
                })
            );
            keyByCell.forEach((_key, cell) => observer.observe(cell));
            onCleanup(() => observer.disconnect());
        });

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

        // Apply per-column `defaultValues` whenever the columns array (or the default values
        // inside it) changes. Overwrites current selection, matching the "always follow" semantic
        // used e.g. for the active-org filter.
        effect(() => {
            const cols = this.columns();
            untracked(() => {
                const applied = this.lastAppliedDefaults();
                const nextApplied: Record<string, unknown[]> = { ...applied };
                let mutated = false;
                for (const col of cols) {
                    if (col.defaultValues === undefined) continue;
                    if (this.arraysShallowEqual(applied[col.key], col.defaultValues)) continue;
                    nextApplied[col.key] = [...col.defaultValues];
                    mutated = true;
                    this.onFilterChange(col.key, [...col.defaultValues]);
                }
                if (mutated) this.lastAppliedDefaults.set(nextApplied);
            });
        });
    }

    private arraysShallowEqual(a: unknown[] | undefined, b: unknown[]): boolean {
        if (!a || a.length !== b.length) return false;
        for (let i = 0; i < a.length; i++) {
            if (a[i] !== b[i]) return false;
        }
        return true;
    }

    /** True when any filter (header dropdown or external search) is currently applied; a `rowVisible` filter is deliberately not counted. */
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
        const rowVisibility = this.rowVisible();
        if (!activeEntries.length && !rowVisibility) return data;
        return data.filter(
            (row) =>
                (!rowVisibility || rowVisibility(row)) &&
                activeEntries.every(([key, values]) => {
                    const rowVal = row[key];
                    if (Array.isArray(rowVal)) {
                        return values.some((v) => (rowVal as unknown[]).includes(v));
                    }
                    return values.includes(rowVal);
                })
        );
    });

    /** Rows currently visible AND selectable — the pool "select all" and `allSelected` operate on. */
    private readonly selectablePool = computed<TableRow[]>(() => {
        const predicate = this.rowSelectable();
        return this.filteredData().filter((item) => predicate(item));
    });

    readonly allSelected = computed(() => {
        const pool = this.selectablePool();
        if (!pool.length) return false;
        const ids = this.selectedIds();
        return pool.every((item) => ids.has(this.getRowId(item)));
    });

    readonly indeterminate = computed(() => {
        const ids = this.selectedIds();
        const pool = this.selectablePool();
        const count = pool.filter((item) => ids.has(this.getRowId(item))).length;
        return count > 0 && count < pool.length;
    });

    readonly selectedItems = computed<TableRow[]>(() => {
        const ids = this.selectedIds();
        return this.data().filter((item) => ids.has(this.getRowId(item)));
    });

    readonly gridTemplateColumns = computed<string>(() => {
        const cols: string[] = [];
        if (this.selectable()) cols.push(CHECKBOX_COLUMN_WIDTH);
        const widths = this.layout().widths;
        for (const col of this.displayedColumns()) {
            const resizedWidth = col.pinned ? undefined : widths[col.key];
            cols.push(resizedWidth ? `${resizedWidth}px` : (col.width ?? '1fr'));
        }
        return cols.join(' ');
    });

    /** Shows exactly the given hideable columns and stores the choice. Unknown keys are ignored. */
    setVisibleColumns(keys: readonly string[]): void {
        const visible = new Set(keys);
        const visibility = Object.fromEntries(this.hideableColumns().map((col) => [col.key, visible.has(col.key)]));
        this.layout.update((layout) => ({ ...layout, visibility }));
        this.persistLayout();
    }

    /** Grid placement of a header cell when a header group adds a second header row; null otherwise. */
    headerGridArea(col: AppTableColumnDef, index: number): string | null {
        if (!this.headerGroups().length) return null;
        const line = index + (this.selectable() ? 2 : 1);
        return col.headerGroup ? `2 / ${line}` : `1 / ${line} / span 2`;
    }

    pinnedLeft(col: AppTableColumnDef): string | null {
        return col.pinned === 'start' ? (this.pinnedOffsets().get(col.key) ?? null) : null;
    }

    pinnedRight(col: AppTableColumnDef): string | null {
        return col.pinned === 'end' ? (this.pinnedOffsets().get(col.key) ?? null) : null;
    }

    /** The px width a column's resize separator reports: the stored one, else the rendered one; null until known. */
    columnWidth(key: string): number | null {
        return this.layout().widths[key] ?? this.renderedWidths()[key] ?? null;
    }

    onResizeStart(key: string, event: PointerEvent): void {
        if (event.button !== 0 || this.resizing) return;
        // Keeps the drag from selecting header text.
        event.preventDefault();
        // Captured, the handle keeps getting the moves while the pointer is over other cells.
        (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
        this.freezeColumnWidths();
        this.resizing = { key, startX: event.clientX, startWidth: this.columnWidth(key) ?? MIN_COLUMN_WIDTH };
    }

    onResizeMove(event: PointerEvent): void {
        if (!this.resizing) return;
        const { key, startX, startWidth } = this.resizing;
        this.setColumnWidth(key, startWidth + event.clientX - startX);
    }

    onResizeEnd(): void {
        if (!this.resizing) return;
        this.resizing = null;
        this.persistLayout();
    }

    onResizeKeydown(key: string, event: KeyboardEvent): void {
        if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
        event.preventDefault();
        this.freezeColumnWidths();
        const currentWidth = this.columnWidth(key) ?? MIN_COLUMN_WIDTH;
        this.setColumnWidth(
            key,
            currentWidth + (event.key === 'ArrowLeft' ? -RESIZE_KEYBOARD_STEP : RESIZE_KEYBOARD_STEP)
        );
        this.persistLayout();
    }

    getRowId(item: TableRow): unknown {
        return item[this.rowId()];
    }

    isSelected(item: TableRow): boolean {
        return this.selectedIds().has(this.getRowId(item));
    }

    /**
     * Selects or deselects the selectable pool only. Selected rows outside the pool — non-selectable
     * rows preselected via `initialSelectedIds`, or rows hidden by a header filter — are kept as they are.
     * Rows hidden by `rowVisible` are also left as they are.
     */
    toggleAll(): void {
        const poolIds = this.selectablePool().map((item) => this.getRowId(item));
        const ids = new Set(this.selectedIds());
        if (this.allSelected()) {
            poolIds.forEach((id) => ids.delete(id));
        } else {
            poolIds.forEach((id) => ids.add(id));
        }
        this.selectedIds.set(ids);
        this.selectionChange.emit(this.selectedItems());
    }

    toggleRow(item: TableRow): void {
        if (!this.rowSelectable()(item)) return;
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

    onHeaderIconClick(key: string, event: MouseEvent): void {
        this.headerIconClick.emit({ key, target: event.currentTarget as HTMLElement });
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

    activeFilterValues(key: string): unknown[] {
        return this.activeFilters()[key] ?? [];
    }

    hasFilterValue(key: string): boolean {
        return this.activeFilterValues(key).length > 0;
    }

    activeFilterCount(key: string): number {
        return this.activeFilterValues(key).length;
    }

    resolveActionVariant(action: AppTableRowAction, row: TableRow): AppTableActionVariant {
        const variant = action.variant;
        if (typeof variant === 'function') return variant(row);
        return variant ?? 'default';
    }

    private setColumnWidth(key: string, width: number): void {
        const clamped = clampColumnWidth(width);
        this.layout.update((layout) => ({ ...layout, widths: { ...layout.widths, [key]: clamped } }));
    }

    /**
     * Fixes every resizable column at its rendered px width before one is resized. Otherwise the `fr` columns share
     * out the space the resized one gives or takes, so its edge drifts away from the pointer. The frozen widths are
     * stored with the resized one: the layout restores as the user left it.
     */
    private freezeColumnWidths(): void {
        const rendered = this.renderedWidths();
        const frozen = Object.fromEntries(
            this.visibleHideableKeys()
                .filter((key) => rendered[key] !== undefined)
                .map((key) => [key, clampColumnWidth(rendered[key])])
        );
        this.layout.update((layout) => ({ ...layout, widths: { ...frozen, ...layout.widths } }));
    }

    /** Stores only entries of columns the table still has, so renamed or removed columns don't pile up. */
    private persistLayout(): void {
        const keys = new Set(this.columns().map((col) => col.key));
        const known = <T>(entries: Record<string, T>): Record<string, T> =>
            Object.fromEntries(Object.entries(entries).filter(([key]) => keys.has(key)));
        const { visibility, widths } = this.layout();
        writeTableLayout(this.layoutKey(), { visibility: known(visibility), widths: known(widths) });
    }
}
