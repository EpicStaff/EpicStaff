import { Injectable } from '@angular/core';
import { forkJoin, Observable, of, throwError } from 'rxjs';
import { catchError, map, switchMap } from 'rxjs/operators';

import { FlowsApiService } from '../../../features/flows/services/flows-api.service';
import { GraphDto, UpdateGraphDtoRequest } from '../../../features/flows/models/graph.model';
import { FlowModel } from '../../core/models/flow.model';
import { ToastService } from '../../../services/notifications/toast.service';

import { ConditionalEdgeService } from '../../../pages/flows-page/components/flow-visual-programming/services/conditional-edge.service';
import { CrewNodeService } from '../../../pages/flows-page/components/flow-visual-programming/services/crew-node.service';
import { EdgeService } from '../../../pages/flows-page/components/flow-visual-programming/services/edge.service';
import { LLMNodeService } from '../../../pages/flows-page/components/flow-visual-programming/services/llm-node.service';
import { PythonNodeService } from '../../../pages/flows-page/components/flow-visual-programming/services/python-node.service';
import { FileExtractorService } from '../../../pages/flows-page/components/flow-visual-programming/services/file-extractor.service';
import { AudioToTextService } from '../../../pages/flows-page/components/flow-visual-programming/services/audio-to-text-node';
import { WebhookTriggerNodeService } from '../../../pages/flows-page/components/flow-visual-programming/services/webhook-trigger.service';
import { TelegramTriggerNodeService } from '../../../pages/flows-page/components/flow-visual-programming/services/telegram-trigger-node.service';
import { EndNodeService } from '../../../pages/flows-page/components/flow-visual-programming/services/end-node.service';
import { SubGraphNodeService } from '../../../pages/flows-page/components/flow-visual-programming/services/subgraph-node.service';
import { DecisionTableNodeService } from '../../../pages/flows-page/components/flow-visual-programming/services/decision-table-node.service';
import { NoteNodeService } from '../../../pages/flows-page/components/flow-visual-programming/services/note-node.service';

import { NodeDiff, GraphDiff, NodeDiffResult, CreatedNodeMapping } from './save-graph.types';
import {
    extractPreviousState,
    extractNewState,
    getGraphDiff,
    buildCrewPayload,
    buildPythonPayload,
    buildLLMPayload,
    buildFileExtractorPayload,
    buildAudioToTextPayload,
    buildSubGraphPayload,
    buildWebhookPayload,
    buildTelegramPayload,
    buildCondEdgePayload,
    buildEdgePayload,
    buildEndNodePayload,
    buildDecisionTablePayload,
    buildNoteNodePayload,
} from './save-graph.diff';

@Injectable({
    providedIn: 'root',
})
export class GraphUpdateService {
    constructor(
        private crewNodeService: CrewNodeService,
        private pythonNodeService: PythonNodeService,
        private conditionalEdgeService: ConditionalEdgeService,
        private edgeService: EdgeService,
        private graphService: FlowsApiService,
        private llmNodeService: LLMNodeService,
        private fileExtractorService: FileExtractorService,
        private audioToTextService: AudioToTextService,
        private webhookTriggerService: WebhookTriggerNodeService,
        private telegramTriggerService: TelegramTriggerNodeService,
        private endNodeService: EndNodeService,
        private subGraphNodeService: SubGraphNodeService,
        private decisionTableNodeService: DecisionTableNodeService,
        private noteNodeService: NoteNodeService,
        private toastService: ToastService
    ) {}

    // ─────────────────────────────────────────────────────────────────────────
    // Private helpers — RxJS execution of diff operations
    // ─────────────────────────────────────────────────────────────────────────

