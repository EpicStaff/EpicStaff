import { CrewNode } from '../../../pages/flows-page/components/flow-visual-programming/models/crew-node.model';
import { PythonNode } from '../../../pages/flows-page/components/flow-visual-programming/models/python-node.model';
import { GetLLMNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/llm-node.model';
import { GetFileExtractorNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/file-extractor.model';
import { GetAudioToTextNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/audio-to-text.model';
import { SubGraphNode } from '../../../pages/flows-page/components/flow-visual-programming/models/subgraph-node.model';
import { GetWebhookTriggerNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/webhook-trigger';
import { GetTelegramTriggerNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/telegram-trigger.model';
import { ConditionalEdge } from '../../../pages/flows-page/components/flow-visual-programming/models/conditional-edge.model';
import { Edge } from '../../../pages/flows-page/components/flow-visual-programming/models/edge.model';
import { EndNode } from '../../../pages/flows-page/components/flow-visual-programming/models/end-node.model';
import { GetDecisionTableNodeRequest } from '../../../pages/flows-page/components/flow-visual-programming/models/decision-table-node.model';
import { NoteNode } from '../../../pages/flows-page/components/flow-visual-programming/models/note-node.model';
import {
    BaseNodeModel,
    ProjectNodeModel,
    PythonNodeModel,
    LLMNodeModel,
    FileExtractorNodeModel,
    AudioToTextNodeModel,
    SubGraphNodeModel,
    WebhookTriggerNodeModel,
    TelegramTriggerNodeModel,
    EndNodeModel,
    EdgeNodeModel,
    DecisionTableNodeModel,
    NoteNodeModel,
    NodeModel,
} from '../../core/models/node.model';

// ---- UI metadata stored in each node's backend `metadata` JSON field ----

export interface NodeUIMetadata {
    position: { x: number; y: number };
    color: string;
    icon: string;
    size: { width: number; height: number };
    parentId: string | null;
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
        parentId: node.parentId,
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
    results: any[];
    createdMappings: CreatedNodeMapping[];
}

// ---- Intermediate types ----

/** An EdgeNodeModel paired with its resolved source and target node names. */
export interface ResolvedConditionalEdge {
    edgeNode: EdgeNodeModel;
    sourceName: string | null;
    targetName: string | null;
}

/** A plain connection reduced to its start/end node names. */
export interface UiEdge {
    start_key: string;
    end_key: string;
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
    noteNodes: NoteNode[];
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
    /** Edge nodes resolved with their source node name (needed for backend matching). */
    conditionalEdges: ResolvedConditionalEdge[];
    /** Plain connections reduced to start/end node names. */
    edges: UiEdge[];
    endNodes: EndNodeModel[];
    decisionTableNodes: DecisionTableNodeModel[];
    noteNodes: NoteNodeModel[];
    /** All UI nodes — used to resolve node ID → node_name for decision tables. */
    allNodes: NodeModel[];
}

// EndNodes now use NodeDiff like other nodes (matching by node_name)

// ---- Full graph diff ----

export interface GraphDiff {
    crewNodes: NodeDiff<CrewNode, ProjectNodeModel>;
    pythonNodes: NodeDiff<PythonNode, PythonNodeModel>;
    llmNodes: NodeDiff<GetLLMNodeRequest, LLMNodeModel>;
    fileExtractorNodes: NodeDiff<GetFileExtractorNodeRequest, FileExtractorNodeModel>;
    audioToTextNodes: NodeDiff<GetAudioToTextNodeRequest, AudioToTextNodeModel>;
    subGraphNodes: NodeDiff<SubGraphNode, SubGraphNodeModel>;
    webhookTriggerNodes: NodeDiff<GetWebhookTriggerNodeRequest, WebhookTriggerNodeModel>;
    telegramTriggerNodes: NodeDiff<GetTelegramTriggerNodeRequest, TelegramTriggerNodeModel>;
    conditionalEdges: NodeDiff<ConditionalEdge, ResolvedConditionalEdge>;
    decisionTableNodes: NodeDiff<GetDecisionTableNodeRequest, DecisionTableNodeModel>;
    /** Edges only support create/delete — no meaningful "update" exists. */
    edges: { toDelete: Edge[]; toCreate: UiEdge[] };
    endNodes: NodeDiff<EndNode, EndNodeModel>;
    noteNodes: NodeDiff<NoteNode, NoteNodeModel>;
}

