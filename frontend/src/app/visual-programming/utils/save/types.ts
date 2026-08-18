import { ConnectionModel } from '../../core/models/connection.model';
import {
    AgentNodeModel,
    AudioToTextNodeModel,
    ClassificationDecisionTableNodeModel,
    CodeAgentNodeModel,
    DecisionTableNodeModel,
    EndNodeModel,
    FileExtractorNodeModel,
    GraphNoteModel,
    LLMNodeModel,
    ProjectNodeModel,
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
    crewNodes: NodeDiff<ProjectNodeModel>;
    pythonNodes: NodeDiff<PythonNodeModel>;
    taskNodes: NodeDiff<TaskNodeModel>;
    agentNodes: NodeDiff<AgentNodeModel>;
    llmNodes: NodeDiff<LLMNodeModel>;
    fileExtractorNodes: NodeDiff<FileExtractorNodeModel>;
    audioToTextNodes: NodeDiff<AudioToTextNodeModel>;
    endNodes: NodeDiff<EndNodeModel>;
    subgraphNodes: NodeDiff<SubGraphNodeModel>;
    webhookNodes: NodeDiff<WebhookTriggerNodeModel>;
    telegramNodes: NodeDiff<TelegramTriggerNodeModel>;
    scheduleNodes: NodeDiff<ScheduleTriggerNodeModel>;
    decisionTableNodes: NodeDiff<DecisionTableNodeModel>;
    noteNodes: NodeDiff<GraphNoteModel>;
    codeAgentNodes: NodeDiff<CodeAgentNodeModel>;
    classificationDecisionTableNodes: NodeDiff<ClassificationDecisionTableNodeModel>;
}

export interface ConnectionDiff {
    toCreate: ConnectionModel[];
    toDelete: ConnectionModel[];
    toUpdate: ConnectionModel[];
}
