import { Dialog, DialogModule } from '@angular/cdk/dialog';
import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, effect, inject, signal } from '@angular/core';
import { Router } from '@angular/router';

import { ImportExportService } from '../../../../../../core/services/import-export.service';
import { ToastService } from '../../../../../../services/notifications/toast.service';
import {
    ConfirmationDialogService,
    ConfirmationResult,
} from '../../../../../../shared/components/cofirm-dialog/confimation-dialog.service';
import { LoadingSpinnerComponent } from '../../../../../../shared/components/loading-spinner/loading-spinner.component';
import { GraphUpdateService } from '../../../../../../visual-programming/services/graph/save-graph.service';
import { FlowCardAction, FlowCardComponent } from '../../../../components/flow-card/flow-card.component';
import { FlowRenameDialogComponent } from '../../../../components/flow-rename-dialog/flow-rename-dialog.component';
import { FlowSessionsListComponent } from '../../../../components/flow-sessions-dialog/flow-sessions-list.component';
import { GetGraphLightRequest, GraphDto } from '../../../../models/graph.model';
import { FlowsApiService } from '../../../../services/flows-api.service';
import { FlowsStorageService } from '../../../../services/flows-storage.service';
import { LabelsStorageService } from '../../../../services/labels-storage.service';
import { RunGraphService } from '../../../../services/run-graph-session.service';

@Component({
    selector: 'app-my-flows',
    standalone: true,
    changeDetection: ChangeDetectionStrategy.OnPush,
    templateUrl: './my-flows.component.html',
    styleUrls: ['./my-flows.component.scss'],
    imports: [CommonModule, FlowCardComponent, LoadingSpinnerComponent, DialogModule],
})
export class MyFlowsComponent {
    private readonly flowsService = inject(FlowsStorageService);
    private readonly graphUpdateService = inject(GraphUpdateService);
    private readonly flowsApiService = inject(FlowsApiService);
    private readonly runGraphService = inject(RunGraphService);
    private readonly router = inject(Router);
    private readonly dialog = inject(Dialog);
    private readonly toastService = inject(ToastService);
    private readonly confirmationDialogService = inject(ConfirmationDialogService);
    private readonly importExportService = inject(ImportExportService);
    private readonly labelsStorage = inject(LabelsStorageService);

    public readonly activeLabelFilter = this.labelsStorage.activeLabelFilter;

    public readonly error = signal<string | null>(null);
    public readonly filteredFlows = this.flowsService.filteredFlows;
    public readonly isFlowsLoaded = this.flowsService.isFlowsLoaded;
    public readonly selectMode = this.flowsService.selectMode;
    public readonly selectedFlowIds = this.flowsService.selectedFlowIds;

    constructor() {
        effect(() => {
            const filter = this.labelsStorage.activeLabelFilter();
            this.flowsService.getFlows(true, filter).subscribe({
                next: () => {},
                error: (err: HttpErrorResponse) => {
                    console.error('Error loading flows', err);
                    this.error.set('Failed to load flows. Please try again later.');
                },
            });
        });
    }

    public retryLoad(): void {
        this.error.set(null);
        this.flowsService.getFlows(true, this.labelsStorage.activeLabelFilter()).subscribe({
            next: () => {},
            error: (err: HttpErrorResponse) => {
                console.error('Error loading flows', err);
                this.error.set('Failed to load flows. Please try again later.');
            },
        });
    }

    public onFlowSelect(flowId: number): void {
        this.flowsService.toggleFlowSelection(flowId);
    }

    public isFlowSelected(flowId: number): boolean {
        return this.selectedFlowIds().includes(flowId);
    }

    public onOpenFlow(id: number): void {
        this.router.navigate(['/flows', id]);
    }

