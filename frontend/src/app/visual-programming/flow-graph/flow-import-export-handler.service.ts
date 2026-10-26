import { HttpErrorResponse } from '@angular/common/http';
import { DestroyRef, inject, Injectable } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NodeType } from '@shared/models';
import { downloadBlob, showExportExclusionWarning } from '@shared/utils';

import { ImportExportService, PartialExportRequest } from '../../core/services/import-export.service';
import { GraphContentDto } from '../../features/flows/models/graph.model';
import { FlowCopyImportFacadeService } from '../../features/flows/services/flow-copy-import-facade.service';
import { ToastService } from '../../services/notifications';
import { CdtExportImportService } from '../components/node-panels/classification-decision-table-node-panel/cdt-export-import.service';
import { FlowService } from '../services/flow.service';
import { FlowSelectionManagerService } from './flow-selection-manager.service';

/** Adds a partial import's `content` to the canvas; returns false when it could not (the editor was busy). */
export type ImportedContentHandler = (content: GraphContentDto) => boolean;

/**
 * Handles import and export operations for the flow graph: partial/full JSON export,
 * CSV export and partial import.
 *
 * Provided at the FlowGraphComponent level — one instance per editor.
 */
@Injectable()
export class FlowImportExportService {
    private readonly flowService = inject(FlowService);
    private readonly selectionManager = inject(FlowSelectionManagerService);
    private readonly importExportService = inject(ImportExportService);
    private readonly flowCopyImportFacade = inject(FlowCopyImportFacadeService);
    private readonly cdtExportImportService = inject(CdtExportImportService);
    private readonly toastService = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);

    // ── Export: selected as JSON ────────────────────────────────────

    onExportSelectedAsJson(currentFlowId: number | null, hasUnsavedChanges: boolean): void {
        if (!currentFlowId) return;
        if (hasUnsavedChanges) {
            this.toastService.warning('Save the flow before exporting', 3000, 'bottom-right');
            return;
        }
        this.triggerPartialExport(this.selectionManager.selectedNodeIds(), currentFlowId);
    }

    // ── Export: selected as CSV ─────────────────────────────────────

    onExportSelectedAsCsv(hasUnsavedChanges: boolean): void {
        if (hasUnsavedChanges) {
            this.toastService.warning('Save the flow before exporting', 3000, 'bottom-right');
            return;
        }
        const selectedIds = this.selectionManager.selectedNodeIds();
        const nodes = this.flowService.nodes();

        for (const id of selectedIds) {
            const node = nodes.find((n) => n.id === id);

            if (!node || node.backendId === null) {
                continue;
            }

            this.importExportService
                .cdtExport(node.backendId, 'json')
                .pipe(takeUntilDestroyed(this.destroyRef))
                .subscribe({
                    next: (blob) => {
                        blob.text()
                            .then((text) => {
                                const parsed = JSON.parse(text) as Record<string, unknown>;
                                const exportData = this.cdtExportImportService.partialExportNodeToCdtExportData(parsed);
                                const csv = this.cdtExportImportService.exportToCsv(exportData);
                                this.cdtExportImportService.downloadFile(
                                    csv,
                                    node.node_name + '.csv',
                                    'text/csv;charset=utf-8;'
                                );
                            })
                            .catch(() => this.toastService.error('Export failed', 3000, 'bottom-right'));
                    },
                    error: () => this.toastService.error('Export failed', 3000, 'bottom-right'),
                });
        }
    }

    // ── Export: all as JSON ─────────────────────────────────────────

    onExportAllAsJson(currentFlowId: number | null, hasUnsavedChanges: boolean): void {
        if (!currentFlowId) return;
        const exportable = this.flowService.nodes().filter((n) => n.type !== NodeType.START && n.type !== NodeType.END);
        if (exportable.length === 0) {
            this.toastService.warning('No nodes to export', 3000, 'bottom-right');
            return;
        }
        if (hasUnsavedChanges) {
            this.toastService.warning('Save the flow before exporting', 3000, 'bottom-right');
            return;
        }
        this.triggerPartialExport([], currentFlowId);
    }

    // ── Import ─────────────────────────────────────────────────────

    /**
     * Picks a node bundle file and hands the backend's unsaved `content` for it to `onImported`; nothing is
     * written to the flow, so the caller adds the nodes to the canvas and the flow save persists them.
     */
    onImportNodes(currentFlowId: number, onImported: ImportedContentHandler): void {
        const input = document.createElement('input');
        input.type = 'file';
        input.accept = '.json';
        input.value = '';
        input.onchange = (e: Event) => {
            const file = (e.target as HTMLInputElement).files?.[0];
            if (!file) return;
            this.doPartialImport(file, currentFlowId, onImported);
        };
        input.click();
    }

    // ── Private helpers ────────────────────────────────────────────

    private triggerPartialExport(nodeIds: string[], currentFlowId: number): void {
        const body = this.buildPartialExportBody(nodeIds);
        const filename = nodeIds.length > 0 ? 'selected-nodes.json' : 'all-nodes.json';
        this.importExportService
            .partialExport(currentFlowId, body)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: ({ blob, excluded }) => {
                    downloadBlob(blob, filename);
                    const count = Object.entries(body)
                        .filter(([key]) => key !== 'edge_list')
                        .reduce((sum, [, list]) => sum + (list as number[]).length, 0);
                    const isExportAll = nodeIds.length === 0;
                    const hasStartOrEnd =
                        !isExportAll &&
                        this.flowService
                            .nodes()
                            .some(
                                (n) => nodeIds.includes(n.id) && (n.type === NodeType.START || n.type === NodeType.END)
                            );
                    const suffix = isExportAll || hasStartOrEnd ? ' (Start and End nodes excluded)' : '';
                    this.toastService.success(`${count} nodes exported as JSON${suffix}`, 3000, 'bottom-right');

                    showExportExclusionWarning(this.toastService, excluded, 'bottom-right');
                },
                error: () => this.toastService.error('Export failed', 3000, 'bottom-right'),
            });
    }

    private buildPartialExportBody(selectedIds: string[]): PartialExportRequest {
        const allNodes = this.flowService.nodes();
        const nodes = selectedIds.length > 0 ? allNodes.filter((n) => selectedIds.includes(n.id)) : allNodes;
        const selectedIdSet = new Set(
            nodes.filter((n) => n.type !== NodeType.START && n.type !== NodeType.END).map((n) => n.id)
        );

        const body: PartialExportRequest = {
            agent_node_list: [],
            task_node_list: [],
            python_node_list: [],
            audio_transcription_node_list: [],
            file_extractor_node_list: [],
            subgraph_node_list: [],
            webhook_trigger_node_list: [],
            telegram_trigger_node_list: [],
            decision_table_node_list: [],
            classification_decision_table_node_list: [],
            graph_note_list: [],
            schedule_trigger_node_list: [],
            edge_list: [],
            knowledge_node_list: [],
            key_value_node_list: [],
        };

        for (const node of nodes) {
            if (node.backendId === null) continue;
            if (node.type === NodeType.START || node.type === NodeType.END) continue;
            const id = node.backendId;
            switch (node.type) {
                case NodeType.AGENT:
                    body.agent_node_list.push(id);
                    break;
                case NodeType.TASK:
                    body.task_node_list.push(id);
                    break;
                case NodeType.PYTHON:
                    body.python_node_list.push(id);
                    break;
                case NodeType.AUDIO_TO_TEXT:
                    body.audio_transcription_node_list.push(id);
                    break;
                case NodeType.FILE_EXTRACTOR:
                    body.file_extractor_node_list.push(id);
                    break;
                case NodeType.SUBGRAPH:
                    body.subgraph_node_list.push(id);
                    break;
                case NodeType.WEBHOOK_TRIGGER:
                    body.webhook_trigger_node_list.push(id);
                    break;
                case NodeType.TELEGRAM_TRIGGER:
                    body.telegram_trigger_node_list.push(id);
                    break;
                case NodeType.TABLE:
                    body.decision_table_node_list.push(id);
                    break;
                case NodeType.CLASSIFICATION_TABLE:
                    body.classification_decision_table_node_list.push(id);
                    break;
                case NodeType.NOTE:
                    body.graph_note_list.push(id);
                    break;
                case NodeType.SCHEDULE_TRIGGER:
                    body.schedule_trigger_node_list.push(id);
                    break;
                case NodeType.KNOWLEDGE_RETRIEVER:
                    body.knowledge_node_list.push(id);
                    break;
                case NodeType.KEY_VALUE:
                    body.key_value_node_list.push(id);
                    break;
            }
        }

        for (const conn of this.flowService.connections()) {
            if (selectedIdSet.has(conn.sourceNodeId) && selectedIdSet.has(conn.targetNodeId) && conn.data?.id != null) {
                body.edge_list.push(conn.data.id);
            }
        }

        return body;
    }

    private doPartialImport(file: File, currentFlowId: number, onImported: ImportedContentHandler): void {
        // Through the facade: the backend refuses a file with trigger nodes to a user without Flows:Use, and the
        // facade explains that refusal (nothing is emitted then, so nothing below runs).
        this.flowCopyImportFacade
            .partialImport(currentFlowId, file)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (response) => {
                    if (onImported(response.content)) {
                        this.toastService.success('Import successful', 3000, 'bottom-right');
                    } else {
                        this.toastService.warning(
                            'Import discarded: the editor was busy. Try again.',
                            4000,
                            'bottom-right'
                        );
                    }
                },
                error: (err: HttpErrorResponse) => {
                    const rawMessage =
                        (err.error as Record<string, string>)?.['message'] ??
                        (err.error as Record<string, string>)?.['detail'] ??
                        null;
                    this.toastService.error(rawMessage ?? 'Import failed', 3000, 'bottom-right');
                },
            });
    }
}
