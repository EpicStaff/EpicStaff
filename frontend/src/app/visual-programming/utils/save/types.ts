import { ConnectionModel } from '../../core/models/connection.model';
import {
    AudioToTextNodeModel,
    CodeAgentNodeModel,
    DecisionTableNodeModel,
    EndNodeModel,
    FileExtractorNodeModel,
    GraphNoteModel,
    LLMNodeModel,
    ProjectNodeModel,
    PythonNodeModel,
    StartNodeModel,
    SubGraphNodeModel,
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
    crewNodes: NodeDiff<ProjectNodeModel>;
    pythonNodes: NodeDiff<PythonNodeModel>;
    llmNodes: NodeDiff<LLMNodeModel>;
    fileExtractorNodes: NodeDiff<FileExtractorNodeModel>;
    audioToTextNodes: NodeDiff<AudioToTextNodeModel>;
    endNodes: NodeDiff<EndNodeModel>;
    subgraphNodes: NodeDiff<SubGraphNodeModel>;
    webhookNodes: NodeDiff<WebhookTriggerNodeModel>;
    telegramNodes: NodeDiff<TelegramTriggerNodeModel>;
    decisionTableNodes: NodeDiff<DecisionTableNodeModel>;
    noteNodes: NodeDiff<GraphNoteModel>;
    codeAgentNodes: NodeDiff<CodeAgentNodeModel>;
}

export interface ConnectionDiff {
    toCreate: ConnectionModel[];
    toDelete: ConnectionModel[];
    toUpdate: ConnectionModel[];
}
