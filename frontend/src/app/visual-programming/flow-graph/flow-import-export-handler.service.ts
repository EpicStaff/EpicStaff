import { HttpErrorResponse } from '@angular/common/http';
import { DestroyRef, inject, Injectable } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NodeType } from '@shared/models';
import { downloadBlob } from '@shared/utils';

import { ImportExportService, PartialExportRequest } from '../../core/services/import-export.service';
import { FlowCopyImportFacadeService } from '../../features/flows/services/flow-copy-import-facade.service';
import { ToastService } from '../../services/notifications';
import { CdtExportImportService } from '../components/node-panels/classification-decision-table-node-panel/cdt-export-import.service';
import { FlowModel } from '../core/models/flow.model';
import { FlowService } from '../services/flow.service';
import { FlowSelectionManagerService } from './flow-selection-manager.service';

/**
 * Handles import and export operations for the flow graph: partial/full JSON export,
 * CSV export, partial import, and post-import node shifting.
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

    // ── Import state ────────────────────────────────────────────────
    private _preImportBackendIds: Set<number> | null = null;
    private _importPositionSnapshot: Map<number, { x: number; y: number }> | null = null;

    /** Set to `true` after a successful import so the component can fit-to-screen on the next flow change. */
    fitAfterNextFlowChange = false;

    /** Whether a post-import shift is pending (backend IDs were recorded before import). */
    get hasPendingImportShift(): boolean {
        return this._preImportBackendIds !== null;
    }

    // ── Export: selected as JSON ────────────────────────────────────

    onExportSelectedAsJson(currentFlowId: number | null): void {
        if (!currentFlowId) return;
        const selectedIds = this.selectionManager.selectedNodeIds();
        const nodes = this.flowService.nodes();
        const hasUnsaved = selectedIds.some((id) => nodes.find((n) => n.id === id)?.backendId === null);
        if (hasUnsaved) {
            this.toastService.warning('Save the flow before exporting', 3000, 'bottom-right');
            return;
        }
        this.triggerPartialExport(selectedIds, currentFlowId);
    }

    // ── Export: selected as CSV ─────────────────────────────────────

    onExportSelectedAsCsv(): void {
        const selectedIds = this.selectionManager.selectedNodeIds();
        const nodes = this.flowService.nodes();

        for (const id of selectedIds) {
            const node = nodes.find((n) => n.id === id);

            if (!node) {
                continue;
            }

            if (node.backendId === null) {
                this.toastService.warning('Save the flow before exporting', 3000, 'bottom-right');
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

    onExportAllAsJson(currentFlowId: number | null): void {
        if (!currentFlowId) return;
        const exportable = this.flowService.nodes().filter((n) => n.type !== NodeType.START && n.type !== NodeType.END);
        if (exportable.length === 0) {
            this.toastService.warning('No nodes to export', 3000, 'bottom-right');
            return;
        }
        if (this.flowService.nodes().some((n) => n.backendId === null)) {
            this.toastService.warning('Save the flow before exporting', 3000, 'bottom-right');
            return;
        }
        this.triggerPartialExport([], currentFlowId);
    }

    // ── Import ─────────────────────────────────────────────────────

    onImportNodes(
        currentFlowId: number | null,
        hasUnsavedChanges: boolean,
        isReadOnly: boolean,
        onImportComplete: () => void
    ): void {
        if (isReadOnly) return;
        if (!currentFlowId) return;
        if (hasUnsavedChanges) {
            this.toastService.warning('Save the flow before importing', 3000, 'bottom-right');
            return;
        }
        const input = document.createElement('input');
        input.type = 'file';
        input.accept = '.json';
        input.value = '';
        input.onchange = (e: Event) => {
            const file = (e.target as HTMLInputElement).files?.[0];
            if (!file || !currentFlowId) return;
            this.doPartialImport(file, currentFlowId, onImportComplete);
        };
        input.click();
    }

    /**
     * If a post-import shift is pending, applies it to the incoming flow state and clears the flag.
     * Otherwise returns the flow state unchanged.
     */
    processImportedFlowState(flowState: FlowModel): FlowModel {
        if (!this._preImportBackendIds) {
            return flowState;
        }
        const result = this.shiftImportedNodes(flowState, this._preImportBackendIds);
        this._preImportBackendIds = null;
        return result;
    }

    // ── Private helpers ────────────────────────────────────────────

    private triggerPartialExport(nodeIds: string[], currentFlowId: number): void {
        const body = this.buildPartialExportBody(nodeIds);
        const filename = nodeIds.length > 0 ? 'selected-nodes.json' : 'all-nodes.json';
        this.importExportService
            .partialExport(currentFlowId, body)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (blob) => {
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

    private doPartialImport(file: File, currentFlowId: number, onImportComplete: () => void): void {
        // Through the facade: the backend refuses a file with trigger nodes to a user without Flows:Use, and the
        // facade explains that refusal (nothing is emitted then, so nothing below runs).
        this.flowCopyImportFacade
            .partialImport(currentFlowId, file)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: () => {
                    this.toastService.success('Import successful', 3000, 'bottom-right');
                    const currentNodes = this.flowService.nodes();
                    this._preImportBackendIds = new Set(
                        currentNodes.map((n) => n.backendId).filter((id): id is number => id !== null)
                    );
                    this._importPositionSnapshot = new Map(
                        currentNodes
                            .filter((n): n is typeof n & { backendId: number } => n.backendId !== null)
                            .map((n) => [n.backendId, { x: n.position.x, y: n.position.y }])
                    );
                    this.fitAfterNextFlowChange = true;
                    onImportComplete();
                },
                error: (err: HttpErrorResponse) => {
                    const body = typeof err.error === 'string' ? err.error : JSON.stringify(err.error ?? '');
                    const rawMessage =
                        (err.error as Record<string, string>)?.['message'] ??
                        (err.error as Record<string, string>)?.['detail'] ??
                        null;
                    if (body.includes('node_name must make a unique set')) {
                        this.toastService.error(
                            'Import failed: a Classification Decision Table node with this name already exists in this flow. This is a backend issue — delete the duplicate CDT nodes and try again.',
                            6000,
                            'bottom-right'
                        );
                    } else {
                        this.toastService.error(rawMessage ?? 'Import failed', 3000, 'bottom-right');
                    }
                },
            });
    }

    private shiftImportedNodes(flowState: FlowModel, preImportIds: Set<number>): FlowModel {
        const newNodes = flowState.nodes.filter((n) => n.backendId !== null && !preImportIds.has(n.backendId));

        if (!newNodes.length) return flowState;

        const snapshot = this._importPositionSnapshot;
        this._importPositionSnapshot = null;

        // maxRightX uses snapshot positions so previous imports' shifts are respected
        const maxRightX = flowState.nodes
            .filter((n) => n.backendId !== null && preImportIds.has(n.backendId))
            .reduce((max, n) => {
                const pos = snapshot?.get(n.backendId!) ?? n.position;
                return Math.max(max, pos.x + n.size.width);
            }, 0);

        const minNewX = newNodes.reduce((min, n) => Math.min(min, n.position.x), Infinity);
        const offsetX = maxRightX + 400 - minNewX;
        if (offsetX <= 0) return flowState;

        return {
            ...flowState,
            nodes: flowState.nodes.map((n) => {
                if (n.backendId !== null && preImportIds.has(n.backendId)) {
                    const snapshotPos = snapshot?.get(n.backendId);
                    return snapshotPos ? { ...n, position: snapshotPos } : n;
                }
                return { ...n, position: { ...n.position, x: n.position.x + offsetX } };
            }),
        };
    }
}
