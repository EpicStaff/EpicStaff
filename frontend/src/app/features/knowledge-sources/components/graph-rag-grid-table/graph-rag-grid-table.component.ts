import {
    ChangeDetectionStrategy,
    Component,
    computed,
    effect,
    ElementRef,
    HostListener,
    input,
    output,
    signal,
    viewChildren,
} from '@angular/core';
import { MatTooltip } from '@angular/material/tooltip';
import { AppSvgIconComponent } from '@shared/components';

import { GraphGridActionEvent, GraphGridColumnDef } from './graph-rag-grid-table.model';
import { HighlightPipe } from './highlight.pipe';

const MIN_COLUMN_WIDTH = 100;
const POPOVER_MIN_WIDTH = 300;
const POPOVER_MIN_HEIGHT = 34;
const POPOVER_MAX_HEIGHT = 300;

interface ExpandedCell {
    value: string;
    style: Record<string, string>;
}

/** Position of a body cell: row index into `rows`, column index into `columnDefs`. */
interface CellPosition {
    row: number;
    column: number;
}

@Component({
    selector: 'app-graph-rag-grid-table',
    templateUrl: './graph-rag-grid-table.component.html',
    styleUrls: ['./graph-rag-grid-table.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [AppSvgIconComponent, HighlightPipe, MatTooltip],
})
export class GraphRagGridTableComponent {
    readonly columnDefs = input.required<GraphGridColumnDef[]>();
    readonly rows = input.required<Record<string, unknown>[]>();
    readonly searchTerm = input<string>('');
    readonly actionClick = output<GraphGridActionEvent>();

    readonly expandedCell = signal<ExpandedCell | null>(null);

    private readonly columnWidths = signal<Record<string, number>>({});
    /** The cell that holds the grid's single tab stop (roving tabindex); updated whenever a cell gets focus. */
    private readonly activeCell = signal<CellPosition>({ row: 0, column: 0 });
    /** Body cells in DOM order: row by row, one entry per column. */
    private readonly bodyCells = viewChildren<ElementRef<HTMLElement>>('bodyCell');
    private resizing: { key: string; startX: number; startWidth: number } | null = null;
    private popoverAnchor: HTMLElement | null = null;

    constructor() {
        effect(() => {
            const defs = this.columnDefs();
            if (defs.length === 0) return;
            const initial: Record<string, number> = {};
            for (const def of defs) {
                if (def.width) {
                    const parsed = parseInt(def.width, 10);
                    if (!isNaN(parsed)) {
                        initial[def.key] = parsed;
                    }
                }
            }
            this.columnWidths.set(initial);
        });
    }

    /** The active cell clamped to the current data, so the grid keeps exactly one tab stop when rows or columns shrink. */
    private readonly tabStop = computed<CellPosition>(() => {
        const { row, column } = this.activeCell();
        return {
            row: Math.min(row, Math.max(this.rows().length - 1, 0)),
            column: Math.min(column, Math.max(this.columnDefs().length - 1, 0)),
        };
    });

    readonly gridTemplateColumns = computed(() => {
        const widths = this.columnWidths();
        const defs = this.columnDefs();
        const fillerIndex = defs.map((def) => !this.isActionColumn(def)).lastIndexOf(true);
        return defs
            .map((def, index) => {
                const width = widths[def.key];
                const track = width ? `${width}px` : (def.width ?? '1fr');
                return index === fillerIndex && track !== '1fr' ? `minmax(${track}, 1fr)` : track;
            })
            .join(' ');
    });

    formatColumnHeader(def: GraphGridColumnDef): string {
        if (def.action) return '';
        if (def.label) return def.label;
        return def.key
            .split('_')
            .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
            .join(' ');
    }

    /** True while the column renders as a row-level action button rather than a value cell. */
    isActionColumn(def: GraphGridColumnDef): boolean {
        return def.action !== undefined;
    }

    /**
     * Click, Enter and Space on a body cell:
     * — an action column emits `actionClick` with the column's action name;
     * — anything else opens the cell popover.
     */
    onCellActivate(def: GraphGridColumnDef, row: Record<string, unknown>, cellElement: HTMLElement): void {
        if (def.action) {
            this.closePopover();
            this.actionClick.emit({ action: def.action.name, row });
            return;
        }
        const value = row[def.key];
        const text = value == null ? '' : String(value);
        const style = this.calculatePopoverPosition(cellElement.getBoundingClientRect());
        this.popoverAnchor = cellElement;
        this.expandedCell.set({ value: text, style });
    }

    /** Only the tab-stop cell is in the Tab order; the others are reached with the arrow keys. */
    cellTabIndex(rowIndex: number, columnIndex: number): number {
        const tabStop = this.tabStop();
        return tabStop.row === rowIndex && tabStop.column === columnIndex ? 0 : -1;
    }

    onCellFocus(rowIndex: number, columnIndex: number): void {
        this.activeCell.set({ row: rowIndex, column: columnIndex });
    }

    /**
     * Grid keyboard model: arrows move one cell, Home/End jump to the first/last cell of the row,
     * Enter and Space activate the cell. Every handled key is prevented — Space and the arrows would otherwise
     * scroll the grid, and Enter is prevented too so it behaves exactly like a click.
     */
    onCellKeydown(
        event: KeyboardEvent,
        def: GraphGridColumnDef,
        row: Record<string, unknown>,
        position: CellPosition,
        cellElement: HTMLElement
    ): void {
        if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            this.onCellActivate(def, row, cellElement);
            return;
        }
        const target = this.targetCell(event.key, position);
        if (!target) return;
        event.preventDefault();
        this.focusCell(target);
    }

    closePopover(): void {
        this.expandedCell.set(null);
        this.popoverAnchor = null;
    }

    @HostListener('document:keydown.escape')
    onEscapeKey(): void {
        if (!this.expandedCell()) return;
        const anchor = this.popoverAnchor;
        this.closePopover();
        // Keyboard users return to the cell they opened the popover from.
        anchor?.focus();
    }

    @HostListener('document:pointerdown', ['$event'])
    onDocumentPointerDown(event: PointerEvent): void {
        if (!this.expandedCell()) return;
        const target = event.target as HTMLElement;
        if (!target.closest('.grid-table-popover')) {
            this.closePopover();
        }
    }

    onResizeStart(key: string, event: PointerEvent, headerCell: HTMLElement): void {
        this.closePopover();
        if (event.button !== 0 || this.resizing) return;
        event.preventDefault();
        (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
        this.freezeColumnWidths(headerCell);
        this.resizing = { key, startX: event.clientX, startWidth: headerCell.offsetWidth };
    }

    private freezeColumnWidths(headerCell: HTMLElement): void {
        const row = headerCell.parentElement;
        if (!row) return;
        const cells = Array.from(row.children) as HTMLElement[];
        const defs = this.columnDefs();
        this.columnWidths.update((widths) => {
            const frozen: Record<string, number> = { ...widths };
            cells.forEach((cell, index) => {
                const def = defs[index];
                if (def && frozen[def.key] === undefined) {
                    frozen[def.key] = cell.offsetWidth;
                }
            });
            return frozen;
        });
    }

    onResizeMove(event: PointerEvent): void {
        if (!this.resizing) return;
        const { key, startX, startWidth } = this.resizing;
        const newWidth = Math.max(MIN_COLUMN_WIDTH, startWidth + event.clientX - startX);
        this.columnWidths.update((widths) => ({ ...widths, [key]: newWidth }));
    }

    onResizeEnd(): void {
        this.resizing = null;
    }

    /** The cell a navigation key moves to, or null for keys the grid does not handle. Moves stop at the edges. */
    private targetCell(key: string, { row, column }: CellPosition): CellPosition | null {
        const lastRow = this.rows().length - 1;
        const lastColumn = this.columnDefs().length - 1;
        switch (key) {
            case 'ArrowUp':
                return { row: Math.max(row - 1, 0), column };
            case 'ArrowDown':
                return { row: Math.min(row + 1, lastRow), column };
            case 'ArrowLeft':
                return { row, column: Math.max(column - 1, 0) };
            case 'ArrowRight':
                return { row, column: Math.min(column + 1, lastColumn) };
            case 'Home':
                return { row, column: 0 };
            case 'End':
                return { row, column: lastColumn };
            default:
                return null;
        }
    }

    private focusCell(position: CellPosition): void {
        // The popover belongs to the cell it was opened from; moving away closes it.
        this.closePopover();
        this.activeCell.set(position);
        const cellIndex = position.row * this.columnDefs().length + position.column;
        this.bodyCells()[cellIndex]?.nativeElement.focus();
    }

    private calculatePopoverPosition(cellRect: DOMRect): Record<string, string> {
        const viewportWidth = window.innerWidth;
        const viewportHeight = window.innerHeight;
        const popoverWidth = Math.max(cellRect.width, POPOVER_MIN_WIDTH);
        const style: Record<string, string> = {
            position: 'fixed',
            width: `${popoverWidth}px`,
            'min-height': `${POPOVER_MIN_HEIGHT}px`,
            'max-height': `${POPOVER_MAX_HEIGHT}px`,
        };

        // Horizontal: anchor to cell left, flip if overflows
        if (cellRect.left + popoverWidth <= viewportWidth) {
            style['left'] = `${cellRect.left}px`;
        } else {
            style['right'] = `${viewportWidth - cellRect.right}px`;
        }

        // Vertical: anchor to cell top, flip up if overflows
        if (cellRect.top + POPOVER_MAX_HEIGHT <= viewportHeight) {
            style['top'] = `${cellRect.top}px`;
        } else {
            style['bottom'] = `${viewportHeight - cellRect.bottom}px`;
        }

        return style;
    }
}
