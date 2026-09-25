import { Dialog } from '@angular/cdk/dialog';
import { Component, computed, DestroyRef, inject, input, output, viewChild } from '@angular/core';
import { rxResource, takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { AppSvgIconComponent, SpinnerComponent } from '@shared/components';
import { SecretsStorageService } from '@shared/services';
import { catchError, filter, forkJoin, of } from 'rxjs';

import {
    RestoreWarningsDialogComponent,
    RestoreWarningsDialogData,
} from '../../features/flows/components/restore-warnings-dialog/restore-warnings-dialog.component';
import { GetGraphLightRequest, GraphVersionDto, RestoreWarning } from '../../features/flows/models/graph.model';
import { FlowsApiService } from '../../features/flows/services/flows-api.service';
import { ToastService } from '../../services/notifications';
import { FLOW_EDITOR_READ_ONLY, FLOW_EDITOR_STATE_PROVIDERS } from '../core/providers/flow-editor-state.providers';
import { FlowGraphComponent } from '../flow-graph/flow-graph.component';
import { ClipboardService } from '../services/clipboard.service';
import { buildPreviewFlowModel } from '../utils/load';

type PreviewFlowModel = ReturnType<typeof buildPreviewFlowModel>;

/**
 * Read-only canvas for one stored version. It owns a separate set of flow-editor services, so
 * nothing done here reaches the live editor's flow, undo stack, side panel or clipboard.
 * The host page removes its live canvas while this is shown and puts it back on `closed`.
 */
@Component({
    selector: 'app-flow-version-preview',
    imports: [FlowGraphComponent, AppSvgIconComponent, SpinnerComponent],
    providers: [...FLOW_EDITOR_STATE_PROVIDERS, { provide: FLOW_EDITOR_READ_ONLY, useValue: true }],
    templateUrl: './flow-version-preview.component.html',
    styleUrl: './flow-version-preview.component.scss',
})
export class FlowVersionPreviewComponent {
    public readonly version = input.required<GraphVersionDto>();
    /** Flows the user can open; a subgraph node pointing elsewhere is shown as blocked. */
    public readonly flowsLight = input<GetGraphLightRequest[]>([]);
    public readonly closed = output<void>();
    /** The canvas's shortcuts button; the host page owns the shortcuts modal. */
    public readonly openShortcuts = output<DOMRect>();

    private readonly flowGraph = viewChild(FlowGraphComponent);

    // Keyed on the version id: a newer version cancels the request still in flight, and so does
    // destroying the component.
    protected readonly preview = rxResource({
        params: () => this.version().id,
        stream: ({ params: versionId }) =>
            forkJoin({
                response: this.flowsApiService.previewGraphVersion(versionId),
                secrets: this.secretsStorageService.getSecrets().pipe(catchError(() => of([]))),
            }),
    });
    // An old or malformed snapshot can make the mappers throw; that shows the error state instead
    // of breaking the page.
    private readonly previewBuild = computed<{ model: PreviewFlowModel | null; failed: boolean }>(() => {
        const loaded = this.preview.hasValue() ? this.preview.value() : undefined;
        if (!loaded) return { model: null, failed: false };
        const secretsByName = new Map(loaded.secrets.map((secret) => [secret.name, secret.id]));
        try {
            return {
                model: buildPreviewFlowModel(loaded.response.snapshot, secretsByName, this.flowsLight()),
                failed: false,
            };
        } catch (error) {
            console.error('Failed to build the version preview', error);
            return { model: null, failed: true };
        }
    });
    protected readonly previewModel = computed(() => this.previewBuild().model);
    protected readonly hasFailed = computed(() => !!this.preview.error() || this.previewBuild().failed);
    protected readonly warnings = computed<RestoreWarning[]>(() =>
        this.preview.hasValue() ? this.preview.value().response.warnings : []
    );

    private readonly flowsApiService = inject(FlowsApiService);
    private readonly secretsStorageService = inject(SecretsStorageService);
    private readonly dialog = inject(Dialog);
    private readonly toastService = inject(ToastService);
    private readonly previewClipboard = inject(ClipboardService);
    // skipSelf: past this component's own editor providers, to the host page's (live) clipboard.
    private readonly liveClipboard = inject(ClipboardService, { skipSelf: true });
    private readonly destroyRef = inject(DestroyRef);

    /** Nodes copied from the preview are pasted into the live flow, so they go to its clipboard. */
    protected onCopied(): void {
        const copiedNodes = this.previewClipboard.getClipboardData();
        if (!copiedNodes) return;
        this.liveClipboard.setClipboardData(copiedNodes);
        this.toastService.success('Copied', 2000, 'bottom-right');
    }

    protected onExit(): void {
        this.closed.emit();
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
                // Warnings name nodes by their id in the snapshot; preview nodes have no backend id.
                const nodeId = this.previewModel()?.snapshotIdToNodeUuid.get(snapshotNodeId);
                if (nodeId) {
                    this.flowGraph()?.openNodePanel(nodeId);
                }
            });
    }
}
