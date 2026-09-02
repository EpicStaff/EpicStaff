import { animate, style, transition, trigger } from '@angular/animations';
import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { Overlay } from '@angular/cdk/overlay';
import { HttpErrorResponse } from '@angular/common/http';
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
import { CheckboxComponent } from '@shared/components';
import { concatMap, from, map, Subject, takeUntil } from 'rxjs';

import { AppSvgIconComponent } from '../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { CdtExplainService } from '../../../../services/cdt-explain.service';
import { CdtExplanationStoreService } from '../../../../services/cdt-explanation-store.service';
import { filterByQuery } from '../cdt-search-filter.util';
import { OverlayMenuController } from '../classification-decision-table-grid/shared/overlay-menu.util';
import { buildCdtDecisionTree } from './cdt-decision-tree.builder';
import {
    CDT_TREE_COPY,
    CDT_TREE_EDGE_LABEL_OFFSET,
    CDT_TREE_EDGE_OFFSET,
    CDT_TREE_FIT_PADDING,
    CDT_TREE_LEGEND,
    ICON_BY_SHAPE,
} from './cdt-decision-tree.constants';
import { layoutCdtDecisionTree } from './cdt-decision-tree.layout';
import { CdtDecisionTreeInput, CdtTreeEdge, CdtTreeLlmOption, CdtTreePositionedBlock } from './cdt-decision-tree.model';
import { CdtDecisionTreeBlockComponent } from './cdt-decision-tree-block/cdt-decision-tree-block.component';
import { CdtDecisionTreeDetailComponent } from './cdt-decision-tree-detail/cdt-decision-tree-detail.component';
import { resolveTreeKeyAction } from './cdt-decision-tree-keyboard.util';
import { CdtDecisionTreeSearchComponent } from './cdt-decision-tree-search/cdt-decision-tree-search.component';
import { CdtDecisionTreeShapeComponent } from './cdt-decision-tree-shape/cdt-decision-tree-shape.component';
import { buildExplainStepKeys, explainStepFingerprint } from './cdt-explain.identity';
import { CdtExplainBlock, CdtExplainResponse, CdtExplanationState } from './cdt-explain.model';
import {
    buildCdtExplainBlocks,
    buildCdtExplainTable,
    chunkExplainBlocks,
    resolveExplainLlmConfig,
} from './cdt-explain.payload';

/**
 * Keyed on the backend's error codes, not the status. Neither is handled by an
 * interceptor: `forbidden` covers 403 and `validation-errors` only annotates 4xx.
 */
function explainErrorMessage(error: HttpErrorResponse): string {
    const code: unknown = (error.error as { code?: unknown } | null)?.code;

    if (code === 'cdt_explain_llm_config_not_found') return CDT_TREE_COPY.explainModelGone;
    if (code === 'cdt_explain_upstream_failed') return CDT_TREE_COPY.explainUpstreamFailed;
    return CDT_TREE_COPY.explainFailed;
}

/**
 * Read-only flowchart of a Classification Decision Table node.
 *
 * The diagram is read-only, and structurally so: nodes are drag- and
 * selection-disabled, no mutating Foblex output is bound, and neither `FlowService`
 * nor `SidePanelService` is injected, so no code path here can move a node, touch a
 * connection or edit a table.
 *
 * The one thing it writes is an explanation, only through
 * `CdtExplanationStoreService`. That write lands on the node's metadata and marks
 * the canvas dirty — see the store for why that trade is intended.
 */
