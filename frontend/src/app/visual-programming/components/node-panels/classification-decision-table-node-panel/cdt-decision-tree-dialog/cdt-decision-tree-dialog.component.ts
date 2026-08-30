import { animate, style, transition, trigger } from '@angular/animations';
import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { Overlay } from '@angular/cdk/overlay';
import {
    afterNextRender,
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    ElementRef,
    inject,
    Injector,
    signal,
    TemplateRef,
    viewChild,
    ViewContainerRef,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { EFMarkerType, FCanvasChangeEvent, FCanvasComponent, FFlowModule, FZoomDirective } from '@foblex/flow';

import { AppSvgIconComponent } from '../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { filterByQuery } from '../cdt-search-filter.util';
import { OverlayMenuController } from '../classification-decision-table-grid/shared/overlay-menu.util';
import { buildCdtDecisionTree } from './cdt-decision-tree.builder';
import {
    CDT_TREE_EDGE_OFFSET,
    CDT_TREE_FIT_PADDING,
    CDT_TREE_LEGEND,
    ICON_BY_SHAPE,
} from './cdt-decision-tree.constants';
import { layoutCdtDecisionTree } from './cdt-decision-tree.layout';
import { CdtDecisionTreeInput, CdtTreeEdge, CdtTreePositionedBlock } from './cdt-decision-tree.model';
import { CdtDecisionTreeBlockComponent } from './cdt-decision-tree-block/cdt-decision-tree-block.component';
import { CdtDecisionTreeDetailComponent } from './cdt-decision-tree-detail/cdt-decision-tree-detail.component';
import { resolveTreeKeyAction } from './cdt-decision-tree-keyboard.util';
import { CdtDecisionTreeSearchComponent } from './cdt-decision-tree-search/cdt-decision-tree-search.component';
import { CdtDecisionTreeShapeComponent } from './cdt-decision-tree-shape/cdt-decision-tree-shape.component';

/**
 * Read-only flowchart of a Classification Decision Table node.
 *
 * The read-only guarantee is structural: nodes are drag- and selection-disabled,
 * no mutating Foblex output is bound, and nothing that could write to the canvas
 * is injected — no `FlowService`, no `SidePanelService`, no `HttpClient`.
 */
@Component({
    selector: 'app-cdt-decision-tree-dialog',
    standalone: true,
    imports: [
        FFlowModule,
        FZoomDirective,
        AppSvgIconComponent,
        CdtDecisionTreeBlockComponent,
        CdtDecisionTreeShapeComponent,
        CdtDecisionTreeSearchComponent,
        CdtDecisionTreeDetailComponent,
    ],
    templateUrl: './cdt-decision-tree-dialog.component.html',
    styleUrls: ['./cdt-decision-tree-dialog.component.scss'],
    animations: [
        /**
         * The detail window's slide-in. `width`, not `transform: translateX`: the
         * window is a flex sibling, so translating would collapse the canvas in one
         * frame and only then slide the window into the gap. Declared here because
         * this component owns the `@if` and needs the `done` callback.
         */
        trigger('panelSlide', [
            transition(':enter', [style({ width: '0' }), animate('200ms ease-out', style({ width: '*' }))]),
            transition(':leave', [animate('160ms ease-in', style({ width: '0' }))]),
        ]),
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CdtDecisionTreeDialogComponent {
    private readonly dialogRef = inject<DialogRef<void>>(DialogRef);
    private readonly data = inject<CdtDecisionTreeInput>(DIALOG_DATA);

    /** The search panel's overlay; the detail window is docked, not overlaid. */
    private readonly searchCtrl = new OverlayMenuController(inject(Overlay), inject(ViewContainerRef));
    private readonly destroyRef = inject(DestroyRef);
    private readonly injector = inject(Injector);

    private readonly fCanvas = viewChild(FCanvasComponent);
    private readonly fZoom = viewChild(FZoomDirective);
    private readonly searchInput = viewChild<ElementRef<HTMLInputElement>>('searchInput');
    private readonly searchToggle = viewChild<ElementRef<HTMLButtonElement>>('searchToggle');
    /** The box, so the dropdown under it lines up with its edges. */
    private readonly searchBox = viewChild<ElementRef<HTMLElement>>('searchBox');
    private readonly searchTpl = viewChild.required<TemplateRef<unknown>>('searchTpl');

    /** Built once: the dialog holds a snapshot and never re-layouts. */
    protected readonly layout = layoutCdtDecisionTree(buildCdtDecisionTree(this.data));

    protected readonly legend = CDT_TREE_LEGEND;

    /** The same icons the canvas blocks carry, so a legend entry is its block. */
    protected readonly iconByShape = ICON_BY_SHAPE;

    protected readonly eMarkerType = EFMarkerType;

    /**
     * How far an edge runs straight out of a connector before it may turn.
     *
     * The layout places the exit columns using the same number, so the drop into
     * them is one straight line rather than a step.
     */
    protected readonly edgeOffset = CDT_TREE_EDGE_OFFSET;

    /** `fDraggable` is present only so the canvas can be panned. */
    protected readonly canvasMoveTrigger = (): boolean => true;

    /**
     * Edges are added one pass after the blocks.
     *
     * `f-canvas` projects connections before nodes, so an `f-connection` created
     * alongside its blocks resolves its endpoints against a connector store that is
     * still filling up: Foblex draws no path, logs nothing, and never retries —
     * `redraw()` does not re-resolve them either.
     *
     * An empty list rather than an `@if`, because `f-canvas` projects by selector
     * with no catch-all slot and drops elements inside a control-flow block.
     */
    protected readonly visibleEdges = signal<readonly CdtTreeEdge[]>([]);

    /**
     * The filter applied to the canvas — what dims and highlights blocks. Typing
     * writes `draftQuery` instead, so the diagram does not move under a panel the
     * user is still reading.
     */
    protected readonly query = signal('');

    /** What is typed in the dropdown. Reset to `query` when the panel is cancelled. */
    protected readonly draftQuery = signal('');

    /**
     * Whether the search box is showing. Collapsed, the toolbar carries only the
     * 28px icon button; expanded, the button goes accent and the box appears beside
     * it with the dropdown under it.
     */
    protected readonly searchExpanded = signal(false);

    protected readonly zoomPercent = signal(100);
    protected readonly activeMatch = signal(0);

    /**
     * Which block the detail window is showing. An id rather than the block, so a
     * second pick re-renders the window instead of replaying the slide-in.
     */
    private readonly selectedBlockId = signal<string | null>(null);

    protected readonly selectedBlock = computed<CdtTreePositionedBlock | null>(() => {
        const id = this.selectedBlockId();
        return id ? (this.layout.blocks.find((block) => block.id === id) ?? null) : null;
    });

    /**
     * Every block the search can offer, in reading order — `layout.blocks` is
     * construction order and puts the exits before the rules.
     */
    private readonly orderedBlocks = computed<CdtTreePositionedBlock[]>(() => {
        const byId = new Map(this.layout.blocks.map((block) => [block.id, block]));
        return this.layout.groups.flatMap((group) =>
            group.blockIds.map((id) => byId.get(id)).filter((block): block is CdtTreePositionedBlock => !!block)
        );
    });

    protected readonly matchIds = computed<string[]>(() => {
        const query = this.query().trim();
        if (!query) return [];
        return filterByQuery(this.orderedBlocks(), query, (block) => block.searchText).map((block) => block.id);
    });

    private readonly matchSet = computed(() => new Set(this.matchIds()));

    protected readonly hasQuery = computed(() => this.query().trim().length > 0);

    constructor() {
        // The dialog is opened with `disableClose`, so CDK closes it for neither
        // the backdrop nor Escape — both are ours to handle.
        this.dialogRef.backdropClick.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => this.close());

        // CDK dispatches `keydownEvents` from a bubble-phase listener on
        // `document.body`, which is early enough to preempt the flow page's own
        // `document` and `window` shortcut handlers, and late enough that a block
        // has already handled its own Enter or Space. See `resolveTreeKeyAction`.
        this.dialogRef.keydownEvents
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((event) => this.onKeydown(event));

        // The search panel lives in its own overlay, outside this component's view,
        // so it has to be torn down explicitly. The detail window does not — it is
        // in this template and goes with it.
        this.destroyRef.onDestroy(() => this.searchCtrl.dispose());
    }

    // -- canvas --------------------------------------------------------------

    protected onFlowLoaded(): void {
        // A macrotask after `fLoaded`, so the blocks' connectors are registered
        // and Foblex's first connection pass is done before the edges exist —
        // see `visibleEdges`.
        setTimeout(() => {
            this.visibleEdges.set(this.layout.edges);

            // And one more, mirroring the main canvas: Foblex needs the nodes
            // laid out in the DOM before it can measure them.
            setTimeout(() => {
                const canvas = this.fCanvas();
                if (!canvas) return;
                canvas.fitToScreen(CDT_TREE_FIT_PADDING, false);
                this.zoomPercent.set(Math.round(canvas.getScale() * 100));
            }, 0);
        }, 0);
    }

    protected onCanvasChange(event: FCanvasChangeEvent): void {
        this.zoomPercent.set(Math.round(event.scale * 100));
    }

    /** Centre a block, and open its window if it is one the design lets you open. */
    private revealBlock(blockId: string): void {
        this.fCanvas()?.centerGroupOrNode(blockId, false);
        this.openDetailFor(blockId);
    }

    /**
     * Point the window at a block, or shut it if that block is not openable — the
     * search offers the terminators too, and a stale window would describe the
     * previously picked block while the canvas centred on this one.
     */
    private openDetailFor(blockId: string): void {
        const block = this.layout.blocks.find((entry) => entry.id === blockId);
        // `clickable` already folds in "has something to show" — see the builder.
        this.selectedBlockId.set(block?.clickable ? blockId : null);
    }

    protected zoomIn(): void {
        this.fZoom()?.zoomIn();
    }

    protected zoomOut(): void {
        this.fZoom()?.zoomOut();
    }

    protected resetZoom(): void {
        this.fCanvas()?.setScale(1);
        this.zoomPercent.set(100);
    }

    protected fit(): void {
        this.fCanvas()?.fitToScreen(CDT_TREE_FIT_PADDING, true);
    }

    // -- search --------------------------------------------------------------

    /**
     * Typing narrows the panel and nothing else; the canvas moves only on Save or
     * on a pick. Enter applies it, and that is the whole keyboard path: the panel
     * is a sibling overlay outside CDK's focus trap, so Tab never reaches Save.
     */
    protected onQueryInput(event: Event): void {
        this.draftQuery.set((event.target as HTMLInputElement).value);
        this.openSearch();
    }

    /**
     * The icon button always moves towards "search visible", and dismisses only
     * from the fully open state: it reveals the box with its dropdown, reopens a
     * dropdown that was cancelled, and collapses everything on the press after.
     *
     * Reading `isOpen()` here is only reliable because the button is passed as
     * `ignoreOutsideFor`, so the panel has not already closed itself by click time.
     *
     * Collapsing clears the applied filter as well as the draft: the filter dims
     * every non-matching block, and leaving it on with no box to see it in would
     * dim the canvas with nothing in the toolbar explaining why.
     */
    protected toggleSearch(): void {
        if (!this.searchExpanded()) {
            this.searchExpanded.set(true);
            // The box is inside an `@if`, so neither it nor the input exists until
            // the next render.
            afterNextRender(() => this.focusAndOpenSearch(), { injector: this.injector });
            return;
        }

        if (!this.searchCtrl.isOpen()) {
            this.focusAndOpenSearch();
            return;
        }

        this.collapseSearch();
    }

    protected collapseSearch(): void {
        this.searchCtrl.close();
        this.searchExpanded.set(false);
        this.draftQuery.set('');
        this.query.set('');
        this.activeMatch.set(0);
        // The input is inside the `@if` above and has just been destroyed: without
        // this, focus falls to `<body>`, outside the dialog's focus trap, and the
        // next Tab lands on the flow page behind the modal.
        this.searchToggle()?.nativeElement.focus();
    }

    private focusAndOpenSearch(): void {
        this.searchInput()?.nativeElement.focus();
        this.openSearch();
    }

    protected openSearch(): void {
        // The box, not the input: the dropdown is the box's width, so anchoring to
        // the input would leave it offset by the box's padding.
        const anchor = this.searchBox()?.nativeElement ?? this.searchInput()?.nativeElement;
        if (!anchor) return;

        const toggle = this.searchToggle()?.nativeElement;

        this.searchCtrl.open(anchor, this.searchTpl(), {
            offsetY: 8,
            // The toolbar clips before the box does, and the pane sits in a `fixed`
            // container that clips at nothing: aligning to the box's right edge
            // would put the dropdown under an edge the user cannot see, off beside
            // the visible input. Its left edge is always on screen.
            alignX: 'start',
            // What CDK shrinks the panel to fit inside, so its footer stays on
            // screen on a short viewport instead of being cut off — see the panel's
            // own `max-height`.
            viewportMargin: 12,
            // The detail window is left open: docked, it is part of the dialog, and
            // searching is no reason to throw away the block being read. A backdrop
            // would make the first click on that window only dismiss this panel.
            hasBackdrop: false,
            // The toggle owns its own open/close and must not read as an outside
            // click — see `toggleSearch`.
            ignoreOutsideFor: toggle ? [toggle] : [],
        });
    }

    protected isSearchOpen(): boolean {
        return this.searchCtrl.isOpen();
    }

    /** Jump to a block and open it; centre only, when there is nothing to open. */
    protected onSearchPick(blockId: string): void {
        this.searchCtrl.close();
        this.revealBlock(blockId);
    }

    /** Save: what is typed becomes the filter the canvas is drawn with. */
    protected applySearch(): void {
        this.query.set(this.draftQuery());
        this.activeMatch.set(0);
        this.searchCtrl.close();
        // Otherwise the toolbar reads `1 / N` over a canvas that never moved, and
        // the first `›` steps to the second match.
        this.revealActiveMatch();
    }

    /** Cancel: leave the canvas as it was, and forget what was typed. */
    protected cancelSearch(): void {
        this.draftQuery.set(this.query());
        this.searchCtrl.close();
    }

    /**
     * Clear Filter: empty the box and drop the filter the canvas is drawn with.
     *
     * Both, not just the draft — otherwise a button labelled "Clear Filter" leaves
     * the canvas dimmed with a `3 / 7` counter standing over an empty box.
     */
    protected clearSearch(): void {
        this.draftQuery.set('');
        this.query.set('');
        this.activeMatch.set(0);
        this.searchInput()?.nativeElement.focus();
    }

    protected stepMatch(delta: number): void {
        const total = this.matchIds().length;
        if (total === 0) return;
        this.activeMatch.update((current) => (current + delta + total) % total);
        this.revealActiveMatch();
    }

    protected isDimmed(blockId: string): boolean {
        return this.hasQuery() && !this.matchSet().has(blockId);
    }

    protected isMatched(blockId: string): boolean {
        return this.hasQuery() && this.matchSet().has(blockId);
    }

    private revealActiveMatch(): void {
        const id = this.matchIds()[this.activeMatch()];
        if (id) this.fCanvas()?.centerGroupOrNode(id, true);
    }

    // -- detail window -------------------------------------------------------

    /** Clicking a second block swaps the open window's contents rather than reopening it. */
    protected openDetail(block: CdtTreePositionedBlock): void {
        if (!block.clickable || !block.detail) return;
        this.selectedBlockId.set(block.id);
    }

    protected closeDetail(): void {
        this.selectedBlockId.set(null);
    }

    /**
     * Re-centre the selected block once the window has finished sliding: opening it
     * narrows the canvas and can push the just-clicked block out of view. Fitting
     * the diagram instead would throw away the zoom the user arrived with.
     */
    protected onDetailSettled(): void {
        const id = this.selectedBlockId();
        if (id) this.fCanvas()?.centerGroupOrNode(id, true);
    }

    // -- keyboard ------------------------------------------------------------

    /**
     * Has to stay synchronous — see the module comment on `resolveTreeKeyAction`
     * for why an async operator here would silently void `stopPropagation`.
     */
    private onKeydown(event: KeyboardEvent): void {
        const result = resolveTreeKeyAction(event, {
            detailOpen: this.selectedBlockId() !== null,
            searchExpanded: this.searchExpanded(),
            searchOpen: this.searchCtrl.isOpen(),
            // The draft, not the applied filter: that is what the box shows and
            // what `clear-search` empties. Reading the filter here made Escape clear
            // an already-empty box for ever and never reach the dialog.
            searchHasText: this.draftQuery().trim().length > 0,
            targetIsSearch: event.target === this.searchInput()?.nativeElement,
        });

        if (result.stopPropagation) event.stopPropagation();
        if (result.preventDefault) event.preventDefault();

        switch (result.action) {
            case 'close-detail':
                this.closeDetail();
                break;
            case 'close-search':
                this.cancelSearch();
                break;
            case 'clear-search':
                this.clearSearch();
                break;
            case 'collapse-search':
                this.collapseSearch();
                break;
            case 'close-dialog':
                this.close();
                break;
            case 'none':
                break;
        }
    }

    protected close(): void {
        this.dialogRef.close();
    }
}
