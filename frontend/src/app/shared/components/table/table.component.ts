import { NgTemplateOutlet } from '@angular/common';
import {
    afterRenderEffect,
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
    viewChild,
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
import { distributeWidths, fitColumnWidths, WidthClaim } from './table-fit-columns';
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
/**
 * From this many shown columns besides the end-pinned ones (the checkbox column not counted) the columns are
 * resizable. With fewer, the first one fills the width the end-pinned ones leave, so there is nothing to resize.
 */
const MIN_RESIZABLE_COLUMN_COUNT = 2;
/** Widest share of the table's visible width a resizable column takes, so the other columns stay in reach. */
const MAX_COLUMN_SHARE = 0.5;
/**
 * A track that takes a share of the spare width: `<n>fr` (captures n), or `minmax(<min>, <n>fr)` with a px, rem or em
 * min (captures min and n). A bare `<n>fr` gets MIN_COLUMN_WIDTH as its minimum. Other `fr` forms are left to the grid
 * and are not held to the cap.
 */
const FLEXIBLE_TRACK = /^(?:(\d*\.?\d+)fr|minmax\(\s*(\d*\.?\d+(?:px|rem|em))\s*,\s*(\d*\.?\d+)fr\s*\))$/;
/** The browsers' default font size, for when none can be read. */
const DEFAULT_FONT_SIZE = 16;
/** An end-pinned column with this width is as wide as its widest cell. */
const CONTENT_SIZED_WIDTH = 'max-content';
/** A width that neither grows nor shrinks with the table, e.g. '200px' or '2rem'. */
const FIXED_LENGTH = /^\d*\.?\d+(px|rem|em)$/;

/** Horizontal scroll state of the wrapper, measured only when the table has pinned columns. */
interface HorizontalScroll {
    scrollLeft: number;
    /** How far the wrapper scrolls horizontally: scrollWidth - clientWidth. */
    overflow: number;
    /** The wrapper's clientWidth. */
    viewport: number;
    /** px between the wrapper's outer edge and its scrollport: the border, and on the end side the vertical scrollbar. */
    insetStart: number;
    insetEnd: number;
}

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
     * `<app-table-column-picker>`), and every column but an end-pinned one resized by dragging its header edge, while
     * two or more columns show besides the end-pinned ones. Each resizable column is held to half the table's visible
     * width (only the column that fills the spare width stretches past it, when nothing else needs the space); the cap
     * is per column, not for the pinned columns together.
     * The choices are kept in localStorage under this key, so give each table its own. `null` (default) keeps the
     * columns as defined.
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
    private readonly wrapper = viewChild<ElementRef<HTMLElement>>('wrapper');
    private readonly tableHeader = viewChild<ElementRef<HTMLElement>>('tableHeader');

    protected readonly minColumnWidth = MIN_COLUMN_WIDTH;
    protected readonly resizeHandleTooltip = 'Drag to resize. Double-click to fit all columns to the screen.';

    private readonly selectedIds = signal<Set<unknown>>(new Set());
    private readonly activeFilters = signal<Record<string, unknown[]>>({});
    /** Last `defaultValues` applied per column key — used to detect actual changes and avoid re-applying on unrelated column def updates. */
    private readonly lastAppliedDefaults = signal<Record<string, unknown[]>>({});
    /** Column visibility and widths; re-read from storage when the key changes. */
    private readonly layout = linkedSignal<TableLayout>(() => readTableLayout(this.layoutKey()));
    /** Rendered px width of each resizable column, kept current by a ResizeObserver. */
    private readonly renderedWidths = signal<Record<string, number>>({});
    /**
     * The wrapper's clientWidth, kept current by a ResizeObserver: the visible width of the table, not its scrollable
     * one, so widening a column does not raise the cap it is held to. 0 until measured.
     */
    private readonly containerWidth = signal(0);
    private readonly horizontalScroll = signal<HorizontalScroll>({
        scrollLeft: 0,
        overflow: 0,
        viewport: 0,
        insetStart: 0,
        insetEnd: 0,
    });
    /** Measured px width of each content-sized end-pinned column, the same in every row. */
    private readonly contentSizedWidths = signal<Record<string, number>>({});
    private resizing: { key: string; startX: number; startWidth: number } | null = null;
    /** The column whose resize handle is hovered, focused or dragged: its right edge is highlighted in every row. */
    protected readonly activeResizeKey = signal<string | null>(null);
    protected readonly resizeDragging = signal(false);
    /** Scroll px per pointer px while the scrollbar thumb is dragged. */
    private scrollbarDrag: { startX: number; startScrollLeft: number; scrollPerPixel: number } | null = null;
    protected readonly scrollbarDragging = signal(false);

    readonly customizable = computed(() => this.layoutKey() !== null);

    readonly displayedColumns = computed<AppTableColumnDef[]>(() => {
        const visibility = this.layout().visibility;
        const hiddenByDefaultApplies = this.customizable();
        return this.columns().filter(
            (col) => !this.isHideable(col) || (visibility[col.key] ?? !(hiddenByDefaultApplies && col.hiddenByDefault))
        );
    });

    /**
     * The columns a column picker lists: all but the pinned and the `hideable: false` ones, and none unless the table
     * is customizable.
     */
    readonly hideableColumns = computed<AppTableColumnDef[]>(() =>
        this.customizable() ? this.columns().filter((col) => this.isHideable(col)) : []
    );

    /**
     * Columns resize only in a customizable table showing two or more columns besides the end-pinned ones. With
     * fewer, stored widths are not applied either: the first column fills the width beside the end-pinned ones, which
     * keep their own.
     */
    private readonly resizeEnabled = computed(
        () =>
            this.customizable() &&
            this.displayedColumns().filter((col) => col.pinned !== 'end').length >= MIN_RESIZABLE_COLUMN_COUNT
    );

    /** Widest a resizable column renders, by drag, keyboard, fit, from storage or as its share of the spare width. */
    protected readonly maxColumnWidth = computed(() => this.columnWidthCap(this.containerWidth()));

    /** The cap holds once the table's visible width is measured, and only while its columns are resizable. */
    private readonly capApplies = computed(() => this.resizeEnabled() && this.containerWidth() > 0);

    /**
     * While the cap applies, the px width of each column whose track takes an `fr` share (see FLEXIBLE_TRACK): sized
     * the way CSS sizes `fr` tracks, by weight from the visible width less every other track, never under the track's
     * minimum, but held to the cap. CSS allows no `fr` inside `min()`, so the grid can't do it itself. Below the cap
     * the columns keep the proportions their `fr` weights give them. Reads the definitions, the stored widths and the
     * measured visible width, never the rendered column widths, so rendering the result can't feed back into it.
     */
    private readonly flexibleWidths = computed<Record<string, number>>(() => {
        const wrapper = this.wrapper()?.nativeElement;
        if (!this.capApplies() || !wrapper) return {};
        const claims: (WidthClaim & { key: string })[] = [];
        let fixedWidth = this.selectable() ? this.lengthInPx(CHECKBOX_COLUMN_WIDTH, wrapper) : 0;
        for (const col of this.displayedColumns()) {
            const track = col.pinned === 'end' ? this.endPinnedWidth(col) : this.definedTrack(col);
            const flexible = col.pinned === 'end' ? null : FLEXIBLE_TRACK.exec(track);
            if (flexible) {
                const min = flexible[2] ? Math.ceil(this.lengthInPx(flexible[2], wrapper)) : MIN_COLUMN_WIDTH;
                claims.push({ key: col.key, base: 0, min, weight: Number(flexible[1] ?? flexible[3]) });
            } else {
                fixedWidth += this.lengthInPx(track, wrapper);
            }
        }
        const available = Math.floor(this.containerWidth() - fixedWidth);
        const widths = distributeWidths(claims, available, this.maxColumnWidth());
        return Object.fromEntries(claims.map((claim, index) => [claim.key, widths[index]]));
    });

    readonly visibleHideableKeys = computed<string[]>(() =>
        this.displayedColumns()
            .filter((col) => this.isHideable(col))
            .map((col) => col.key)
    );

    /**
     * The column that takes up the space the others leave, so the end-pinned ones stay at the end: the last
     * start-pinned one (no pinned column follows it, so the sticky offsets stay right), else the first scrolling one.
     */
    private readonly fillerColumn = computed<AppTableColumnDef | undefined>(() => {
        const columns = this.displayedColumns();
        return columns.filter((col) => col.pinned === 'start').at(-1) ?? columns.find((col) => !col.pinned);
    });

    readonly hasPinnedStart = computed(() => this.displayedColumns().some((col) => col.pinned === 'start'));

    /**
     * With pinned columns the wrapper hides its own horizontal scrollbar, which would run under them, and the table
     * shows one under the scrolling columns only.
     */
    readonly hasPinnedColumns = computed(() => this.displayedColumns().some((col) => col.pinned));

    /** The last start-pinned and the first end-pinned column: their inner edges cast the "more content" shadow. */
    protected readonly pinnedEdgeKeys = computed(() => {
        const columns = this.displayedColumns();
        return {
            start: columns.filter((col) => col.pinned === 'start').at(-1)?.key ?? null,
            end: columns.find((col) => col.pinned === 'end')?.key ?? null,
        };
    });

    /** Columns are scrolled under the start-pinned ones. */
    protected readonly shadowStart = computed(() => this.horizontalScroll().scrollLeft > 0);
    /** Columns are hidden under the end-pinned ones; 1px of slack for fractional scroll positions. */
    protected readonly shadowEnd = computed(() => {
        const { scrollLeft, overflow } = this.horizontalScroll();
        return scrollLeft < overflow - 1;
    });

    protected readonly scrollbarOverflow = computed(() => this.horizontalScroll().overflow);

    /** Thumb size and position as % of the track; the thumb shows the visible share of the table's width. */
    protected readonly scrollbarThumb = computed(() => {
        const { scrollLeft, overflow, viewport } = this.horizontalScroll();
        const width = overflow > 0 ? (viewport / (viewport + overflow)) * 100 : 100;
        const left = overflow > 0 ? (Math.min(scrollLeft, overflow) / overflow) * (100 - width) : 0;
        return { width, left };
    });

    /** Margins that line the scrollbar up with the scrolling columns, between the pinned ones. */
    protected readonly scrollbarInset = computed(() => {
        const { startWidths, endWidths } = this.pinnedLayout();
        const { insetStart, insetEnd } = this.horizontalScroll();
        const sum = (widths: string[], inset: number) => `calc(${[...widths, `${inset}px`].join(' + ')})`;
        return { start: sum(startWidths, insetStart), end: sum(endWidths, insetEnd) };
    });

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

    /**
     * CSS `left` / `right` of each pinned column — the summed widths of the pinned columns before it — and the widths
     * of the sticky columns on each side (the checkbox column counts only while it sticks).
     */
    private readonly pinnedLayout = computed(() => {
        const offsets = new Map<string, string>();
        const columns = this.displayedColumns();
        const accumulate = (pinnedColumns: AppTableColumnDef[], widths: string[]): string[] => {
            for (const col of pinnedColumns) {
                offsets.set(col.key, widths.length ? `calc(${widths.join(' + ')})` : '0px');
                widths.push(this.pinnedWidth(col));
            }
            return pinnedColumns.length ? widths : [];
        };
        const startWidths = accumulate(
            columns.filter((col) => col.pinned === 'start'),
            this.selectable() ? [CHECKBOX_COLUMN_WIDTH] : []
        );
        const endWidths = accumulate(columns.filter((col) => col.pinned === 'end').reverse(), []);
        return { offsets, startWidths, endWidths };
    });

    constructor() {
        effect((onCleanup) => {
            const cells = this.headerCells();
            const columns = this.displayedColumns();
            // jsdom has no ResizeObserver; without one the separators report a width only once resized.
            if (!this.customizable() || typeof ResizeObserver === 'undefined') return;
            const keyByCell = new Map<Element, string>();
            cells.forEach((cell, index) => {
                if (columns[index] && this.isResizable(columns[index])) {
                    keyByCell.set(cell.nativeElement, columns[index].key);
                }
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

        // The column width cap follows the table's visible width, which changes with the window.
        effect((onCleanup) => {
            const wrapper = this.wrapper()?.nativeElement;
            if (!wrapper || !this.customizable() || typeof ResizeObserver === 'undefined') return;
            // Measured now as well, so a stored width never paints a first frame above the cap.
            this.containerWidth.set(wrapper.clientWidth);
            const observer = new ResizeObserver(() => this.containerWidth.set(wrapper.clientWidth));
            observer.observe(wrapper);
            onCleanup(() => observer.disconnect());
        });

        // Column resizes, visibility changes and a vertical scrollbar coming or going all change the horizontal
        // overflow without a scroll event.
        effect((onCleanup) => {
            const wrapper = this.wrapper()?.nativeElement;
            const header = this.tableHeader()?.nativeElement;
            if (!wrapper || !header || !this.hasPinnedColumns() || typeof ResizeObserver === 'undefined') return;
            const observer = new ResizeObserver(() => this.measureHorizontalScroll());
            observer.observe(wrapper);
            observer.observe(header);
            onCleanup(() => observer.disconnect());
        });

        // Each row is a grid of its own, so a content-sized column gets one px width measured over all its cells.
        afterRenderEffect(() => {
            this.filteredData();
            this.displayedColumns();
            untracked(() => this.measureContentSizedColumns());
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
            untracked(() => {
                if (!ids.length && !this.selectedIds().size) return;
                this.selectedIds.set(new Set(ids));
                this.selectionChange.emit(this.selectedItems());
            });
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
        const columns = this.displayedColumns();
        const filler = this.fillerColumn();
        const flexibleWidths = this.flexibleWidths();
        const tracks = columns.map((col) => {
            if (col.pinned === 'end') return this.endPinnedWidth(col);
            const flexibleWidth = flexibleWidths[col.key];
            return flexibleWidth === undefined ? this.definedTrack(col) : `${flexibleWidth}px`;
        });
        // Only once the user has sized the other columns: until then the space is shared out as defined. Under the cap
        // the `fr` shares are already worked out in px, so the filler takes what is left: the px lost to rounding, or
        // the width every capped column leaves.
        const othersFixed =
            this.capApplies() ||
            columns.every(
                (col) =>
                    col === filler ||
                    col.pinned === 'end' ||
                    this.resizedWidth(col) !== undefined ||
                    (col.pinned === 'start' && FIXED_LENGTH.test(col.width ?? ''))
            );
        columns.forEach((col, index) => {
            const track = tracks[index];
            cols.push(col === filler && othersFixed && FIXED_LENGTH.test(track) ? `minmax(${track}, 1fr)` : track);
        });
        return cols.join(' ');
    });

    /**
     * Shows exactly the given hideable columns and stores the choice; unknown keys and `hideable: false` columns are
     * ignored. The shown columns keep their current widths: a removed column's space goes to the filler column, an
     * added one takes the filler's extra space first, then the table scrolls.
     */
    setVisibleColumns(keys: readonly string[]): void {
        this.freezeColumnWidths(false);
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
        return col.pinned === 'start' ? (this.pinnedLayout().offsets.get(col.key) ?? null) : null;
    }

    pinnedRight(col: AppTableColumnDef): string | null {
        return col.pinned === 'end' ? (this.pinnedLayout().offsets.get(col.key) ?? null) : null;
    }

    /** A start-pinned column stays sticky while resized; an end-pinned one keeps its width. */
    isResizable(col: AppTableColumnDef): boolean {
        return this.resizeEnabled() && col.pinned !== 'end';
    }

    onWrapperScroll(): void {
        if (this.hasPinnedColumns()) this.measureHorizontalScroll();
    }

    /**
     * Starts dragging the scrollbar thumb. A press on the track outside the thumb first centres the thumb under the
     * pointer, so the drag continues from there.
     */
    onScrollbarPointerDown(event: PointerEvent): void {
        const wrapper = this.wrapper()?.nativeElement;
        const track = event.currentTarget as HTMLElement;
        if (event.button !== 0 || !wrapper) return;
        event.preventDefault();
        track.setPointerCapture(event.pointerId);
        const { overflow } = this.horizontalScroll();
        const trackRect = track.getBoundingClientRect();
        const thumbWidth = (trackRect.width * this.scrollbarThumb().width) / 100;
        const scrollPerPixel = trackRect.width > thumbWidth ? overflow / (trackRect.width - thumbWidth) : 0;
        if (!(event.target as HTMLElement).classList.contains('table-scrollbar__thumb')) {
            wrapper.scrollLeft = (event.clientX - trackRect.left - thumbWidth / 2) * scrollPerPixel;
        }
        this.scrollbarDrag = { startX: event.clientX, startScrollLeft: wrapper.scrollLeft, scrollPerPixel };
        this.scrollbarDragging.set(true);
    }

    onScrollbarPointerMove(event: PointerEvent): void {
        const wrapper = this.wrapper()?.nativeElement;
        if (!this.scrollbarDrag || !wrapper) return;
        const { startX, startScrollLeft, scrollPerPixel } = this.scrollbarDrag;
        wrapper.scrollLeft = startScrollLeft + (event.clientX - startX) * scrollPerPixel;
    }

    onScrollbarPointerEnd(): void {
        this.scrollbarDrag = null;
        this.scrollbarDragging.set(false);
    }

    /**
     * The wrapper hides its horizontal overflow when columns are pinned, so the browser no longer scrolls it sideways
     * on a wheel or trackpad: the horizontal delta (or a shift+wheel's vertical one) is applied here.
     */
    onWrapperWheel(event: WheelEvent): void {
        const wrapper = this.wrapper()?.nativeElement;
        if (!wrapper || !this.hasPinnedColumns()) return;
        const delta = event.deltaX || (event.shiftKey ? event.deltaY : 0);
        if (!delta) return;
        wrapper.scrollLeft += delta;
        // A diagonal trackpad swipe keeps its vertical part; a purely sideways one must not reach the page.
        if (!event.deltaX || !event.deltaY) event.preventDefault();
    }

    /**
     * The px width a column's resize separator reports: the stored one, else the rendered one, either held to the cap;
     * null until known. The filler column may render wider than stored, so its rendered width comes first.
     */
    columnWidth(key: string): number | null {
        const maxWidth = this.maxColumnWidth();
        const capped = (width: number | undefined) => (width === undefined ? undefined : Math.min(width, maxWidth));
        const stored = capped(this.layout().widths[key]);
        const rendered = capped(this.renderedWidths()[key]);
        return (this.fillerColumn()?.key === key ? (rendered ?? stored) : (stored ?? rendered)) ?? null;
    }

    onResizeHandleEnter(key: string): void {
        this.activeResizeKey.set(key);
    }

    /** Leaving or blurring the handle mid-drag keeps the line: the drag end clears it. */
    onResizeHandleLeave(): void {
        if (!this.resizing) this.activeResizeKey.set(null);
    }

    onResizeStart(key: string, event: PointerEvent): void {
        if (event.button !== 0 || this.resizing) return;
        // Keeps the drag from selecting header text.
        event.preventDefault();
        // Captured, the handle keeps getting the moves while the pointer is over other cells.
        (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
        this.freezeColumnWidths(true);
        this.resizing = { key, startX: event.clientX, startWidth: this.columnWidth(key) ?? MIN_COLUMN_WIDTH };
        this.activeResizeKey.set(key);
        this.resizeDragging.set(true);
    }

    onResizeMove(event: PointerEvent): void {
        if (!this.resizing) return;
        const { key, startX, startWidth } = this.resizing;
        this.setColumnWidth(key, startWidth + event.clientX - startX);
    }

    onResizeEnd(): void {
        if (!this.resizing) return;
        this.resizing = null;
        this.activeResizeKey.set(null);
        this.resizeDragging.set(false);
        this.persistLayout();
    }

    onResizeKeydown(key: string, event: KeyboardEvent): void {
        if (event.key === 'Enter') {
            event.preventDefault();
            this.fitColumnsToTable();
            return;
        }
        if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
        event.preventDefault();
        this.freezeColumnWidths(true);
        const currentWidth = this.columnWidth(key) ?? MIN_COLUMN_WIDTH;
        this.setColumnWidth(
            key,
            currentWidth + (event.key === 'ArrowLeft' ? -RESIZE_KEYBOARD_STEP : RESIZE_KEYBOARD_STEP)
        );
        this.persistLayout();
    }

    /**
     * Sizes every resizable column to its widest cell's full content, then shares the table's width out among them
     * (see `fitColumnWidths`), and stores the result like a manual resize.
     */
    fitColumnsToTable(): void {
        const wrapper = this.wrapper()?.nativeElement;
        if (!wrapper) return;
        const columns = this.displayedColumns();
        const resizableIndexes = columns.flatMap((col, index) => (this.isResizable(col) ? [index] : []));
        const rows = this.cellRows(wrapper);
        const header = rows[0];
        const fixedWidth = [
            wrapper.querySelector<HTMLElement>('.table-header > .table-cell.checkbox'),
            ...columns.map((col, index) => (col.pinned === 'end' ? header[index] : null)),
        ].reduce((sum, cell) => sum + (cell?.getBoundingClientRect().width ?? 0), 0);
        const contentWidths = this.measureContentWidths(rows, resizableIndexes);
        const maxWidth = this.columnWidthCap(wrapper.clientWidth);
        const fitted = fitColumnWidths(contentWidths, wrapper.clientWidth - fixedWidth, maxWidth);
        const widths = Object.fromEntries(
            resizableIndexes.map((columnIndex, position) => [
                columns[columnIndex].key,
                clampColumnWidth(fitted[position], maxWidth),
            ])
        );
        this.layout.update((layout) => ({ ...layout, widths: { ...layout.widths, ...widths } }));
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

    private isHideable(col: AppTableColumnDef): boolean {
        return !col.pinned && col.hideable !== false;
    }

    /** The grid track of an end-pinned column: its measured px width if content-sized, else its defined width. */
    private endPinnedWidth(col: AppTableColumnDef): string {
        const measured = this.contentSizedWidths()[col.key];
        return measured ? `${measured}px` : (col.width ?? '1fr');
    }

    /** A pinned column's width as a `calc()` term; a content-sized one counts as 0 until measured. */
    private pinnedWidth(col: AppTableColumnDef): string {
        const measured = col.pinned === 'end' ? this.contentSizedWidths()[col.key] : undefined;
        const width = measured ? `${measured}px` : (this.resizedWidth(col) ?? col.width);
        return width && width !== CONTENT_SIZED_WIDTH ? width : '0px';
    }

    /** Header and body rows, each holding its cells in `displayedColumns()` order, after the checkbox cell. */
    private cellRows(wrapper: HTMLElement): HTMLElement[][] {
        return [...wrapper.querySelectorAll<HTMLElement>('.table-header, .table-row')].map((row) => [
            ...row.querySelectorAll<HTMLElement>(':scope > .table-cell:not(.checkbox)'),
        ]);
    }

    private measureContentSizedColumns(): void {
        const wrapper = this.wrapper()?.nativeElement;
        const columns = this.displayedColumns();
        const indexes = columns.flatMap((col, index) =>
            col.pinned === 'end' && col.width === CONTENT_SIZED_WIDTH ? [index] : []
        );
        if (!wrapper || !indexes.length) return;
        const measured = this.measureContentWidths(this.cellRows(wrapper), indexes);
        const current = this.contentSizedWidths();
        const next = { ...current };
        indexes.forEach((columnIndex, position) => {
            // Nothing laid out (e.g. no layout engine): keep the column sized by `max-content`.
            if (measured[position] > 0) next[columns[columnIndex].key] = Math.ceil(measured[position]);
        });
        if (Object.keys(next).some((key) => next[key] !== current[key])) this.contentSizedWidths.set(next);
    }

    /**
     * The stored px width of a resized column, held to the cap, as a grid track. The cap applies on render rather than
     * to the stored value, so a width stored in a wider window comes back when the window grows again. End-pinned
     * columns are never resized, and no stored width applies while the table shows too few columns to resize.
     */
    private resizedWidth(col: AppTableColumnDef): string | undefined {
        const width = this.isResizable(col) ? this.layout().widths[col.key] : undefined;
        return width ? `${Math.min(width, this.maxColumnWidth())}px` : undefined;
    }

    /**
     * Half the table's visible width, never under MIN_COLUMN_WIDTH nor over MAX_COLUMN_WIDTH; MAX_COLUMN_WIDTH while the
     * width is not measured yet.
     */
    private columnWidthCap(containerWidth: number): number {
        if (containerWidth <= 0) return MAX_COLUMN_WIDTH;
        return clampColumnWidth(Math.floor(containerWidth * MAX_COLUMN_SHARE));
    }

    /** The grid track of a column that is not end-pinned, before the cap: its stored width, else its defined one. */
    private definedTrack(col: AppTableColumnDef): string {
        return this.resizedWidth(col) ?? col.width ?? '1fr';
    }

    /** A px, rem or em length in px; 0 for anything else (`auto`, an unmeasured `max-content`), which claims no width. */
    private lengthInPx(length: string, element: HTMLElement): number {
        const unit = FIXED_LENGTH.exec(length)?.[1];
        if (!unit) return 0;
        const fontSizeOf = (target: Element) => parseFloat(getComputedStyle(target).fontSize) || DEFAULT_FONT_SIZE;
        const factor = unit === 'px' ? 1 : fontSizeOf(unit === 'rem' ? element.ownerDocument.documentElement : element);
        return parseFloat(length) * factor;
    }

    private measureHorizontalScroll(): void {
        const wrapper = this.wrapper()?.nativeElement;
        if (!wrapper) return;
        this.horizontalScroll.set({
            scrollLeft: wrapper.scrollLeft,
            overflow: Math.max(0, wrapper.scrollWidth - wrapper.clientWidth),
            viewport: wrapper.clientWidth,
            insetStart: wrapper.clientLeft,
            insetEnd: wrapper.offsetWidth - wrapper.clientWidth - wrapper.clientLeft,
        });
    }

    /**
     * The full width of each column's widest cell, header included. Cells clip their content with an ellipsis, so
     * each is sized to `max-content` for the reading: all at once, so the browser lays the table out only once.
     */
    private measureContentWidths(rows: HTMLElement[][], columnIndexes: number[]): number[] {
        const cells = rows.flatMap((row) => columnIndexes.map((index) => row[index]).filter(Boolean));
        cells.forEach((cell) => cell.style.setProperty('width', 'max-content'));
        const widths = columnIndexes.map((index) =>
            Math.max(0, ...rows.map((row) => row[index]?.getBoundingClientRect().width ?? 0))
        );
        cells.forEach((cell) => cell.style.removeProperty('width'));
        return widths;
    }

    private setColumnWidth(key: string, width: number): void {
        const clamped = clampColumnWidth(width, this.maxColumnWidth());
        this.layout.update((layout) => ({ ...layout, widths: { ...layout.widths, [key]: clamped } }));
    }

    /**
     * Fixes the scrolling columns at their rendered px width (a stored width wins) before a resize or a visibility
     * change. Otherwise the `fr` columns share out the space that change gives or takes: a resized edge drifts away
     * from the pointer, and the other columns jump. The frozen widths are stored: the layout restores as the user left
     * it.
     *
     * The filler column is left at its base width, so it shrinks back to it when columns are added — unless
     * `fixFiller`: before a resize it is fixed at its rendered width too, as it sits before the resized edge and
     * would otherwise give or take space, moving that edge away from the pointer.
     */
    private freezeColumnWidths(fixFiller: boolean): void {
        const rendered = this.renderedWidths();
        const maxWidth = this.maxColumnWidth();
        const fillerKey = this.fillerColumn()?.key;
        const frozenKeys = this.displayedColumns()
            .filter((col) => !col.pinned && col.key !== fillerKey && rendered[col.key] !== undefined)
            .map((col) => col.key);
        const frozen = Object.fromEntries(frozenKeys.map((key) => [key, clampColumnWidth(rendered[key], maxWidth)]));
        const filler =
            fixFiller && fillerKey && rendered[fillerKey] !== undefined
                ? { [fillerKey]: clampColumnWidth(rendered[fillerKey], maxWidth) }
                : {};
        this.layout.update((layout) => ({ ...layout, widths: { ...frozen, ...layout.widths, ...filler } }));
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