    /**
     * Executes delete / create / update operations from a diff in parallel.
     *
     * Returns `NodeDiffResult` which includes `createdMappings` — a list of
     * `{ uiNodeId, backendId }` pairs so callers can patch UI nodes with their
     * newly-assigned backend IDs after a POST.
     *
     * @param diff - The diff result containing nodes to delete, create, and update
     * @param deleteOperation - Function that performs HTTP DELETE for a backend node
     * @param createOperation - Function that performs HTTP POST for a UI node
     * @param updateOperation - Function that performs HTTP PUT for a UI node (takes backendId + UI node)
     * @param getUINodeId - Extracts the UI node's UUID (`id`) from the generic TUI so we can
     *                      map the POST response's backend `id` back to the correct UI node.
     */
    private executeNodeDiff<TBackend extends { id: number }, TUI>(
        diff: NodeDiff<TBackend, TUI>,
        deleteOperation: (node: TBackend) => Observable<any>,
        createOperation: (node: TUI) => Observable<any>,
        updateOperation: (backendId: number, node: TUI) => Observable<any>,
        getUINodeId: (node: TUI) => string
    ): Observable<NodeDiffResult> {
        const operations: Observable<{ type: string; uiNodeId?: string; result: any }>[] = [
            ...diff.toDelete.map(n =>
                deleteOperation(n).pipe(
                    map(r => ({ type: 'delete', result: r })),
                    catchError(err => throwError(() => err))
                )
            ),
            ...diff.toCreate.map(n =>
                createOperation(n).pipe(
                    map(r => ({ type: 'create', uiNodeId: getUINodeId(n), result: r })),
                    catchError(err => throwError(() => err))
                )
            ),
            ...diff.toUpdate.map(({ backend, ui }) =>
                updateOperation(backend.id, ui).pipe(
                    map(r => ({ type: 'update', result: r })),
                    catchError(err => throwError(() => err))
                )
            ),
        ];

        if (!operations.length) {
            return of({ results: [], createdMappings: [] });
        }

        return forkJoin(operations).pipe(
            map(results => {
                const createdMappings: CreatedNodeMapping[] = results
                    .filter(r => r.type === 'create' && r.uiNodeId && r.result?.id != null)
                    .map(r => ({ uiNodeId: r.uiNodeId!, backendId: r.result.id }));

                return { results, createdMappings };
            })
        );
    }

    private applyEdgeDiff(
        diff: GraphDiff['edges'],
        graphId: number
    ): Observable<any[]> {
        const ops: Observable<any>[] = [
            ...diff.toDelete.map(e =>
                this.edgeService.deleteEdge(e.id).pipe(catchError(err => throwError(() => err)))
            ),
            ...diff.toCreate.map(e =>
                this.edgeService.createEdge(buildEdgePayload(e, graphId))
                    .pipe(catchError(err => throwError(() => err)))
            ),
        ];
        return ops.length ? forkJoin(ops) : of([]);
    }


    /**
     * Extracts only truly UI-only elements for storage in `graph.metadata`.
     * Notes are now backend-managed, so metadata only stores an empty state
     * (kept for backwards compatibility / future UI-only nodes).
     */
    private buildGraphMetadata(_flowState: FlowModel): Partial<FlowModel> {
        return { nodes: [], connections: [] };
    }

    // ─────────────────────────────────────────────────────────────────────────
    // Public API
    // ─────────────────────────────────────────────────────────────────────────

