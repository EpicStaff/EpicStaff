import {
    afterNextRender,
    afterRenderEffect,
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    effect,
    ElementRef,
    inject,
    input,
    NgZone,
    output,
    signal,
    viewChild,
} from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';

import { AppSvgIconComponent } from '../../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { CopyButtonComponent } from '../../../../../../shared/components/copy-button/copy-button.component';
import { CDT_TREE_COPY } from '../cdt-decision-tree.constants';
import { CdtTreeBlock } from '../cdt-decision-tree.model';
import { CdtDecisionTreeCodeComponent } from '../cdt-decision-tree-code/cdt-decision-tree-code.component';
import { codeBlockHeight, isScrolledToEnd } from '../cdt-detail-geometry.util';
import { CdtExplanationState } from '../cdt-explain.model';

/** Set on the body; read by the code block for its height. */
const CODE_BLOCK_HEIGHT_PROPERTY = '--cdt-code-block-height';

/** On the body while it is scrolled to its end: the code block may scroll then. */
const AT_END_CLASS = 'cdt-tree-detail__body--at-end';

/**
 * The read-only detail window for one block of the decision tree.
 *
 * Presentational: takes a block, renders what it already carries, emits when it
 * wants closing.
 *
 * Docked beside the canvas rather than anchored to the block, which is what lets
 * a second click swap its contents instead of tearing the window down — the
 * dialog keeps the selected id and this component just re-renders.
 */
