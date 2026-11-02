import { computed, signal } from '@angular/core';

// narrow enough to tuck a column away, wide enough to keep its handle and an ellipsis grabbable
export const AUDIT_COLUMN_MIN_WIDTH = 48;

interface ColumnResize {
    index: number;
    startX: number;
    startWidth: number;
}

// Widths of an audit table's columns, resized by dragging a handle in the column's header cell.
export class AuditResizableColumns {
    private readonly columnWidths = signal<number[]>([]);
    private resize: ColumnResize | null = null;

    public readonly widths = this.columnWidths.asReadonly();
    // the table is at least as wide as its columns, so widening one scrolls the table instead of squeezing the rest
    public readonly tableWidth = computed(() => this.columnWidths().reduce((total, width) => total + width, 0));

    constructor(
        defaultWidths: number[],
        private readonly minWidth = AUDIT_COLUMN_MIN_WIDTH
    ) {
        this.columnWidths.set(defaultWidths);
    }

    public start(event: PointerEvent, index: number): void {
        if (event.button !== 0) {
            return;
        }
        event.preventDefault();
        const handle = event.currentTarget as HTMLElement;
        // capture keeps the drag alive when the pointer leaves the narrow handle
        handle.setPointerCapture(event.pointerId);
        // start from where the column actually is on screen, so the drag never jumps
        const startWidth = handle.parentElement?.getBoundingClientRect().width ?? this.columnWidths()[index];
        this.resize = { index, startX: event.clientX, startWidth };
    }

    public move(event: PointerEvent): void {
        const resize = this.resize;
        if (resize === null) {
            return;
        }
        const width = Math.max(this.minWidth, Math.round(resize.startWidth + event.clientX - resize.startX));
        this.columnWidths.update((widths) =>
            widths.map((current, index) => (index === resize.index ? width : current))
        );
    }

    public stop(): void {
        this.resize = null;
    }
}
