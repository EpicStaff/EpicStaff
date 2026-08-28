import { animate, style, transition, trigger } from '@angular/animations';
import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { Overlay } from '@angular/cdk/overlay';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    ElementRef,
    inject,
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
 * The canvas cannot be edited: nodes have no drag handle and are explicitly
 * drag- and selection-disabled, every connector is disabled, and no mutating
 * Foblex output is bound. The component also injects nothing that could write to
 * the canvas — no `FlowService`, no `SidePanelService`, no `HttpClient` — so the
 * read-only guarantee is structural rather than a matter of discipline.
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
         * The detail window's slide-in. `width`, not `transform: translateX` — the
         * window is a flex sibling, so translating would collapse the canvas in one
         * frame and only then slide the window into the gap.
         *
         * Declared here rather than on the window's host because this component
         * owns the `@if` and needs the `done` callback — see `onDetailSettled`.
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

    /**
     * The search panel's overlay — the only one left; the detail window is docked.
     *
     * Opened with `hasBackdrop: false`, because the two can now be open at once
     * and CDK's transparent backdrop would swallow the first click on the window.
     * See `openSearch`.
     */
    private readonly searchCtrl = new OverlayMenuController(inject(Overlay), inject(ViewContainerRef));
    private readonly destroyRef = inject(DestroyRef);

    private readonly fCanvas = viewChild(FCanvasComponent);
    private readonly fZoom = viewChild(FZoomDirective);
    private readonly searchInput = viewChild<ElementRef<HTMLInputElement>>('searchInput');
    private readonly searchTpl = viewChild.required<TemplateRef<unknown>>('searchTpl');

    /** Built once: the dialog holds a snapshot and never re-layouts. */
    protected readonly layout = layoutCdtDecisionTree(buildCdtDecisionTree(this.data));

    protected readonly legend = CDT_TREE_LEGEND;

    /**
     * The same icons the canvas blocks carry, so a legend entry is the block it
     * names rather than only its outline. Exposed as the map rather than through
     * a method so the template reads a property instead of calling on every pass.
     */
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
     * in the same pass as its blocks resolves its endpoints against a connector
     * store that is still filling up. Foblex returns null for the ones it cannot
     * find yet, draws no path, logs nothing, and never retries — `redraw()` does
     * not re-resolve them either. Filling this list only once every connector is
     * registered makes the diagram deterministic.
     *
     * It has to be an empty list rather than an `@if`: `f-canvas` projects by
     * selector with no catch-all slot, and elements inside a control-flow block
     * are dropped instead of being projected.
     */
    protected readonly visibleEdges = signal<readonly CdtTreeEdge[]>([]);

    /**
     * The filter actually applied to the canvas — what dims and highlights blocks.
     *
     * Only Save writes it. Typing writes `draftQuery`, so the diagram does not
     * move or change under a panel the user is still reading.
     */
    protected readonly query = signal('');

    /** What is typed in the dropdown. Reset to `query` when the panel is cancelled. */
    protected readonly draftQuery = signal('');

    protected readonly zoomPercent = signal(100);
    protected readonly activeMatch = signal(0);

    /**
     * Which block the detail window is showing, or null when closed. An id rather
     * than the block, so a second pick re-renders the window instead of destroying
     * it and replaying the slide-in.
     */
    private readonly selectedBlockId = signal<string | null>(null);

    protected readonly selectedBlock = computed<CdtTreePositionedBlock | null>(() => {
        const id = this.selectedBlockId();
        return id ? (this.layout.blocks.find((block) => block.id === id) ?? null) : null;
    });

    /**
     * Every block the search can offer, in reading order.
     *
     * `layout.blocks` is construction order and puts the exits before the rules.
     * The region is in no group, which keeps that titleless outline out.
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

    /**
     * Nothing but the zoom readout. This used to dismiss the anchored popover on
     * every transform, because CDK measured its anchor once at attach; a docked
     * window has no anchor to drift.
     */
    protected onCanvasChange(event: FCanvasChangeEvent): void {
        this.zoomPercent.set(Math.round(event.scale * 100));
    }

    /** Centre a block, and open its window if it is one the design lets you open. */
    private revealBlock(blockId: string): void {
        this.fCanvas()?.centerGroupOrNode(blockId, false);
        this.openDetailFor(blockId);
    }

    /**
     * Point the window at a block, or shut it if that block is not openable.
     *
     * Shutting matters for the search, which offers every block including the
     * terminators: leaving the window alone would centre on the picked block while
     * still describing the previous one.
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
     * Typing narrows the panel and nothing else — the canvas moves only when the
     * filter is applied or a block is picked.
     *
     * Enter applies it, and that is the whole keyboard path: CDK traps focus in
     * `cdk-dialog-container` and the panel is a sibling overlay outside the trap,
     * so Tab never reaches Save.
     */
    protected onQueryInput(event: Event): void {
        this.draftQuery.set((event.target as HTMLInputElement).value);
        this.openSearch();
    }

    protected openSearch(): void {
        const anchor = this.searchInput()?.nativeElement;
        if (!anchor) return;

        // The detail window is left open — docked, it is part of the dialog like
        // the toolbar is, and searching is no reason to throw away the block being
        // read. `hasBackdrop: false` is what makes that safe: with a backdrop the
        // first click on the open window would only dismiss this panel.
        this.searchCtrl.open(anchor, this.searchTpl(), {
            panelClass: 'cdt-tree-search',
            offsetY: 8,
            hasBackdrop: false,
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

    /** Clear Filter: empty the box. The canvas follows on Save. */
    protected clearSearch(): void {
        this.draftQuery.set('');
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
     * the whole diagram would work too, but would throw away the zoom the user
     * arrived with. On close there is no selection and the viewport only grows.
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
            searchOpen: this.searchCtrl.isOpen(),
            // The box holds the draft, so that is what `clear-search` empties and
            // therefore what decides whether there is anything to clear. Reading
            // the applied filter here made Escape clear an already-empty box for
            // ever and never reach the dialog.
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
