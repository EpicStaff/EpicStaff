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
/** Px past `minWidth` the drag has to travel before it snaps collapsed — tuned by feel, not derived. */
const COLLAPSE_DRAG_SLACK = 220;

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
    template: `
        @if (collapsible()) {
            <button
                type="button"
                class="collapse-toggle"
                [class.always-visible]="collapsed()"
                [attr.aria-label]="collapsed() ? 'Expand panel' : 'Collapse panel'"
                (pointerdown)="$event.stopPropagation()"
                (click)="onToggleClick()"
            >
                <app-svg-icon
                    [icon]="collapsed() ? 'chevron-right' : 'chevron-left'"
                    size="1rem"
                />
            </button>
        }
    `,
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
                position: relative;
                flex: 0 0 auto;
                align-self: stretch;
                width: 0.375rem;
                box-sizing: border-box;
                border-left: 1px solid var(--color-divider-subtle, rgba(255, 255, 255, 0.1));
                border-right: 1px solid var(--color-divider-subtle, rgba(255, 255, 255, 0.1));
                cursor: col-resize;
                transition: border-left-color 0.15s ease;
                /* Keep touch drags from scrolling the panel instead of resizing. */
                touch-action: none;
                outline: none;
                z-index: 10;
            }

            :host::before {
                content: '';
                position: absolute;
                top: 50%;
                left: 50%;
                transform: translate(-50%, -50%);
                width: 1px;
                height: 28px;
                background-color: var(--color-text-primary);
                pointer-events: none;
            }

            :host:has(.collapse-toggle.always-visible) {
                cursor: default;
                width: 1px;
                border-left: none;

                &::before {
                    display: none;
                }
            }

            :host:has(.collapse-toggle:not(.always-visible):hover) {
                border-left-color: var(--accent-color);
            }

            :host:has(.collapse-toggle.always-visible:hover) {
                border-right-color: var(--accent-color);
            }

            .collapse-toggle {
                position: absolute;
                top: 50%;
                left: 0;
                border-top-left-radius: 8px;
                border-bottom-left-radius: 8px;
                transform: translate(-100%, -50%);
                width: 28px;
                height: 66px;
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 0;
                border: 1px solid var(--color-divider-subtle, rgba(255, 255, 255, 0.1));
                background: var(--color-background-body);
                color: var(--color-text-primary);
                cursor: pointer;
                opacity: 0;
                pointer-events: none;
                transition:
                    opacity 0.15s ease,
                    border-color 0.15s ease,
                    color 0.15s ease;
                z-index: -1;

                &:hover {
                    border-color: var(--accent-color);
                    color: var(--accent-color);
                }

                &.always-visible {
                    opacity: 1;
                    pointer-events: auto;
                    left: 100%;
                    transform: translateY(-50%);
                    border-radius: 0 8px 8px 0;
                }
            }

            :host(:hover) .collapse-toggle,
            :host(:focus-visible) .collapse-toggle {
                opacity: 1;
                pointer-events: auto;
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

    public readonly collapsible = input<boolean>(false);
    public readonly collapsed = model<boolean>(false);

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

    protected onToggleClick(): void {
        this.collapsed.update((value) => !value);
    }

    protected onPointerDown(event: PointerEvent): void {
        // A second pointer mid-drag would replace `endDrag` and orphan the first one, leaving the
        // body unselectable and the Escape listener swallowing the key for good.
        if (event.button !== 0 || this.isDragging() || this.collapsed()) {
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
        this.collapsed.set(false);
        this.applyWidth(this.startWidth);
    }

    protected resetToDefault(): void {
        const defaultWidth = this.defaultWidth();
        if (defaultWidth === null) {
            return;
        }
        this.collapsed.set(false);
        this.remeasureBounds();
        this.applyWidth(defaultWidth);
    }

    protected onKeydown(event: KeyboardEvent): void {
        if (this.collapsible() && this.collapsed()) {
            if (event.key === 'Home') {
                event.preventDefault();
                this.resetToDefault();
            }
            return;
        }
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
        if (this.collapsible() && rawWidth < this.minWidth() - COLLAPSE_DRAG_SLACK) {
            if (!this.collapsed()) {
                this.collapsed.set(true);
            }
            return;
        }

        if (this.collapsed()) {
            this.collapsed.set(false);
        }

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
