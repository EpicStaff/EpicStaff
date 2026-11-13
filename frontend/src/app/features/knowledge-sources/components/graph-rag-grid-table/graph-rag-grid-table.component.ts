import {
    ChangeDetectionStrategy,
    Component,
    computed,
    effect,
    HostListener,
    input,
    output,
    signal,
} from '@angular/core';

import { HighlightPipe } from '../graph-rag-data-tables/highlight.pipe';
import { GraphGridColumnDef } from './graph-rag-grid-table.model';

const MIN_COLUMN_WIDTH = 100;
const POPOVER_MIN_WIDTH = 300;
const POPOVER_MIN_HEIGHT = 34;
const POPOVER_MAX_HEIGHT = 300;

interface ExpandedCell {
    value: string;
    style: Record<string, string>;
}

@Component({
    selector: 'app-graph-rag-grid-table',
    templateUrl: './graph-rag-grid-table.component.html',
    styleUrls: ['./graph-rag-grid-table.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [HighlightPipe],
})
export class GraphRagGridTableComponent {
    readonly columns = input.required<string[]>();
    readonly rows = input.required<Record<string, unknown>[]>();
    readonly searchTerm = input<string>('');
    readonly columnDefs = input<GraphGridColumnDef[]>([]);
    readonly clickableRows = input(false);
    readonly rowClick = output<Record<string, unknown>>();

    readonly expandedCell = signal<ExpandedCell | null>(null);

    private readonly columnWidths = signal<Record<string, number>>({});
    private resizing: { key: string; startX: number; startWidth: number } | null = null;

    private readonly columnDefMap = computed(() => {
        const map = new Map<string, GraphGridColumnDef>();
        for (const def of this.columnDefs()) {
            map.set(def.key, def);
        }
        return map;
    });

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

    readonly gridTemplateColumns = computed(() => {
        const widths = this.columnWidths();
        const defs = this.columnDefMap();
        return this.columns()
            .map((col) => {
                const width = widths[col];
                if (width) return `${width}px`;
                const def = defs.get(col);
                return def?.width ?? '1fr';
            })
            .join(' ');
    });

    formatColumnHeader(column: string): string {
        const def = this.columnDefMap().get(column);
        if (def?.label) return def.label;
        return column
            .split('_')
            .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
            .join(' ');
    }

    onCellClick(column: string, value: unknown, event: MouseEvent, row: Record<string, unknown>): void {
        if (this.clickableRows()) {
            this.rowClick.emit(row);
            return;
        }
        const cell = (event.currentTarget as HTMLElement).getBoundingClientRect();
        const text = value == null ? '' : String(value);
        const style = this.calculatePopoverPosition(cell);
        this.expandedCell.set({ value: text, style });
    }

    closePopover(): void {
        this.expandedCell.set(null);
    }

    @HostListener('document:keydown.escape')
    onEscapeKey(): void {
        if (this.expandedCell()) {
            this.closePopover();
        }
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
        this.resizing = { key, startX: event.clientX, startWidth: headerCell.offsetWidth };
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
