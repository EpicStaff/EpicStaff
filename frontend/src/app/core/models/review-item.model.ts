import { NodeType } from '@shared/models';
import { Observable } from 'rxjs';

import { ImportResult } from './import-result.model';

export interface RawFlowNode {
    /** The node's id in the import file; `null` when the file has none. */
    id: number | null;
    name: string;
    node_type: string;
}

export type FlowNodesByFile = Record<string, RawFlowNode[]>;

/**
 * A node's id in an import file, as both the file reader and the inspect response must read it: only an
 * integer counts (the backend sends `node_id: null` for anything else), so both sides fall back to the name.
 */
export function toFileNodeId(value: unknown): number | null {
    return typeof value === 'number' && Number.isInteger(value) ? value : null;
}

export interface ReviewPythonCode {
    code: string;
    entrypoint: string;
    libraries: string;
    global_kwargs: Record<string, unknown>;
}

export interface PythonCodeToolReviewItem {
    kind: 'python_code_tool';
    name: string;
    description: string | null;
    python_code: ReviewPythonCode;
    variables: unknown[];
    use_storage: boolean;
}

export interface McpToolReviewItem {
    kind: 'mcp_tool';
    name: string;
    transport: string;
}

export interface FlowNodeReviewItem {
    kind: 'flow_node';
    flow_name: string;
    /** The node's id in the import file (backend inspect `_project_flow_nodes`); `null` when the file has none. */
    node_id: number | null;
    node_name: string | null;
    node_type: string;
    python_code?: ReviewPythonCode;
    pre_python_code?: ReviewPythonCode;
    post_python_code?: ReviewPythonCode;
}

export type ReviewItem = PythonCodeToolReviewItem | McpToolReviewItem | FlowNodeReviewItem;

export interface InspectResult {
    review_items: ReviewItem[];
}

export function hasReviewableItems(reviewItems: ReviewItem[]): boolean {
    return reviewItems.length > 0;
}

export interface ImportReviewDialogData {
    importResult: ImportResult;
    reviewItems?: ReviewItem[];
    allFlowNodes?: FlowNodesByFile;
    importFn: () => Observable<unknown>;
}

export type ImportReviewDialogCloseResult = { action: 'cancel' } | { action: 'imported'; result: unknown };

const BACKEND_NODE_TYPE_MAP: Record<string, NodeType> = {
    PythonNode: NodeType.PYTHON,
    ClassificationDecisionTableNode: NodeType.CLASSIFICATION_TABLE,
    WebhookTriggerNode: NodeType.WEBHOOK_TRIGGER,
    TelegramTriggerNode: NodeType.TELEGRAM_TRIGGER,
    AgentNode: NodeType.AGENT,
    TaskNode: NodeType.TASK,
    SubgraphNode: NodeType.SUBGRAPH,
    StartNode: NodeType.START,
    EndNode: NodeType.END,
    FileExtractorNode: NodeType.FILE_EXTRACTOR,
    AudioTranscriptionNode: NodeType.AUDIO_TO_TEXT,
    ScheduleTriggerNode: NodeType.SCHEDULE_TRIGGER,
    DecisionTableNode: NodeType.TABLE,
    GraphNote: NodeType.NOTE,
    KeyValueNode: NodeType.KEY_VALUE,
};

export function mapBackendNodeType(backendType: string): NodeType | null {
    return BACKEND_NODE_TYPE_MAP[backendType] ?? null;
}