@Component({
    selector: 'app-cdt-decision-tree-dialog',
    standalone: true,
    imports: [
        FFlowModule,
        FZoomDirective,
        AppSvgIconComponent,
        CheckboxComponent,
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

    /**
     * The search panel's overlay. Mutually exclusive with the model picker only
     * because `openSearch` and `openExplainMenu` stand each other down — both
     * hang off the toolbar, so nothing structural separates them.
     */
    private readonly searchCtrl = new OverlayMenuController(inject(Overlay), inject(ViewContainerRef));
    /** The model picker's overlay. One controller holds one pane, hence two. */
    private readonly explainMenuCtrl = new OverlayMenuController(inject(Overlay), inject(ViewContainerRef));
    private readonly destroyRef = inject(DestroyRef);
    private readonly injector = inject(Injector);
    private readonly explainService = inject(CdtExplainService);

    private readonly fCanvas = viewChild(FCanvasComponent);
    private readonly fZoom = viewChild(FZoomDirective);
    private readonly searchInput = viewChild<ElementRef<HTMLInputElement>>('searchInput');
    private readonly searchToggle = viewChild<ElementRef<HTMLButtonElement>>('searchToggle');
    /** The box, so the dropdown under it lines up with its edges. */
    private readonly searchBox = viewChild<ElementRef<HTMLElement>>('searchBox');
    private readonly searchTpl = viewChild.required<TemplateRef<unknown>>('searchTpl');
    private readonly explainMenuTpl = viewChild.required<TemplateRef<unknown>>('explainMenuTpl');

    /** Built once: the dialog holds a snapshot and never re-layouts. */
    protected readonly layout = layoutCdtDecisionTree(buildCdtDecisionTree(this.data));

    /**
     * Every explainable step, keyed by block id. Built once from the same snapshot
     * as `layout`. Not every clickable block is here — a prompt block whose config
     * is missing has nothing to explain.
     */
    private readonly explainBlocks = buildCdtExplainBlocks(this.data);
    private readonly explainTable = buildCdtExplainTable(this.data);

    /**
     * Block id → the identity its explanation is filed under, and → what the step
     * currently looks like. Fixed for a sitting: the snapshot cannot change.
     */
    private readonly explainStepKeys = buildExplainStepKeys(this.data);

    private readonly explainFingerprints = new Map<string, string>(
        [...this.explainBlocks].map(([id, block]) => [id, explainStepFingerprint(block)])
    );

    /**
     * Declared after the keys above because it is handed the set of them, which is
     * what tells the store which entries on the node are still real.
     */
    private readonly explanationStore = inject(CdtExplanationStoreService).forNode({
        nodeId: this.data.nodeId,
        backendId: this.data.backendId,
        liveStepKeys: new Set(this.explainStepKeys.values()),
    });

    protected readonly legend = CDT_TREE_LEGEND;
    protected readonly copy = CDT_TREE_COPY;

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

    /** Perpendicular shift that lifts an edge label off its own line. */
    protected readonly edgeLabelOffset = CDT_TREE_EDGE_LABEL_OFFSET;

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
     * Every explanation this dialog knows about, keyed by step identity. Seeded
     * from the node on open and the source of truth from then on — the canvas
     * reads it for every block's marker, so it has to be a signal.
     *
     * Not in the detail window: that instance survives a switch between blocks —
     * the `@if` stays true and only its input changes — so state kept there would
     * show block A's text under block B's heading.
     */
    private readonly explanations = signal<ReadonlyMap<string, CdtExplanationState>>(this.seedFromStore());

    /**
     * The model is not part of the key: a step has one explanation, and which model
     * wrote it is reported by `Generated by:`. Keying by model would also make the
     * canvas marker ambiguous — current for one model, stale for another.
     */
    private seedFromStore(): ReadonlyMap<string, CdtExplanationState> {
        const seeded = new Map<string, CdtExplanationState>();

        for (const stepKey of new Set(this.explainStepKeys.values())) {
            const remembered = this.explanationStore.get(stepKey);
            if (remembered) {
                seeded.set(stepKey, {
                    status: 'ready',
                    text: remembered.text,
                    generatedBy: remembered.generatedBy,
                    fingerprint: remembered.fingerprint,
                });
            }
        }

        return seeded;
    }

    /**
     * Which LLM writes the explanations this sitting. Seeded from what is already
     * on record for the table, so the picker overrides rather than gates. Not
     * persisted — nothing on the node stores it.
     */
    protected readonly explainLlmConfig = signal<number | null>(resolveExplainLlmConfig(this.data));

    protected readonly explainLlmOptions = this.data.llmConfigOptions;

    /** Which button opened the picker: its footer checkbox is Explain All's only. */
    protected readonly explainMenuScope = signal<'step' | 'all'>('step');

    /**
     * Tracked because both chevrons share one controller: `open` no-ops while a pane
     * is attached, so without it the second chevron would only close the menu.
     */
    private explainMenuAnchor: HTMLElement | null = null;

    /** Restricts an Explain All pass to steps whose text has gone stale. */
    protected readonly explainOutdatedOnly = signal(false);

    protected readonly explainAllTotal = signal(0);
    protected readonly explainAllDone = signal(0);
    /** Set when a pass ends with steps the model would not explain. */
    protected readonly explainAllFailed = signal(0);
    /** Says why a press did nothing, rather than leaving the press unanswered. */
    protected readonly explainAllNotice = signal<string | null>(null);

    protected readonly explainAllRunning = computed(() => this.explainAllTotal() > 0);

    /** Cancels an in-flight pass without tearing the dialog down. */
    private readonly explainAllStopped = new Subject<void>();

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

    protected readonly selectedExplanation = computed<CdtExplanationState | null>(() =>
        this.explanationOf(this.selectedBlockId())
    );

    /** Whether the open block's explanation was written for an older version of it. */
    protected readonly selectedOutdated = computed(() => this.isOutdated(this.selectedBlockId()));

    private explanationOf(blockId: string | null): CdtExplanationState | null {
        const stepKey = blockId ? this.explainStepKeys.get(blockId) : undefined;
        return stepKey ? (this.explanations().get(stepKey) ?? null) : null;
    }

    /** Outdated = has an explanation whose fingerprint no longer matches the step. */
    protected isOutdated(blockId: string | null): boolean {
        if (!blockId) return false;

        const state = this.explanationOf(blockId);
        if (state?.status !== 'ready') return false;

        return state.fingerprint !== this.explainFingerprints.get(blockId);
    }

    /** Whether the open block is one the endpoint can be asked about at all. */
    protected readonly canExplainSelected = computed(() => {
        const id = this.selectedBlockId();
        return !!id && this.explainBlocks.has(id);
    });

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
        this.destroyRef.onDestroy(() => {
            this.searchCtrl.dispose();
            this.explainMenuCtrl.dispose();
        });
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

        // Idempotent, which matters: typing calls this on every key.
        this.explainMenuCtrl.close();
        this.explainMenuAnchor = null;

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

    protected isSelected(blockId: string): boolean {
        return this.selectedBlockId() === blockId;
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

    /**
     * The anchor comes up from the child because the button lives there while the
     * options and the overlay live here.
     */
    protected openExplainMenu(anchor: HTMLElement, scope: 'step' | 'all'): void {
        if (this.explainMenuCtrl.isOpen()) {
            const wasSameAnchor = this.explainMenuAnchor === anchor;
            this.explainMenuCtrl.close();
            this.explainMenuAnchor = null;
            // A press on the chevron that opened it means "close"; a press on the
            // other one means "move here".
            if (wasSameAnchor) return;
        }

        // Neither takes a backdrop, so one has to stand the other down.
        this.searchCtrl.close();

        this.explainMenuAnchor = anchor;
        this.explainMenuScope.set(scope);

        this.explainMenuCtrl.open(anchor, this.explainMenuTpl(), {
            offsetY: 6,
            // Both anchors sit at the right edge of their row.
            alignX: 'end',
            viewportMargin: 12,
            // Keeps the window and canvas behind it clickable.
            hasBackdrop: false,
            ignoreOutsideFor: [anchor],
        });
    }

    protected isExplainMenuOpen(): boolean {
        return this.explainMenuCtrl.isOpen();
    }

    protected selectExplainLlm(option: CdtTreeLlmOption): void {
        // Rendered so the reason is visible, but not a choice.
        if (!option.hasApiKey) return;

        this.explainLlmConfig.set(option.id);
        this.explainMenuCtrl.close();
    }

    /**
     * Ask the endpoint to explain the block the window is showing.
     *
     * Both refusals are answered in the section rather than by a toast: the button
     * is inside a modal, and the sentence belongs where the user just clicked.
     */
    protected explainSelectedBlock(): void {
        const blockId = this.selectedBlockId();
        if (!blockId) return;

        const block = this.explainBlocks.get(blockId);
        if (!block) return;

        const backendId = this.data.backendId;
        if (backendId == null) {
            this.refuseExplain(blockId, CDT_TREE_COPY.explainUnsaved);
            return;
        }

        // Null only when neither the table nor any of its prompts names a model.
        const llmConfig = this.explainLlmConfig();
        if (llmConfig == null) {
            this.refuseExplain(blockId, CDT_TREE_COPY.explainNoModel);
            return;
        }

        const stepKey = this.explainStepKeys.get(blockId);
        if (!stepKey) return;

        // Always regenerates: the remembered answer showed without being asked,
        // so a press can only mean "give me another".
        this.setExplanation(stepKey, { status: 'loading' });

        this.explainService
            .explain(backendId, { llm_config: llmConfig, table: this.explainTable, blocks: [block] })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (response) => this.applyExplanations(response, [blockId]),
                error: (error: HttpErrorResponse) =>
                    this.setExplanation(stepKey, { status: 'error', message: explainErrorMessage(error) }),
            });
    }

    /**
     * Without the checkbox: steps with no explanation at all. With it: the ones
     * whose explanation went stale. Two disjoint sets, so neither ever pays for
     * text that is already current.
     */
    protected explainAll(): void {
        if (this.explainAllRunning()) return;

        this.explainAllNotice.set(null);
        this.explainAllFailed.set(0);

        const backendId = this.data.backendId;
        if (backendId == null) {
            this.explainAllNotice.set(CDT_TREE_COPY.explainUnsaved);
            return;
        }

        const llmConfig = this.explainLlmConfig();
        if (llmConfig == null) {
            this.explainAllNotice.set(CDT_TREE_COPY.explainNoModel);
            return;
        }

        const outdatedOnly = this.explainOutdatedOnly();
        const blocks = this.blocksNeedingExplanation(outdatedOnly);
        if (blocks.length === 0) {
            this.explainAllNotice.set(
                outdatedOnly ? CDT_TREE_COPY.explainAllNothingOutdated : CDT_TREE_COPY.explainAllNothing
            );
            return;
        }

        // All at once, so a block opened mid-pass shows a spinner.
        this.explanations.update((current) => {
            const next = new Map(current);
            for (const block of blocks) {
                const stepKey = this.explainStepKeys.get(block.id);
                if (stepKey) next.set(stepKey, { status: 'loading' });
            }
            return next;
        });

        const chunks = chunkExplainBlocks(blocks);
        this.explainAllTotal.set(blocks.length);
        this.explainAllDone.set(0);

        // Sequential: the server already runs five batches per request, and more
        // on top of that is a rate limit waiting to happen.
        from(chunks)
            .pipe(
                concatMap((chunk) =>
                    this.explainService
                        .explain(backendId, {
                            llm_config: llmConfig,
                            table: this.explainTable,
                            blocks: chunk,
                        })
                        .pipe(map((response) => ({ response, ids: chunk.map((block) => block.id) })))
                ),
                takeUntil(this.explainAllStopped),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                // Per chunk, so a pass that dies halfway keeps its work.
                next: ({ response, ids }) => {
                    this.applyExplanations(response, ids);
                    this.explainAllDone.update((done) => done + response.explanations.length);
                    this.explainAllFailed.update((failed) => failed + response.failures.length);
                },
                error: () => {
                    this.explainAllNotice.set(CDT_TREE_COPY.explainFailed);
                    this.finishExplainAll();
                },
                complete: () => this.finishExplainAll(),
            });
    }

    protected toggleExplainOutdatedOnly(): void {
        this.explainOutdatedOnly.update((only) => !only);
    }

    protected stopExplainAll(): void {
        this.explainAllStopped.next();
        this.finishExplainAll();
    }

    private finishExplainAll(): void {
        // Anything still loading was in a chunk that never ran — a stop, or a failed
        // request. Put back rather than dropped: an outdated step went to loading
        // over text it already had, so dropping would mean Stop wiped explanations
        // the user still had, markers included. The stored copy is untouched.
        this.explanations.update((current) => {
            const next = new Map(current);
            for (const [stepKey, state] of next) {
                if (state.status !== 'loading') continue;

                const remembered = this.explanationStore.get(stepKey);
                if (remembered) {
                    next.set(stepKey, {
                        status: 'ready',
                        text: remembered.text,
                        generatedBy: remembered.generatedBy,
                        fingerprint: remembered.fingerprint,
                    });
                } else {
                    next.delete(stepKey);
                }
            }
            return next;
        });

        if (this.explainAllFailed() > 0) {
            this.explainAllNotice.set(CDT_TREE_COPY.explainAllFailed(this.explainAllFailed()));
        }

        this.explainAllTotal.set(0);
        this.explainAllDone.set(0);
    }

    /** One block per step, so the twice-drawn post step is explained once. */
    private blocksNeedingExplanation(outdatedOnly: boolean): CdtExplainBlock[] {
        const seen = new Set<string>();
        const blocks: CdtExplainBlock[] = [];

        for (const [blockId, block] of this.explainBlocks) {
            const stepKey = this.explainStepKeys.get(blockId);
            if (!stepKey || seen.has(stepKey)) continue;

            const state = this.explanations().get(stepKey);
            const wanted = outdatedOnly ? this.isOutdated(blockId) : state?.status !== 'ready';
            if (!wanted) continue;

            seen.add(stepKey);
            blocks.push(block);
        }

        return blocks;
    }

    /**
     * Filed under the id the response carries, never under the open block: the user
     * can switch blocks mid-flight. The fingerprint stored beside the text is the
     * step's current one, which is what puts the marker out on arrival.
     */
    private applyExplanations(response: CdtExplainResponse, requestedIds: readonly string[]): void {
        this.explanations.update((current) => {
            const next = new Map(current);

            for (const item of response.explanations) {
                const stepKey = this.explainStepKeys.get(item.id);
                const fingerprint = this.explainFingerprints.get(item.id);
                if (!stepKey || !fingerprint) continue;

                next.set(stepKey, {
                    status: 'ready',
                    text: item.text,
                    generatedBy: item.generated_by,
                    fingerprint,
                });
                this.explanationStore.set(stepKey, {
                    text: item.text,
                    generatedBy: item.generated_by,
                    fingerprint,
                });
            }

            // A refusal answers the press directly, so the reason shows even over
            // text that was there. The stored copy survives a reopen.
            for (const failure of response.failures) {
                const stepKey = this.explainStepKeys.get(failure.id);
                if (stepKey) next.set(stepKey, { status: 'error', message: failure.detail });
            }

            // Asked about but mentioned in neither array. Scoped to this request —
            // during a pass the chunks behind it are legitimately still loading.
            for (const id of requestedIds) {
                const stepKey = this.explainStepKeys.get(id);
                if (stepKey && next.get(stepKey)?.status === 'loading') {
                    next.set(stepKey, { status: 'error', message: CDT_TREE_COPY.explainFailed });
                }
            }

            return next;
        });
    }

    /**
     * Why nothing was sent, in the section just clicked. Filed under the step key
     * like any other state — writing these under the raw block id is what made
     * both refusals unreachable before.
     */
    private refuseExplain(blockId: string, message: string): void {
        const stepKey = this.explainStepKeys.get(blockId);
        if (stepKey) this.setExplanation(stepKey, { status: 'error', message });
    }

    private setExplanation(stepKey: string, state: CdtExplanationState): void {
        this.explanations.update((current) => new Map(current).set(stepKey, state));
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
            explainMenuOpen: this.explainMenuCtrl.isOpen(),
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
            case 'close-explain-menu':
                this.explainMenuCtrl.close();
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
