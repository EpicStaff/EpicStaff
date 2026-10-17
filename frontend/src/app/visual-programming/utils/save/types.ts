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
 * for numbered node types alone: the number the canvas shows, which the server keeps when it is
 * still free in the block it numbers this save's new nodes from, and replaces otherwise.
 */
export interface CreatedNodeItemKeys {
    id: null;
    temp_id: string;
    node_number_hint?: number;
}