@Component({
    selector: 'app-cdt-decision-tree-detail',
    standalone: true,
    imports: [AppSvgIconComponent, CopyButtonComponent, MatTooltipModule, CdtDecisionTreeCodeComponent],
    templateUrl: './cdt-decision-tree-detail.component.html',
    styleUrls: ['./cdt-decision-tree-detail.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CdtDecisionTreeDetailComponent {
    /** Only openable blocks reach this component, so `detail` is always present. */
    public readonly block = input.required<CdtTreeBlock>();

    /**
     * The explanation of the block being shown, or null when none was asked for.
     *
     * Owned by the dialog: this component's instance outlives a switch between
     * blocks, so anything kept here would survive into the next block's window.
     */
    public readonly explanation = input<CdtExplanationState | null>(null);

    /**
     * Whether the Explain control is shown at all. False in a read-only editor,
     * which can read stored explanations but not generate them. Required, so no
     * caller gets the control by default.
     */
    public readonly explainOffered = input.required<boolean>();

    /**
     * Whether this block can be explained at all. False for the one clickable
     * block that has nothing to send — a prompt step whose config went missing.
     */
    public readonly explainAvailable = input<boolean>(true);

    /** Whether the model picker is showing, so the chevron can say so. */
    public readonly explainMenuOpen = input<boolean>(false);

    /**
     * Said here as well as on the canvas marker: this is where the text is read,
     * and a reader who opened the block from the search panel never saw the marker.
     */
    public readonly outdated = input<boolean>(false);

    public readonly closed = output<void>();
    public readonly explainRequested = output<void>();
    /**
     * The chevron element, so the dialog can anchor the picker to it. The button
     * lives here; the options and the overlay do not.
     */
    public readonly explainMenuRequested = output<HTMLElement>();

    /** The window's scroller, which starts at the top for every block. */
    private readonly body = viewChild.required<ElementRef<HTMLElement>>('body');

    /** Its height is the scroll range, and it changes: async text, collapse. */
    private readonly explanationSection = viewChild.required<ElementRef<HTMLElement>>('explanationSection');

    /** The code section: its bottom padding is the gap left under the code block. */
    private readonly codeSection = viewChild<ElementRef<HTMLElement>>('codeSection');

    /** The code block, sized to reach that gap above the window's bottom edge. */
    private readonly code = viewChild(CdtDecisionTreeCodeComponent);

    /**
     * The block's host, watched for size: its top padding animates in when the code
     * section reopens, moving the block down after the height was last measured.
     */
    private readonly codeHost = viewChild(CdtDecisionTreeCodeComponent, { read: ElementRef });

    protected readonly copy = CDT_TREE_COPY;

    /** Both start open: the window exists to show them. */
    protected readonly explanationOpen = signal(true);
    protected readonly dataOpen = signal(true);

    /** Unpacked into three narrow reads, so the narrowing stays in TypeScript. */
    protected readonly explanationLoading = computed(() => this.explanation()?.status === 'loading');

    protected readonly explanationReady = computed(() => {
        const state = this.explanation();
        return state?.status === 'ready' ? state : null;
    });

    protected readonly explanationError = computed(() => {
        const state = this.explanation();
        return state?.status === 'error' ? state.message : null;
    });

    /**
     * The id rather than the block: the dialog can hand over a fresh object for the
     * same block, and that must not throw the reader back to the top.
     */
    private readonly blockId = computed(() => this.block().id);

    /**
     * A second click swaps the contents without re-creating this component, so the
     * scroll position would otherwise carry over to a block it was never about.
     * Runs after render, and only when the id changes — never per scroll event.
     */
    private readonly resetScrollOnBlockChange = afterRenderEffect({
        write: () => {
            this.blockId();
            this.body().nativeElement.scrollTop = 0;
        },
    });

    /**
     * Opening or shutting the code section, or showing another block, changes the
     * geometry without necessarily scrolling, so it asks for a recompute too.
     */
    private readonly remeasureOnLayoutChange = effect(() => {
        this.dataOpen();
        this.blockId();
        this.scheduleGeometryUpdate();
    });

    private readonly zone = inject(NgZone);
    private readonly destroyRef = inject(DestroyRef);

    /** Whether the listeners are attached. Before and after, nothing is measured. */
    private listening = false;
    /** The pending animation frame, or 0: at most one geometry write per frame. */
    private frame = 0;
    /** Whether the window was at its end at the last write. */
    private atEnd = false;
    /** One reference, so the same listener can be removed again. */
    private readonly onGeometryChange = (): void => this.scheduleGeometryUpdate();

    constructor() {
        afterNextRender(() => this.zone.runOutsideAngular(() => this.trackCodeBlockGeometry()));
    }

    protected onMenuClick(event: MouseEvent): void {
        this.explainMenuRequested.emit(event.currentTarget as HTMLElement);
    }

    protected toggleExplanation(): void {
        this.explanationOpen.update((open) => !open);
    }

    protected toggleData(): void {
        this.dataOpen.update((open) => !open);
    }

    /**
     * Keeps the code block's bottom edge a section's padding above the window's
     * bottom edge, and lets the block scroll only once the window has reached its end.
     *
     * Outside Angular and passive: the listener only writes a custom property and a
     * class, never state, so a scroll triggers no change detection. Remeasured on
     * scroll; on a resize of the window, of Explanation (its text arrives late; it
     * collapses) or of the block's host; and on the layout changes the effect above
     * reports.
     *
     * Watching the host cannot loop. The height written depends only on where the
     * block starts — the host's top plus its padding — never on the block's own
     * height, so the write a host resize triggers is followed by at most one more,
     * which writes the same value and resizes nothing.
     */
    private trackCodeBlockGeometry(): void {
        const body = this.body().nativeElement;
        this.listening = true;

        // Synchronously for the first paint, so the block never shows at its natural
        // height for a frame before settling above the window's edge.
        this.updateGeometry();

        body.addEventListener('scroll', this.onGeometryChange, { passive: true });
        const resizeObserver = new ResizeObserver(this.onGeometryChange);
        resizeObserver.observe(body);
        resizeObserver.observe(this.explanationSection().nativeElement);

        // Observed once: only blocks with code are clickable (`clickable` requires
        // `detail !== null` in cdt-decision-tree.builder.ts), so the `@if` around the
        // code section never drops its view and this host lives as long as the component.
        const host = this.codeHost()?.nativeElement;
        if (host) resizeObserver.observe(host, { box: 'border-box' });

        this.destroyRef.onDestroy(() => {
            this.listening = false;
            body.removeEventListener('scroll', this.onGeometryChange);
            resizeObserver.disconnect();
            cancelAnimationFrame(this.frame);
            this.frame = 0;
        });
    }

    private scheduleGeometryUpdate(): void {
        if (!this.listening || this.frame) return;

        // The effect calls in from inside Angular; the frame must not run there.
        this.zone.runOutsideAngular(() => {
            this.frame = requestAnimationFrame(() => this.updateGeometry());
        });
    }

    /**
     * The height is written whether the code section is open or shut. Shut, the
     * collapsed row hides it; while the collapse runs, it is what `grid-collapsible`
     * animates from, so the sweep starts at exactly the block the reader sees rather
     * than at the whole of the code.
     *
     * Leaving the end sends the code back to its first line: its scroller is about
     * to stop answering, and a block left halfway down would hide line 1 with no way
     * to reach it until the window was scrolled back to the end.
     */
    private updateGeometry(): void {
        this.frame = 0;
        const body = this.body().nativeElement;
        const block = this.code()?.blockElement();
        const section = this.codeSection()?.nativeElement;

        if (block && section) {
            const height = codeBlockHeight({
                viewportTop: body.getBoundingClientRect().top,
                viewportHeight: body.clientHeight,
                blockTop: block.getBoundingClientRect().top,
                // Read from the section rather than restated here, so the gap is the
                // padding the stylesheet actually gives it.
                bottomGap: parseFloat(getComputedStyle(section).paddingBottom) || 0,
            });
            body.style.setProperty(CODE_BLOCK_HEIGHT_PROPERTY, `${height}px`);
        }

        const nowAtEnd = isScrolledToEnd(body);
        if (this.atEnd && !nowAtEnd) this.code()?.scrollToTop();
        this.atEnd = nowAtEnd;
        body.classList.toggle(AT_END_CLASS, nowAtEnd);
    }
}
