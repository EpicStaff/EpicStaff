import {
    afterNextRender,
    ChangeDetectionStrategy,
    Component,
    ElementRef,
    inject,
    input,
    model,
    OnDestroy,
    signal,
} from '@angular/core';

import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';

const KEYBOARD_STEP = 16;

/**
 * Draggable divider that resizes `column`, keeping at least `minOppositeWidth` for `opposite`.
 *
 * Place it between those two flex children and set the flex container's `gap` to 0 — the divider
 * supplies the spacing itself. `column` takes its width from `flex-basis`, which the parent binds
 * from the value written back here (see `createColumnWidthState`).
 */
@Component({
    selector: 'app-column-resize-divider',
    imports: [AppSvgIconComponent],
    template: `<app-svg-icon
        class="grip"
        icon="divider"
        width="1px"
        height="28px"
    />`,
    host: {
        role: 'separator',
        'aria-orientation': 'vertical',
        tabindex: '0',
        '[attr.aria-label]': 'ariaLabel()',
        '[attr.aria-valuenow]': 'width()',
        '[attr.aria-valuemin]': 'minWidth()',
        '[attr.aria-valuemax]': 'maxWidth()',
        '[class.is-dragging]': 'isDragging()',
        '(pointerdown)': 'onPointerDown($event)',
        '(pointermove)': 'onPointerMove($event)',
        '(pointerup)': 'stopDragging()',
        '(pointercancel)': 'cancelDragging()',
        '(lostpointercapture)': 'stopDragging()',
        '(dblclick)': 'resetToDefault()',
        '(keydown)': 'onKeydown($event)',
    },
    styles: [
        `
            :host {
                --column-divider-color: var(--color-text-primary);
                --column-divider-color-hover: var(--color-text-primary-hover);

                flex: 0 0 auto;
                align-self: stretch;
                width: 1rem;
                display: flex;
                align-items: center;
                justify-content: center;
                color: var(--column-divider-color);
                cursor: col-resize;
                /* Keep touch drags from scrolling the panel instead of resizing. */
                touch-action: none;
                outline: none;
            }

            .grip {
                transition: color 0.15s ease;
            }

            :host(:hover),
            :host(:focus-visible),
            :host(.is-dragging) {
                color: var(--column-divider-color-hover);
            }
        `,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ColumnResizeDividerComponent implements OnDestroy {
    public readonly column = input.required<HTMLElement>();
    public readonly opposite = input.required<HTMLElement>();

    public readonly width = model.required<number>();
    public readonly minWidth = input<number>(280);
    public readonly minOppositeWidth = input<number>(320);
    /** Width restored on double click or Home; omit to disable that shortcut. */
    public readonly defaultWidth = input<number | null>(null);
    public readonly ariaLabel = input<string>('Resize columns');

    protected readonly isDragging = signal(false);
    protected readonly maxWidth = signal<number | null>(null);

    private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
    private startX = 0;
    private startWidth = 0;
    private pendingClientX = 0;
    private frameHandle: number | null = null;
    private endDrag: (() => void) | null = null;
    private containerResize: ResizeObserver | null = null;

    constructor() {
        afterNextRender(() => {
            this.publishBoundsToCss();
            this.maxWidth.set(this.measureMaxWidth());
            this.observeContainer();
        });
    }

    public ngOnDestroy(): void {
        this.cancelPendingFrame();
        this.endDrag?.();
        this.containerResize?.disconnect();
    }

    protected onPointerDown(event: PointerEvent): void {
        // A second pointer mid-drag would replace `endDrag` and orphan the first one, leaving the
        // body unselectable and the Escape listener swallowing the key for good.
        if (event.button !== 0 || this.isDragging()) {
            return;
        }
        event.preventDefault();

        this.remeasureBounds();
        this.startX = event.clientX;
        this.pendingClientX = event.clientX;
        this.isDragging.set(true);
        this.host.nativeElement.setPointerCapture(event.pointerId);
        this.beginDrag();
    }

    protected onPointerMove(event: PointerEvent): void {
        if (!this.isDragging()) {
            return;
        }
        this.pendingClientX = event.clientX;
        if (this.frameHandle !== null) {
            return;
        }
        // One write per frame: every width change relayouts the code editor beside it.
        this.frameHandle = requestAnimationFrame(() => {
            this.frameHandle = null;
            this.applyWidth(this.draggedWidth());
        });
    }

    protected stopDragging(): void {
        if (!this.isDragging()) {
            return;
        }
        this.isDragging.set(false);
        if (this.frameHandle !== null) {
            // Flush the last move so the column lands where the pointer was released.
            this.cancelPendingFrame();
            this.applyWidth(this.draggedWidth());
        }
        this.finishDrag();
    }

    /** Drops the drag and puts the column back where it started. */
    protected cancelDragging(): void {
        if (!this.isDragging()) {
            return;
        }
        this.isDragging.set(false);
        this.cancelPendingFrame();
        this.finishDrag();
        this.applyWidth(this.startWidth);
    }

    protected resetToDefault(): void {
        const defaultWidth = this.defaultWidth();
        if (defaultWidth === null) {
            return;
        }
        this.remeasureBounds();
        this.applyWidth(defaultWidth);
    }

    protected onKeydown(event: KeyboardEvent): void {
        if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
            event.preventDefault();
            this.remeasureBounds();
            this.applyWidth(this.startWidth + (event.key === 'ArrowLeft' ? -KEYBOARD_STEP : KEYBOARD_STEP));
            return;
        }
        if (event.key === 'Home') {
            event.preventDefault();
            this.resetToDefault();
        }
    }

    private draggedWidth(): number {
        return this.startWidth + (this.pendingClientX - this.startX);
    }

    private applyWidth(rawWidth: number): void {
        const maxWidth = this.maxWidth();
        let nextWidth = Math.max(this.minWidth(), rawWidth);
        if (maxWidth !== null) {
            nextWidth = Math.min(maxWidth, nextWidth);
        }
        nextWidth = Math.round(nextWidth);

        if (nextWidth !== Math.round(this.width())) {
            this.width.set(nextWidth);
        }
    }

    /**
     * Starts from the rendered width rather than the bound one: a width remembered from a wider
     * window is capped by CSS, and the drag must continue from where the column actually is.
     */
    private remeasureBounds(): void {
        this.startWidth = this.column().getBoundingClientRect().width;
        this.maxWidth.set(this.measureMaxWidth());
    }

    private measureMaxWidth(): number {
        const columnWidth = this.column().getBoundingClientRect().width;
        const slack = this.opposite().getBoundingClientRect().width - this.minOppositeWidth();
        return Math.max(this.minWidth(), columnWidth + slack);
    }

    /**
     * Gives the `resizable-column` mixin the same bounds this component clamps to. On the container,
     * not this host: custom properties inherit downwards and the column is a sibling.
     */
    private publishBoundsToCss(): void {
        const container = this.column().parentElement;
        if (!container) {
            return;
        }
        container.style.setProperty('--column-min-opposite', `${this.minOppositeWidth()}px`);
        container.style.setProperty('--column-divider-width', `${this.host.nativeElement.offsetWidth}px`);
    }

    /** Keeps the bounds current while nothing is being dragged: panel and window resizes. */
    private observeContainer(): void {
        const container = this.column().parentElement;
        if (!container) {
            return;
        }
        this.containerResize = new ResizeObserver(() => this.maxWidth.set(this.measureMaxWidth()));
        this.containerResize.observe(container);
    }

    private beginDrag(): void {
        const body = this.host.nativeElement.ownerDocument.body;
        const previousUserSelect = body.style.userSelect;
        const previousCursor = body.style.cursor;

        body.style.userSelect = 'none';
        body.style.cursor = 'col-resize';

        const onKeydown = (event: KeyboardEvent) => {
            if (event.key !== 'Escape') {
                return;
            }
            // Capture phase: cancel the drag instead of letting the panel around it close.
            event.preventDefault();
            event.stopPropagation();
            this.cancelDragging();
        };
        body.ownerDocument.addEventListener('keydown', onKeydown, true);

        this.endDrag = () => {
            body.style.userSelect = previousUserSelect;
            body.style.cursor = previousCursor;
            body.ownerDocument.removeEventListener('keydown', onKeydown, true);
        };
    }

    private finishDrag(): void {
        this.endDrag?.();
        this.endDrag = null;
    }

    private cancelPendingFrame(): void {
        if (this.frameHandle !== null) {
            cancelAnimationFrame(this.frameHandle);
            this.frameHandle = null;
        }
    }
}