    public saveGraph(
        flowState: FlowModel,
        graph: GraphDto
    ): Observable<{
        graph: GraphDto;
        updatedNodes: Record<string, any>;
        createdMappings: CreatedNodeMapping[];
    }> {
        // ── 1. Extract what is currently saved in the backend ────────────────
        const previousState = extractPreviousState(graph);

        // ── 2. Extract what the user currently has in the UI ─────────────────
        const newState = extractNewState(flowState);

        // ── 3. Get the diff (pure, no side effects) ───────────────────────────
        const diff = getGraphDiff(previousState, newState);

        const { id: graphId } = graph;
        const allNodes = newState.allNodes;

        // ── 4. Apply the diff — send only what changed to the backend ─────────
        return forkJoin({
            crewNodes: this.executeNodeDiff(
                diff.crewNodes,
                n => this.crewNodeService.deleteCrewNode(n.id.toString()),
                n => this.crewNodeService.createCrewNode(buildCrewPayload(n, graphId)),
                (id, n) => this.crewNodeService.updateCrewNode(id, buildCrewPayload(n, graphId)),
                n => n.id
            ),
            pythonNodes: this.executeNodeDiff(
                diff.pythonNodes,
                n => this.pythonNodeService.deletePythonNode(n.id.toString()),
                n => this.pythonNodeService.createPythonNode(buildPythonPayload(n, graphId)),
                (id, n) => this.pythonNodeService.updatePythonNode(id, buildPythonPayload(n, graphId)),
                n => n.id
            ),
            llmNodes: this.executeNodeDiff(
                diff.llmNodes,
                n => this.llmNodeService.deleteLLMNode(n.id.toString()),
                n => this.llmNodeService.createLLMNode(buildLLMPayload(n, graphId)),
                (id, n) => this.llmNodeService.updateLLMNode(id, buildLLMPayload(n, graphId)),
                n => n.id
            ),
            fileExtractorNodes: this.executeNodeDiff(
                diff.fileExtractorNodes,
                n => this.fileExtractorService.deleteFileExtractorNode(n.id.toString()),
                n => this.fileExtractorService.createFileExtractorNode(buildFileExtractorPayload(n, graphId)),
                (id, n) => this.fileExtractorService.updateFileExtractorNode(id, buildFileExtractorPayload(n, graphId)),
                n => n.id
            ),
            audioToTextNodes: this.executeNodeDiff(
                diff.audioToTextNodes,
                n => this.audioToTextService.deleteAudioToTextNode(n.id.toString()),
                n => this.audioToTextService.createAudioToTextNode(buildAudioToTextPayload(n, graphId)),
                (id, n) => this.audioToTextService.updateAudioToTextNode(id, buildAudioToTextPayload(n, graphId)),
                n => n.id
            ),
            subGraphNodes: this.executeNodeDiff(
                diff.subGraphNodes,
                n => this.subGraphNodeService.deleteSubGraphNode(n.id),
                n => this.subGraphNodeService.createSubGraphNode(buildSubGraphPayload(n, graphId)),
                (id, n) => this.subGraphNodeService.updateSubGraphNode(id, buildSubGraphPayload(n, graphId)),
                n => n.id
            ),
            webhookTriggerNodes: this.executeNodeDiff(
                diff.webhookTriggerNodes,
                n => this.webhookTriggerService.deleteWebhookTriggerNode(n.id.toString()),
                n => this.webhookTriggerService.createWebhookTriggerNode(buildWebhookPayload(n, graphId)),
                (id, n) => this.webhookTriggerService.updateWebhookTriggerNode(id, buildWebhookPayload(n, graphId)),
                n => n.id
            ),
            telegramTriggerNodes: this.executeNodeDiff(
                diff.telegramTriggerNodes,
                n => this.telegramTriggerService.deleteTelegramTriggerNode(n.id),
                n => this.telegramTriggerService.createTelegramTriggerNode(buildTelegramPayload(n, graphId)),
                (id, n) => this.telegramTriggerService.updateTelegramTriggerNode(id, buildTelegramPayload(n, graphId)),
                n => n.id
            ),
            conditionalEdges: this.executeNodeDiff(
                diff.conditionalEdges,
                n => this.conditionalEdgeService.deleteConditionalEdge(n.id),
                n => this.conditionalEdgeService.createConditionalEdge(buildCondEdgePayload(n, graphId)),
                (id, n) => this.conditionalEdgeService.updateConditionalEdge(id, buildCondEdgePayload(n, graphId)),
                n => n.edgeNode.id
            ),
            decisionTableNodes: this.executeNodeDiff(
                diff.decisionTableNodes,
                n => this.decisionTableNodeService.deleteDecisionTableNode(n.id.toString()),
                n => this.decisionTableNodeService.createDecisionTableNode(buildDecisionTablePayload(n, graphId, allNodes)),
                (id, n) => this.decisionTableNodeService.updateDecisionTableNode(id, buildDecisionTablePayload(n, graphId, allNodes)),
                n => n.id
            ),
            edges: this.applyEdgeDiff(diff.edges, graphId),
            endNodes: this.executeNodeDiff(
                diff.endNodes,
                n => this.endNodeService.deleteEndNode(n.id),
                n => this.endNodeService.createEndNode(buildEndNodePayload(n, graphId)),
                (id, n) => this.endNodeService.updateEndNode(id, buildEndNodePayload(n, graphId)),
                n => n.id
            ),
            noteNodes: this.executeNodeDiff(
                diff.noteNodes,
                n => this.noteNodeService.deleteNoteNode(n.id.toString()),
                n => this.noteNodeService.createNoteNode(buildNoteNodePayload(n, graphId)),
                (id, n) => this.noteNodeService.updateNoteNode(id, buildNoteNodePayload(n, graphId)),
                n => n.id
            ),
        }).pipe(
            // ── 5. Collect all created node mappings (uiNodeId → backendId) ───
            switchMap(results => {
                // Gather createdMappings from every node-type diff result
                const allCreatedMappings: CreatedNodeMapping[] = [
                    ...results.crewNodes.createdMappings,
                    ...results.pythonNodes.createdMappings,
                    ...results.llmNodes.createdMappings,
                    ...results.fileExtractorNodes.createdMappings,
                    ...results.audioToTextNodes.createdMappings,
                    ...results.subGraphNodes.createdMappings,
                    ...results.webhookTriggerNodes.createdMappings,
                    ...results.telegramTriggerNodes.createdMappings,
                    ...results.conditionalEdges.createdMappings,
                    ...results.decisionTableNodes.createdMappings,
                    ...results.endNodes.createdMappings,
                    ...results.noteNodes.createdMappings,
                ];

                // ── 6. Update the graph metadata ──────────────────────────────
                const updateRequest: UpdateGraphDtoRequest = {
                        id: graph.id,
                        name: graph.name,
                        description: graph.description,
                    metadata: this.buildGraphMetadata(flowState),
                };

                return this.graphService.updateGraph(graph.id, updateRequest).pipe(
                    map(updatedGraph => {
                                return {
                                    graph: updatedGraph,
                            updatedNodes: results,
                            createdMappings: allCreatedMappings,
                                };
                            })
                        );
            }),
            catchError(err => throwError(() => err))
        );
    }
}
