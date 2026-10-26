import { Dialog } from '@angular/cdk/dialog';
import { DOCUMENT } from '@angular/common';
import {
    Component,
    computed,
    DestroyRef,
    effect,
    inject,
    input,
    output,
    signal,
    untracked,
    viewChild,
} from '@angular/core';
import { rxResource, takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { AppSvgIconComponent, SpinnerComponent, TabButtonComponent } from '@shared/components';
import { NodeType } from '@shared/models';
import { filter, fromEvent } from 'rxjs';

import {
    RestoreWarningsDialogComponent,
    RestoreWarningsDialogData,
} from '../../features/flows/components/restore-warnings-dialog/restore-warnings-dialog.component';
import { GetGraphLightRequest, GraphVersionDto, RestoreWarning } from '../../features/flows/models/graph.model';
import { SnapshotNodeAuthorship } from '../../features/flows/models/graph-version-preview.model';
import { FlowsApiService } from '../../features/flows/services/flows-api.service';
import { ToastService } from '../../services/notifications';
import { isEditableTarget } from '../core/keymap/key-chord.util';
import { FlowModel } from '../core/models/flow.model';
import { FLOW_EDITOR_PREVIEW } from '../core/providers/flow-editor-preview.token';
import { FLOW_EDITOR_STATE_PROVIDERS } from '../core/providers/flow-editor-state.providers';
import { FlowGraphComponent } from '../flow-graph/flow-graph.component';
import { ClipboardService } from '../services/clipboard.service';
import { SidePanelService } from '../services/side-panel.service';
import { VersionPreviewNodeAuthorshipStore } from '../services/version-preview-node-authorship.store';
import {
    buildFlowDiff,
    buildFrontendFoundReferences,
    buildUnionFlowModel,
    buildVersionKeyValueTableNames,
    buildVersionMissingReferences,
    buildVersionWarningReferences,
    FlowDiff,
    FlowDiffCanvasState,
    FlowDiffSummary,
} from '../utils/diff';
import { buildPreviewFlowModel, mapNodeAuthorshipToCanvas } from '../utils/load';
import { buildFrontendFoundWarnings } from './frontend-found-warnings';

type PreviewFlowModel = ReturnType<typeof buildPreviewFlowModel>;

/** What the canvas shows, and where a node of the snapshot is on it. */
interface PreviewCanvas {
    flow: FlowModel;
    /** `null` for the plain version; the statuses of the diff canvas otherwise. */
    diffState: FlowDiffCanvasState | null;
    /** The nodes whose version referenced something that no longer exists; marked on both canvases. */
    missingReferenceNodeIds: ReadonlySet<string>;
    snapshotIdToCanvasId: ReadonlyMap<number, string>;
}

/** The diff canvas and the diff it shows. */
interface DiffCanvas extends PreviewCanvas {
    diff: FlowDiff;
}

/**
 * Read-only canvas for one stored version. It owns a separate set of flow-editor services, so
 * nothing done here reaches the live editor's flow, undo stack, side panel or clipboard.
 * The host page removes its live canvas while this is shown and puts it back on `closed`.
 */
@Component({
    selector: 'app-flow-version-preview',
    imports: [FlowGraphComponent, AppSvgIconComponent, SpinnerComponent, TabButtonComponent],
    providers: [...FLOW_EDITOR_STATE_PROVIDERS, { provide: FLOW_EDITOR_PREVIEW, useValue: true }],
    templateUrl: './flow-version-preview.component.html',
    styleUrl: './flow-version-preview.component.scss',
})
export class FlowVersionPreviewComponent {
    public readonly version = input.required<GraphVersionDto>();
    /** Flows the user can open; a subgraph node pointing elsewhere is shown as blocked. */
    public readonly flowsLight = input<GetGraphLightRequest[]>([]);
    /**
     * The live canvas (unsaved edits included); the diff compares the version with it. Read lazily, when the
     * diff of a version is first built (the first time the Changes tab is open for it), and then cached until the
     * preview canvas is rebuilt (another version, or a new list of flows). The host can still change it while
     * previewing (e.g. a save that was already running when the preview opened); such updates are not followed.
     */
    public readonly liveFlow = input.required<FlowModel>();
    public readonly closed = output<void>();
    /** The canvas's shortcuts button; the host page owns the shortcuts modal. */
    public readonly openShortcuts = output<DOMRect>();

    private readonly flowGraph = viewChild(FlowGraphComponent);

    // A computed so a renamed version (same id, new object) does not reload the preview.
    private readonly versionId = computed(() => this.version().id);
    // Keyed on the version id: a newer version cancels the request still in flight, and so does
    // destroying the component.
    protected readonly preview = rxResource({
        params: () => this.versionId(),
        stream: ({ params: versionId }) => this.flowsApiService.previewGraphVersion(versionId),
    });
    // An old or malformed snapshot can make the mappers throw; that shows the error state instead
    // of breaking the page.
    private readonly previewBuild = computed<{ model: PreviewFlowModel | null; failed: boolean }>(() => {
        const response = this.preview.hasValue() ? this.preview.value() : undefined;
        if (!response) return { model: null, failed: false };
        try {
            // Resolved by the backend like a restore does, so a user who cannot read the secrets list
            // still sees the secrets a restore would re-link.
            const secretsByName = new Map(Object.entries(response.resolved_secrets));
            return {
                model: buildPreviewFlowModel(response.snapshot, secretsByName, this.flowsLight()),
                failed: false,
            };
        } catch (error) {
            console.error('Failed to build the version preview', error);
            return { model: null, failed: true };
        }
    });
    private readonly previewModel = computed(() => this.previewBuild().model);
    /**
     * What the version side alone says, keyed by version (plain canvas) node id: the references the preview
     * warnings removed, the Key-Value table names, and from both the missing references of each node. Shared
     * by both tabs, so the Preview tab marks missing references without building the diff.
     */
    private readonly versionSide = computed(() => {
        const model = this.previewModel();
        if (!model || !this.preview.hasValue()) return null;
        const response = this.preview.value();
        const warningReferences = buildVersionWarningReferences(response.warnings, model.snapshotIdToCanvasId);
        const keyValueTableNames = buildVersionKeyValueTableNames(response.snapshot.nodes, model.snapshotIdToCanvasId);
        const frontendFoundReferences = buildFrontendFoundReferences(model.flow, keyValueTableNames);
        return {
            model,
            warningReferences,
            keyValueTableNames,
            frontendFoundReferences,
            missingReferences: buildVersionMissingReferences(model.flow, warningReferences, frontendFoundReferences),
        };
    });
    /**
     * Which tab is open: Preview (`false`, the default) shows the version as saved, Changes (`true`) what a
     * restore does to the live canvas. Kept across version switches; the host destroys the preview on exit,
     * which resets it.
     */
    protected readonly showChanges = signal(false);
    // What a restore of the version does to the live canvas, on one canvas. Kept apart from the plain
    // preview model, so a Preview / Changes switch only changes which canvas is bound. Read only
    // while the Changes tab is open, so the diff is not built for the plain preview.
    private readonly diffBuild = computed<{ canvas: DiffCanvas | null; failed: boolean }>(() => {
        const versionSide = this.versionSide();
        if (!versionSide) return { canvas: null, failed: false };
        const { model } = versionSide;
        try {
            const diff = buildFlowDiff({
                versionFlow: model.flow,
                // Read, not tracked: a host update while previewing (e.g. backend ids patched in after a save)
                // must not rebuild the canvas with new ids under an open panel or selection.
                liveFlow: untracked(() => this.liveFlow()),
                versionWarningReferences: versionSide.warningReferences,
                versionKeyValueTableNames: versionSide.keyValueTableNames,
            });
            const union = buildUnionFlowModel(diff);
            const snapshotIdToCanvasId = new Map<number, string>();
            for (const [snapshotId, versionId] of model.snapshotIdToCanvasId) {
                const unionId = union.unionIdByVersionId.get(versionId);
                if (unionId !== undefined) snapshotIdToCanvasId.set(snapshotId, unionId);
            }
            const missingReferenceNodeIds = new Set(
                [...versionSide.missingReferences.keys()].flatMap(
                    (versionId) => union.unionIdByVersionId.get(versionId) ?? []
                )
            );
            return {
                canvas: {
                    flow: union.flow,
                    diffState: union.diffState,
                    missingReferenceNodeIds,
                    snapshotIdToCanvasId,
                    diff,
                },
                failed: false,
            };
        } catch (error) {
            console.error('Failed to compare the version with the current flow', error);
            return { canvas: null, failed: true };
        }
    });
    /** The canvas bound to the graph: the diff canvas on the Changes tab, the plain version on the Preview tab. */
    protected readonly canvas = computed<PreviewCanvas | null>(() => {
        if (this.showChanges()) return this.diffBuild().canvas;
        const versionSide = this.versionSide();
        if (!versionSide) return null;
        return {
            flow: versionSide.model.flow,
            diffState: null,
            missingReferenceNodeIds: new Set(versionSide.missingReferences.keys()),
            snapshotIdToCanvasId: versionSide.model.snapshotIdToCanvasId,
        };
    });
    // A failed diff only matters while it is shown: the plain preview does not need it.
    protected readonly hasDiffFailed = computed(() => this.showChanges() && this.diffBuild().failed);
    protected readonly hasFailed = computed(
        () => !!this.preview.error() || this.previewBuild().failed || this.hasDiffFailed()
    );
    /** What a restore of the version does, in words (nodes only); `null` on the Preview tab. */
    protected readonly changesSummary = computed<string | null>(() => {
        const diff = this.shownDiff();
        return diff ? describeRestore(diff.summary) : null;
    });
    /**
     * A version saved before nodes had a stable id matches no current node, so all its nodes show as added
     * and all current ones as removed. Only when both sides have nodes besides Start: Start nodes are paired
     * by type and left out of the match rate, and a current canvas with nothing else to match is no sign of
     * an old version.
     */
    protected readonly showsOldSnapshotHint = computed(() => {
        const diff = this.shownDiff();
        return (
            !!diff &&
            diff.matchRate === 0 &&
            diff.nodes.some((node) => node.currentNode !== undefined && node.type !== NodeType.START)
        );
    });
    /**
     * The backend warnings, then the missing references only the frontend finds (a Key-Value table that
     * could not be re-bound). Both name nodes by their snapshot id. Shown in both modes, so they are built
     * from the version alone, without the diff.
     */
    protected readonly warnings = computed<RestoreWarning[]>(() => {
        if (!this.preview.hasValue()) return [];
        const response = this.preview.value();
        const versionSide = this.versionSide();
        if (!versionSide) return response.warnings;
        return [
            ...response.warnings,
            ...buildFrontendFoundWarnings(
                response.snapshot.nodes,
                versionSide.frontendFoundReferences,
                versionSide.model.snapshotIdToCanvasId
            ),
        ];
    });
    private readonly shownDiff = computed<FlowDiff | null>(() =>
        this.showChanges() ? (this.diffBuild().canvas?.diff ?? null) : null
    );
    // Empty for a version saved before node authorship was recorded. Re-keyed whenever the canvas is rebuilt.
    private readonly nodeAuthorshipByNodeId = computed<ReadonlyMap<string, SnapshotNodeAuthorship>>(() => {
        const canvas = this.canvas();
        if (!canvas || !this.preview.hasValue()) return new Map();
        return mapNodeAuthorshipToCanvas(this.preview.value().node_authorship, canvas.snapshotIdToCanvasId);
    });

    // This preview's own store, read by a node's "Node Details" dialog and the Start window's footer.
    private readonly syncNodeAuthorship = effect(() =>
        this.nodeAuthorshipStore.replaceFromVersion(this.nodeAuthorshipByNodeId())
    );

    private readonly flowsApiService = inject(FlowsApiService);
    private readonly dialog = inject(Dialog);
    private readonly toastService = inject(ToastService);
    private readonly previewClipboard = inject(ClipboardService);
    // skipSelf: past this component's own editor providers, to the host page's (live) clipboard.
    private readonly liveClipboard = inject(ClipboardService, { skipSelf: true });
    private readonly destroyRef = inject(DestroyRef);
    private readonly sidePanelService = inject(SidePanelService);
    private readonly nodeAuthorshipStore = inject(VersionPreviewNodeAuthorshipStore);

    constructor() {
        fromEvent<KeyboardEvent>(inject(DOCUMENT), 'keydown', { capture: true })
            .pipe(
                filter((event) => event.key === 'Escape' && this.isEscapeFree(event)),
                takeUntilDestroyed()
            )
            .subscribe(() => this.onExit());
    }

    /** Nodes copied from the preview are pasted into the live flow, so they go to its clipboard. */
    protected onCopied(): void {
        const copiedNodes = this.previewClipboard.getClipboardData();
        if (!copiedNodes) return;
        this.liveClipboard.setClipboardData(copiedNodes);
        this.toastService.success('Copied', 2000, 'bottom-right');
    }

    protected onShowChangesChange(showChanges: boolean): void {
        // A click on the open tab changes nothing (and must not drop the selection).
        if (showChanges === this.showChanges()) return;
        const previousCanvas = this.canvas();
        this.showChanges.set(showChanges);
        // The other canvas has other node ids: an open panel moves to the same node there, and a selection made
        // on the previous canvas no longer means anything.
        this.keepPanelOnSameNode(previousCanvas, this.canvas());
        const graph = this.flowGraph();
        graph?.clearCanvasSelection();
        // It also has its own layout. A graph re-created for it fits by itself.
        graph?.fitAfterNextFlowChange();
    }

    protected onShowWarnings(): void {
        const dialogRef = this.dialog.open<number | undefined>(RestoreWarningsDialogComponent, {
            width: '560px',
            data: { warnings: this.warnings(), context: 'preview' } satisfies RestoreWarningsDialogData,
        });

        dialogRef.closed
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                filter((snapshotNodeId): snapshotNodeId is number => snapshotNodeId != null)
            )
            .subscribe((snapshotNodeId) => {
                // Warnings name nodes by their id in the snapshot; preview nodes have no backend id. Mapped
                // through the bound canvas: the plain and the diff canvas give a node different ids.
                const nodeId = this.canvas()?.snapshotIdToCanvasId.get(snapshotNodeId);
                if (nodeId) {
                    this.flowGraph()?.openNodePanel(nodeId);
                }
            });
    }

    private onExit(): void {
        this.closed.emit();
    }

    /**
     * Re-opens the panel on the node of the same snapshot node on `nextCanvas`, or closes it when that node
     * has none: a node only the live canvas has (no snapshot id), or a diff that could not be built.
     */
    private keepPanelOnSameNode(previousCanvas: PreviewCanvas | null, nextCanvas: PreviewCanvas | null): void {
        const openNodeId = this.sidePanelService.selectedNodeId();
        if (openNodeId === null) return;
        const snapshotId = previousCanvas
            ? [...previousCanvas.snapshotIdToCanvasId].find(([, canvasId]) => canvasId === openNodeId)?.[0]
            : undefined;
        const nextNodeId = snapshotId === undefined ? undefined : nextCanvas?.snapshotIdToCanvasId.get(snapshotId);
        this.sidePanelService.setSelectedNodeId(nextNodeId ?? null);
    }

    private isEscapeFree(event: KeyboardEvent): boolean {
        return (
            this.dialog.openDialogs.length === 0 &&
            this.sidePanelService.selectedNodeId() === null &&
            !this.flowGraph()?.selectionManager.multiSelectActive() &&
            !(event.target instanceof HTMLElement && isEditableTarget(event.target)) &&
            !(event.target instanceof Element && event.target.closest('app-shortcuts-modal'))
        );
    }
}

/**
 * e.g. "Restoring this version will add 2 nodes, remove 1 node and change 3 nodes." Only the non-zero node
 * counts are named; connections are not counted, only mentioned when they are all that differs.
 */
function describeRestore(summary: FlowDiffSummary): string {
    const nodeChanges = [
        { verb: 'add', count: summary.added },
        { verb: 'remove', count: summary.deleted },
        { verb: 'change', count: summary.changed },
    ]
        .filter(({ count }) => count > 0)
        .map(({ verb, count }) => `${verb} ${count} ${count === 1 ? 'node' : 'nodes'}`);
    if (nodeChanges.length > 0) return `Restoring this version will ${joinAsList(nodeChanges)}.`;
    if (summary.edgesAdded + summary.edgesDeleted > 0)
        return 'Restoring this version will only change connections, no nodes.';
    return 'Restoring this version will not change any nodes or connections.';
}

/** "a", "a and b", "a, b and c". */
function joinAsList(items: readonly string[]): string {
    return items.length === 1 ? items[0] : `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`;
}
