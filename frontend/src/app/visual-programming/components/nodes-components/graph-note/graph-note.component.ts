import { AriaDescriber, FocusMonitor } from '@angular/cdk/a11y';
import { CdkOverlayOrigin, OverlayModule } from '@angular/cdk/overlay';
import { DOCUMENT } from '@angular/common';
import {
    AfterViewInit,
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    effect,
    inject,
    Input,
    input,
    signal,
    viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { EFResizeHandleType, FFlowModule } from '@foblex/flow';

import { GraphNoteModel } from '../../../core/models/node.model';
import { NOTE_COLORS } from '../../../core/utils/note-colors.util';
import { FlowReadOnlyService } from '../../../services/flow-readonly.service';
import { DisplaySegment, fieldValueSegments } from '../../../utils/diff';
import { DiffFieldMarkChange } from '../../diff-field-mark/diff-field-mark.component';
import {
    currentValueDescription,
    DIFF_MARK_TOOLTIP_POSITIONS,
    DiffMarkTooltipComponent,
} from '../../diff-field-mark/diff-mark-tooltip.component';
import { ResizeHandleComponent } from '../../resize-handle/resize-handle.component';

@Component({
    selector: 'app-graph-note',
    imports: [FFlowModule, FormsModule, OverlayModule, DiffMarkTooltipComponent, ResizeHandleComponent],
    template: `
        <div
            class="note-container"
            cdkOverlayOrigin
            #noteOrigin="cdkOverlayOrigin"
            [style.--note-bg]="node.data.backgroundColor || defaultNoteColor"
            [attr.tabindex]="contentChange() !== null ? 0 : null"
            (mouseenter)="openTooltip()"
            (mouseleave)="closeTooltip()"
            (keydown.escape)="onEscape($event)"
        >
            <div
                class="content-container"
                [style.font-size.px]="node.data.fontSize || 14"
            >
                {{ node.data.content || (isReadOnly() ? '' : 'Add note text...') }}
            </div>
            @if (!isReadOnly()) {
                <app-resize-handle [handleType]="eResizeHandleType.RIGHT_BOTTOM"></app-resize-handle>
            }
        </div>
        <ng-template
            cdkConnectedOverlay
            [cdkConnectedOverlayOrigin]="noteOrigin"
            [cdkConnectedOverlayOpen]="isTooltipOpen() && contentChange() !== null"
            [cdkConnectedOverlayPositions]="tooltipPositions"
            (overlayKeydown)="onOverlayKeydown($event)"
            (detach)="closeTooltip()"
        >
            <app-diff-mark-tooltip [segments]="segments()" />
        </ng-template>
    `,
    styles: [
        `
            .note-container {
                width: 100%;
                height: 100%;
                border-radius: 4px;
                box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
                display: flex;
                position: relative;
                background: transparent;
            }

            .note-container::before {
                content: '';
                position: absolute;
                inset: 0;
                border-radius: inherit;
                background: var(--note-bg);
                opacity: 0.55;
                pointer-events: none;
            }

            /* Outside the diff status outline the canvas node draws around the note (2px off its edge). */
            .note-container:focus-visible {
                outline: 2px solid var(--accent-color);
                outline-offset: 6px;
            }

            .content-container {
                position: relative;
                width: 100%;
                height: 100%;
                padding: 8px;
                overflow: auto;
                white-space: pre-wrap;
                word-break: break-word;
                color: var(--color-text-primary, #fff);
            }
        `,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class GraphNoteComponent implements AfterViewInit {
    @Input() node!: GraphNoteModel;
    /**
     * What a restore of the previewed version does to the note's text, on the Changes tab of a note a restore changes;
     * `null` anywhere else. The note shows the version text; hover and keyboard focus show the current canvas text.
     */
    readonly contentChange = input<DiffFieldMarkChange | null>(null);

    private readonly noteOrigin = viewChild.required<CdkOverlayOrigin>('noteOrigin');

    protected readonly segments = computed<DisplaySegment[]>(() => {
        const change = this.contentChange();
        return change ? fieldValueSegments('content', change.current, change.version) : [];
    });
    private readonly description = computed(() =>
        this.contentChange() === null ? null : currentValueDescription(this.segments())
    );
    protected readonly isTooltipOpen = signal(false);

    /** The description lives outside the note (as matTooltip does it); the visual tooltip is hidden from readers. */
    private readonly describesNote = effect((onCleanup) => {
        const description = this.description();
        if (description === null) return;
        const element = this.noteOrigin().elementRef.nativeElement;
        this.ariaDescriber.describe(element, description);
        onCleanup(() => this.ariaDescriber.removeDescription(element, description));
    });
    /**
     * While open, a press or a wheel anywhere closes the tooltip: either may drag or zoom the canvas, which moves the
     * note away from a tooltip that stays where it is. Capture phase, so the canvas cannot stop the event first.
     */
    private readonly closesOnCanvasMove = effect((onCleanup) => {
        if (!this.isTooltipOpen()) return;
        const close = (): void => this.closeTooltip();
        this.document.addEventListener('pointerdown', close, true);
        this.document.addEventListener('wheel', close, { capture: true, passive: true });
        onCleanup(() => {
            this.document.removeEventListener('pointerdown', close, true);
            this.document.removeEventListener('wheel', close, { capture: true });
        });
    });

    public readonly eResizeHandleType = EFResizeHandleType;
    public readonly isReadOnly = inject(FlowReadOnlyService).isReadOnly;
    protected readonly tooltipPositions = DIFF_MARK_TOOLTIP_POSITIONS;

    private readonly ariaDescriber = inject(AriaDescriber);
    private readonly focusMonitor = inject(FocusMonitor);
    private readonly document = inject(DOCUMENT);
    private readonly destroyRef = inject(DestroyRef);
    protected readonly defaultNoteColor = NOTE_COLORS[0];

    /**
     * Focus opens the tooltip only from the keyboard, as matTooltip does: a click focuses the note right after the
     * press closed the tooltip, and reopening it then would leave it behind while the note is dragged.
     */
    ngAfterViewInit(): void {
        const element = this.noteOrigin().elementRef.nativeElement;
        this.focusMonitor
            .monitor(element)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((origin) => {
                if (origin === 'keyboard') this.openTooltip();
                else if (origin === null) this.closeTooltip();
            });
        this.destroyRef.onDestroy(() => this.focusMonitor.stopMonitoring(element));
    }

    protected openTooltip(): void {
        if (this.contentChange() !== null) this.isTooltipOpen.set(true);
    }

    protected closeTooltip(): void {
        this.isTooltipOpen.set(false);
    }

    /** Esc on the focused note closes an open tooltip only; the key goes no further. */
    protected onEscape(event: Event): void {
        if (!this.isTooltipOpen()) return;
        event.stopPropagation();
        this.closeTooltip();
    }

    /** Esc anywhere while the tooltip is open: the overlay only prevents the default, so stop it here too. */
    protected onOverlayKeydown(event: KeyboardEvent): void {
        if (event.key !== 'Escape') return;
        event.stopPropagation();
        this.closeTooltip();
    }
}