    public handleFlowCardAction(event: FlowCardAction): void {
        const { action, flow } = event;
        switch (action) {
            case 'open':
                this.onOpenFlow(flow.id);
                break;

            case 'delete':
                this.confirmAndDeleteFlow(flow);
                break;

            case 'viewSessions':
                this.dialog.open(FlowSessionsListComponent, {
                    data: { flow },
                    panelClass: 'custom-dialog-panel',
                });
                break;

            case 'rename':
                this.openRenameDialog(flow);
                break;

            case 'run':
                this.runFlow(flow);
                break;

            case 'copy':
                this.openCopyDialog(flow);
                break;

            case 'export':
                this.exportFlow(flow);
                break;

            default:
                console.log(`Action '${action}' not implemented for flow:`, flow.id);
        }
    }

    private confirmAndDeleteFlow(flow: GetGraphLightRequest): void {
        this.confirmationDialogService
            .confirmDeleteWithTruncation(flow.name, 50)
            .subscribe((result: ConfirmationResult) => {
                if (result === true) {
                    this.flowsService.deleteFlow(flow.id).subscribe({
                        next: () => {
                            this.flowsService.getFlows(true, this.labelsStorage.activeLabelFilter()).subscribe();
                        },
                        error: (err) => {
                            console.error(`Error deleting flow ${flow.id} - ${flow.name}`, err);
                        },
                    });
                }
            });
    }

    private openRenameDialog(flow: GetGraphLightRequest): void {
        const dialogRef = this.dialog.open<GraphDto | string>(FlowRenameDialogComponent, {
            data: {
                flowName: flow.name,
                flow: {
                    id: flow.id,
                    name: flow.name,
                    description: flow.description,
                    label_ids: flow.label_ids,
                },
            },
            width: '500px',
        });

        dialogRef.closed.subscribe((result) => {
            if (!result) return;
            this.flowsService.getFlows(true, this.labelsStorage.activeLabelFilter()).subscribe();
        });
    }
    private saving(flowState: GraphDto['metadata'], graph: GraphDto): void {
        this.graphUpdateService.saveGraph(flowState, graph).subscribe({
            next: (result) => {
                this.toastService.success(`Flow copied and saved as "${result.graph.name}"`);
            },
            error: (err) => {
                this.toastService.error('Failed to save graph for copied flow');
                console.error('Save graph error', err);
            },
        });
    }

    private openCopyDialog(flow: GetGraphLightRequest): void {
        const dialogRef = this.dialog.open<string>(FlowRenameDialogComponent, {
            data: { flowName: `${flow.name} Copy`, title: 'Copy Flow' },
        });

        dialogRef.closed.subscribe((newName) => {
            if (newName && newName.trim().length > 0) {
                this.flowsService.copyFlow(flow.id, newName.trim()).subscribe({
                    next: (graph) => {
                        this.saving(graph.metadata, graph);
                    },
                    error: (err) => {
                        this.toastService.error('Failed to copy flow');
                        console.error('Copy flow error', err);
                    },
                });
            }
        });
    }

    private runFlow(flow: GetGraphLightRequest): void {
        // Empty inputs object as per API requirements
        const inputs = {};

        this.runGraphService.runGraph(flow.id, inputs).subscribe({
            next: (response) => {
                if (response && response.session_id) {
                    this.router.navigate(['/graph', flow.id, 'session', response.session_id]);
                } else {
                    console.error('Invalid response from run graph API:', response);
                }
            },
            error: (err) => {
                console.error(`Error running flow ${flow.id}`, err);

                // Extract error message from backend response
                let errorMessage = 'Failed to run flow';
                if (err.error && err.error.message) {
                    errorMessage = err.error.message;
                } else if (err.error && typeof err.error === 'string') {
                    errorMessage = err.error;
                } else if (err.message) {
                    errorMessage = err.message;
                }

                this.toastService.error(`Error running flow "${flow.name}": ${errorMessage}`);
            },
        });
    }

    private exportFlow(flow: GetGraphLightRequest): void {
        this.importExportService.exportFlow(flow.id.toString()).subscribe({
            next: (blob) => {
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `${flow.name}_export_${Date.now()}.json`;
                a.click();
                window.URL.revokeObjectURL(url);

                this.toastService.success(`Flow "${flow.name}" exported successfully`);
            },
            error: (error) => {
                console.error('Export failed:', error);
                this.toastService.error(`Failed to export flow "${flow.name}"`);
            },
        });
    }
}
