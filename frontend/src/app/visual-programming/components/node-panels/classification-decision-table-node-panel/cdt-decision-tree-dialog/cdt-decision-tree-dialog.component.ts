import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { Overlay } from '@angular/cdk/overlay';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    ElementRef,
    inject,
    OnDestroy,
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
import { CDT_TREE_FIT_PADDING, CDT_TREE_LEGEND } from './cdt-decision-tree.constants';
import { layoutCdtDecisionTree } from './cdt-decision-tree.layout';
import { CdtDecisionTreeInput, CdtTreeDetail, CdtTreeEdge, CdtTreePositionedBlock } from './cdt-decision-tree.model';
import { CdtDecisionTreeBlockComponent } from './cdt-decision-tree-block/cdt-decision-tree-block.component';
import { resolveTreeKeyAction } from './cdt-decision-tree-keyboard.util';
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
    ],
    templateUrl: './cdt-decision-tree-dialog.component.html',
    styleUrls: ['./cdt-decision-tree-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CdtDecisionTreeDialogComponent implements OnDestroy {
    private readonly dialogRef = inject<DialogRef<void>>(DialogRef);
    private readonly data = inject<CdtDecisionTreeInput>(DIALOG_DATA);
    private readonly detailCtrl = new OverlayMenuController(inject(Overlay), inject(ViewContainerRef));
    private readonly destroyRef = inject(DestroyRef);

    private readonly fCanvas = viewChild(FCanvasComponent);
    private readonly fZoom = viewChild(FZoomDirective);
    private readonly searchInput = viewChild<ElementRef<HTMLInputElement>>('searchInput');
    private readonly detailTpl = viewChild.required<TemplateRef<unknown>>('detailTpl');

    /** Built once: the dialog holds a snapshot and never re-layouts. */
    protected readonly layout = layoutCdtDecisionTree(buildCdtDecisionTree(this.data));

    protected readonly legend = CDT_TREE_LEGEND;
    protected readonly eMarkerType = EFMarkerType;

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

    protected readonly query = signal('');
    protected readonly zoomPercent = signal(100);
    protected readonly detail = signal<CdtTreeDetail | null>(null);
    protected readonly activeMatch = signal(0);

    protected readonly matchIds = computed<string[]>(() => {
        const query = this.query().trim();
        if (!query) return [];
        return filterByQuery(this.layout.blocks, query, (block) => block.searchText).map((block) => block.id);
    });

    private readonly matchSet = computed(() => new Set(this.matchIds()));

    protected readonly hasQuery = computed(() => this.query().trim().length > 0);

    constructor() {
        // CDK dispatches `keydownEvents` from a bubble-phase listener on
        // `document.body`, which is early enough to preempt the flow page's own
        // `document` and `window` shortcut handlers, and late enough that a block
        // has already handled its own Enter or Space. See `resolveTreeKeyAction`.
        this.dialogRef.keydownEvents
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((event) => this.onKeydown(event));
    }

    public ngOnDestroy(): void {
        this.detailCtrl.dispose();
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
        // The default `close()` scroll strategy never fires for a canvas
        // transform, so the popover would drift away from its anchor.
        this.closeDetail();
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

    protected onQueryInput(event: Event): void {
        this.query.set((event.target as HTMLInputElement).value);
        this.activeMatch.set(0);
        this.revealActiveMatch();
    }

    protected clearSearch(): void {
        this.query.set('');
        this.activeMatch.set(0);
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

    // -- popover -------------------------------------------------------------

    protected openDetail(anchor: HTMLElement, block: CdtTreePositionedBlock): void {
        if (!block.detail) return;
        this.detailCtrl.close();
        this.detail.set(block.detail);
        this.detailCtrl.open(anchor, this.detailTpl(), { panelClass: 'cdt-tree-detail', offsetY: 8 });
    }

    protected closeDetail(): void {
        if (!this.detailCtrl.isOpen()) return;
        this.detailCtrl.close();
        this.detail.set(null);
    }

    // -- keyboard ------------------------------------------------------------

    /**
     * Has to stay synchronous — see the module comment on `resolveTreeKeyAction`
     * for why an async operator here would silently void `stopPropagation`.
     */
    private onKeydown(event: KeyboardEvent): void {
        const result = resolveTreeKeyAction(event, {
            popoverOpen: this.detailCtrl.isOpen(),
            searchHasText: this.hasQuery(),
            targetIsSearch: event.target === this.searchInput()?.nativeElement,
        });

        if (result.stopPropagation) event.stopPropagation();
        if (result.preventDefault) event.preventDefault();

        switch (result.action) {
            case 'close-popover':
                this.closeDetail();
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
