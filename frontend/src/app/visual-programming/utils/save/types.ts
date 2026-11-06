import { ConnectionModel } from '../../core/models/connection.model';
import {
    AgentNodeModel,
    AudioToTextNodeModel,
    ClassificationDecisionTableNodeModel,
    DecisionTableNodeModel,
    EndNodeModel,
    FileExtractorNodeModel,
    GraphNoteModel,
    KeyValueNodeModel,
    KnowledgeRetrieverNodeModel,
    PythonNodeModel,
    ScheduleTriggerNodeModel,
    StartNodeModel,
    SubGraphNodeModel,
    TaskNodeModel,
    TelegramTriggerNodeModel,
    WebhookTriggerNodeModel,
} from '../../core/models/node.model';

export interface NodeDiff<T> {
    toCreate: T[];
    toUpdate: Array<{ previous: T; current: T }>;
    toDelete: T[];
}

export interface NodeDiffByType {
    startNodes: NodeDiff<StartNodeModel>;
    pythonNodes: NodeDiff<PythonNodeModel>;
    taskNodes: NodeDiff<TaskNodeModel>;
    agentNodes: NodeDiff<AgentNodeModel>;
    fileExtractorNodes: NodeDiff<FileExtractorNodeModel>;
    audioToTextNodes: NodeDiff<AudioToTextNodeModel>;
    endNodes: NodeDiff<EndNodeModel>;
    subgraphNodes: NodeDiff<SubGraphNodeModel>;
    webhookNodes: NodeDiff<WebhookTriggerNodeModel>;
    telegramNodes: NodeDiff<TelegramTriggerNodeModel>;
    scheduleNodes: NodeDiff<ScheduleTriggerNodeModel>;
    decisionTableNodes: NodeDiff<DecisionTableNodeModel>;
    noteNodes: NodeDiff<GraphNoteModel>;
    classificationDecisionTableNodes: NodeDiff<ClassificationDecisionTableNodeModel>;
    knowledgeRetrieverNodes: NodeDiff<KnowledgeRetrieverNodeModel>;
    keyValueNodes: NodeDiff<KeyValueNodeModel>;
}

export interface ConnectionDiff {
    toCreate: ConnectionModel[];
    toDelete: ConnectionModel[];
    toUpdate: ConnectionModel[];
}

/**
 * Identity keys of a node item the bulk save creates. `node_number_hint` is wire-only and sent
 * for numbered node types alone. It is an ordering key: the server sorts this save's new nodes by
 * it and numbers them consecutively from the graph's counter, so the number the canvas shows may
 * differ from the hint. `uuid` is the node's stable identity, sent on create only (the backend keeps it
 * immutable).
 */
export interface CreatedNodeItemKeys {
    id: null;
    temp_id: string;
    uuid?: string;
    node_number_hint?: number;
}
