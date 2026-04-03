import { GetAudioToTextNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/audio-to-text.model';
import { GetCodeAgentNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/code-agent-node.model';
import { ConditionalEdge } from '../../../pages/flows-page/components/flow-visual-programming/models/conditional-edge.model';
import { CrewNode } from '../../../pages/flows-page/components/flow-visual-programming/models/crew-node.model';
import { GetDecisionTableNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/decision-table-node.model';
import { Edge } from '../../../pages/flows-page/components/flow-visual-programming/models/edge.model';
import { EndNode } from '../../../pages/flows-page/components/flow-visual-programming/models/end-node.model';
import { GetFileExtractorNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/file-extractor.model';
import { GraphNote } from '../../../pages/flows-page/components/flow-visual-programming/models/graph-note.model';
import { GetLLMNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/llm-node.model';
import { PythonNode } from '../../../pages/flows-page/components/flow-visual-programming/models/python-node.model';
import { SubGraphNode } from '../../../pages/flows-page/components/flow-visual-programming/models/subgraph-node.model';
import { GetTelegramTriggerNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/telegram-trigger.model';
import { GetWebhookTriggerNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/webhook-trigger';
import {
    AudioToTextNodeModel,
    BaseNodeModel,
    CodeAgentNodeModel,
    DecisionTableNodeModel,
    EdgeNodeModel,
    EndNodeModel,
    FileExtractorNodeModel,
    GraphNoteModel,
    LLMNodeModel,
    NodeModel,
    ProjectNodeModel,
    PythonNodeModel,
    SubGraphNodeModel,
    TelegramTriggerNodeModel,
    WebhookTriggerNodeModel,
} from '../../core/models/node.model';

// ---- UI metadata stored in each node's backend `metadata` JSON field ----

export interface NodeUIMetadata extends Record<string, unknown> {
    position: { x: number; y: number };
    color: string;
    icon: string;
    size: { width: number; height: number };
    nodeNumber?: number;
}

/**
 * Gets UI-specific metadata from a node model for comparison and storage
 * in the backend's `metadata` JSONField. Shared between save-graph.diff and
 * save-graph.comparators to avoid circular imports.
 */
export function getUIMetadataForComparison(node: BaseNodeModel): NodeUIMetadata {
    return {
        position: node.position,
        color: node.color,
        icon: node.icon,
        size: node.size,
        nodeNumber: node.nodeNumber,
    };
}

// ---- Generic diff result ----

export interface NodeDiff<TBackend, TUI> {
    toDelete: TBackend[];
    toCreate: TUI[];
    toUpdate: Array<{ backend: TBackend; ui: TUI }>;
}

/** Mapping returned after a POST create — ties a UI node UUID to its new backend ID. */
export interface CreatedNodeMapping {
    uiNodeId: string;
    backendId: number;
}

/** Result of executing a diff: raw HTTP results + mappings for created nodes. */
export interface NodeDiffResult {
    results: unknown[];
    createdMappings: CreatedNodeMapping[];
}

// ---- Intermediate types ----

/** An EdgeNodeModel paired with its resolved source/target node UUIDs and backend IDs. */
export interface ResolvedConditionalEdge {
    edgeNode: EdgeNodeModel;
    sourceNodeUuid: string | null;
    targetNodeUuid: string | null;
    sourceBackendId: number | null;
    targetBackendId: number | null;
}

/**
 * A UI connection reduced to source/target UUIDs and (possibly) backend IDs.
 * Backend IDs are resolved after Phase 1 of the save.
 */
export interface UiEdge {
    sourceNodeUuid: string;
    targetNodeUuid: string;
    sourceBackendId: number | null;
    targetBackendId: number | null;
}

/** An edge fully resolved to backend IDs, ready for API payload. */
export interface ResolvedUiEdge {
    start_node_id: number;
    end_node_id: number;
}

// ---- Previous state (what the backend currently has) ----

export interface GraphPreviousState {
    crewNodes: CrewNode[];
    pythonNodes: PythonNode[];
    llmNodes: GetLLMNodeRequest[];
    fileExtractorNodes: GetFileExtractorNodeRequest[];
    audioToTextNodes: GetAudioToTextNodeRequest[];
    subGraphNodes: SubGraphNode[];
    webhookTriggerNodes: GetWebhookTriggerNodeRequest[];
    telegramTriggerNodes: GetTelegramTriggerNodeRequest[];
    conditionalEdges: ConditionalEdge[];
    edges: Edge[];
    endNodes: EndNode[];
    decisionTableNodes: GetDecisionTableNodeRequest[];
    graphNotes: GraphNote[];
    codeAgentNodes: GetCodeAgentNodeRequest[];
}

// ---- New state (what the UI currently shows) ----

export interface GraphNewState {
    crewNodes: ProjectNodeModel[];
    pythonNodes: PythonNodeModel[];
    llmNodes: LLMNodeModel[];
    fileExtractorNodes: FileExtractorNodeModel[];
    audioToTextNodes: AudioToTextNodeModel[];
    subGraphNodes: SubGraphNodeModel[];
    webhookTriggerNodes: WebhookTriggerNodeModel[];
    telegramTriggerNodes: TelegramTriggerNodeModel[];
    /** Edge nodes resolved with their source/target UUIDs and backend IDs. */
    conditionalEdges: ResolvedConditionalEdge[];
    /** Plain connections reduced to source/target UUIDs and backend IDs. */
    edges: UiEdge[];
    endNodes: EndNodeModel[];
    decisionTableNodes: DecisionTableNodeModel[];
    graphNotes: GraphNoteModel[];
    codeAgentNodes: CodeAgentNodeModel[];
    /** All UI nodes — used to resolve UUID → backendId for decision tables/edges. */
    allNodes: NodeModel[];
}

// ---- Node-only diff (Phase 1) ----

export interface NodeOnlyDiff {
    crewNodes: NodeDiff<CrewNode, ProjectNodeModel>;
    pythonNodes: NodeDiff<PythonNode, PythonNodeModel>;
    llmNodes: NodeDiff<GetLLMNodeRequest, LLMNodeModel>;
    fileExtractorNodes: NodeDiff<GetFileExtractorNodeRequest, FileExtractorNodeModel>;
    audioToTextNodes: NodeDiff<GetAudioToTextNodeRequest, AudioToTextNodeModel>;
    subGraphNodes: NodeDiff<SubGraphNode, SubGraphNodeModel>;
    webhookTriggerNodes: NodeDiff<GetWebhookTriggerNodeRequest, WebhookTriggerNodeModel>;
    telegramTriggerNodes: NodeDiff<GetTelegramTriggerNodeRequest, TelegramTriggerNodeModel>;
    decisionTableNodes: NodeDiff<GetDecisionTableNodeRequest, DecisionTableNodeModel>;
    endNodes: NodeDiff<EndNode, EndNodeModel>;
    graphNotes: NodeDiff<GraphNote, GraphNoteModel>;
    codeAgentNodes: NodeDiff<GetCodeAgentNodeRequest, CodeAgentNodeModel>;
}

// ---- Connection diff (Phase 2 — after node IDs are known) ----

export interface ConnectionDiff {
    conditionalEdges: NodeDiff<ConditionalEdge, ResolvedConditionalEdge>;
    edges: { toDelete: Edge[]; toCreate: ResolvedUiEdge[] };
}

// ---- Full graph diff (combined) ----

export interface GraphDiff extends NodeOnlyDiff, ConnectionDiff {}
